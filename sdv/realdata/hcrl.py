"""
Loader for the HCRL Car-Hacking dataset (Song, Woo and Kim, Vehicular Communications 21, 2020; Korea University OCSlab;
released for academic use; https://ocslab.hksecurity.net/Datasets/car-hacking-dataset).

The data is NOT part of this repository. Point HCRL_DIR at the folder holding the extracted files, or use the default below.
Two layouts exist in the release:
  * attack files (CSV):  Timestamp, CAN ID (hex), DLC, DATA[0..DLC-1], Flag   with Flag R (normal) or T (injected)
  * the attack-free file (text):  Timestamp: 1479121434.850202    ID: 0350    000    DLC: 8    05 28 84 66 6d 00 00 a2
Both are read into the same Capture. The bit rate is not stated in the release; 500 kbit/s is assumed (and said so wherever used).
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

BITRATE = 500_000


def hcrl_dir() -> Path:
    env = os.environ.get("HCRL_DIR")
    if env:
        return Path(env)
    return Path.home() / "Documents" / "GenAI_project_data" / "hcrl" / "extracted"


@dataclass
class Capture:
    name: str
    t: np.ndarray               # seconds since capture start
    ids: np.ndarray             # arbitration IDs
    dlc: np.ndarray
    labels: np.ndarray          # 1 for injected frames
    _index: dict = field(default_factory=dict, repr=False)

    @property
    def duration(self) -> float:
        return float(self.t[-1] - self.t[0]) if len(self.t) else 0.0

    def rows_of(self, can_id: int) -> np.ndarray:
        if not self._index:
            order = np.argsort(self.ids, kind="stable")
            sorted_ids = self.ids[order]
            bounds = np.flatnonzero(np.diff(sorted_ids)) + 1
            for group in np.split(order, bounds):
                if len(group):
                    self._index[int(self.ids[group[0]])] = group
        return self._index.get(int(can_id), np.empty(0, dtype=np.int64))


_TEXT = re.compile(r"Timestamp:\s*([0-9.]+)\s+ID:\s*([0-9a-fA-F]+)\s+\S+\s+DLC:\s*(\d+)")


def parse_lines(lines, name="capture") -> Capture:
    """Parse CSV or text lines; malformed lines are skipped (the release contains a few truncated ones)."""
    t, ids, dlc, lab = [], [], [], []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            if line.startswith("Timestamp"):
                m = _TEXT.match(line)
                if not m:
                    continue
                row = (float(m.group(1)), int(m.group(2), 16), int(m.group(3)), 0)
            else:
                f = line.split(",")
                flag = f[-1].strip()
                if flag not in ("R", "T"):
                    continue
                row = (float(f[0]), int(f[1], 16), int(f[2]), 1 if flag == "T" else 0)
        except (ValueError, IndexError):
            continue
        t.append(row[0])
        ids.append(row[1])
        dlc.append(row[2])
        lab.append(row[3])
    if not t:
        raise ValueError(f"no frames parsed from {name}")
    t = np.asarray(t, np.float64)
    return Capture(name, t - t[0], np.asarray(ids, np.int32), np.asarray(dlc, np.int8), np.asarray(lab, np.int8))


def load(path, max_frames=None) -> Capture:
    path = Path(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = (line for _, line in zip(range(max_frames), fh)) if max_frames else fh
        return parse_lines(lines, path.stem)


def load_cached(path, cache_dir) -> Capture:
    """load() with a .npz cache next to the data (parsing a 4-million-line file takes about a minute)."""
    path, cache_dir = Path(path), Path(cache_dir)
    cache = cache_dir / (path.stem + ".npz")
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        z = np.load(cache)
        return Capture(path.stem, z["t"], z["ids"], z["dlc"], z["labels"])
    cap = load(path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(cache, t=cap.t, ids=cap.ids, dlc=cap.dlc, labels=cap.labels)
    return cap


def frame_time_s(dlc=8) -> float:
    """Worst-case classical CAN data frame time (11-bit ID, worst-case stuffing) at BITRATE."""
    from sdv.bus.can_bus import frame_bits
    return frame_bits(dlc) / BITRATE


def bursts(cap: Capture, gap_s=0.5):
    """Attack bursts as (start, end) seconds: runs of injected frames separated by more than gap_s."""
    ti = cap.t[cap.labels == 1]
    if not len(ti):
        return []
    cut = np.flatnonzero(np.diff(ti) > gap_s)
    starts = np.r_[ti[0], ti[cut + 1]]
    ends = np.r_[ti[cut], ti[-1]]
    return list(zip(starts.tolist(), ends.tolist()))
