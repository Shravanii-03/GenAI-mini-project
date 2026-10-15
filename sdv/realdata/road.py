"""
Loader for the ROAD dataset (Verma et al., ORNL; CC-BY 4.0; https://zenodo.org/records/10462796).

The data is NOT part of this repository. Point ROAD_DIR at the extracted `road/` folder, or put it
at the default location below. Signals are anonymised in ROAD ("Signal_3_of_ID"), so nothing here
relies on knowing what a signal means; ground truth comes from the per-row Label and the injection
intervals in the capture metadata.
"""
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

N_SIGNALS = 22


def road_dir() -> Path:
    env = os.environ.get("ROAD_DIR")
    if env:
        return Path(env)
    return Path.home() / "Documents" / "GenAI_project_data" / "road" / "extracted" / "road"


def available() -> bool:
    return (road_dir() / "signal_extractions").exists()


@dataclass
class Capture:
    name: str
    t: np.ndarray               # seconds since capture start, one entry per frame
    ids: np.ndarray             # arbitration IDs (decimal, as in the dataset)
    vals: np.ndarray            # frames x 22 decoded signals, NaN where unused
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

    def signal_keys(self):
        """(id, k) pairs that carry at least one decoded value."""
        keys = []
        for can_id in np.unique(self.ids):
            rows = self.rows_of(can_id)
            present = np.flatnonzero(np.isfinite(self.vals[rows]).any(axis=0))
            keys += [(int(can_id), int(k)) for k in present]
        return keys

    def series(self, can_id: int, k: int):
        rows = self.rows_of(can_id)
        v = self.vals[rows, k]
        keep = np.isfinite(v)
        return self.t[rows][keep], v[keep].astype(np.float64)


def _load_csv(path: Path, max_seconds=None) -> Capture:
    import pandas as pd
    df = pd.read_csv(path)
    t = df["Time"].to_numpy(np.float64)
    if max_seconds is not None:
        df, t = df[t <= max_seconds], t[t <= max_seconds]
    return Capture(
        name=path.stem, t=t, ids=df["ID"].to_numpy(np.int32),
        vals=df.iloc[:, 3:3 + N_SIGNALS].to_numpy(np.float32), labels=df["Label"].to_numpy(np.int8),
    )


def load_signal_csv(path, cache_dir=None, max_seconds=None) -> Capture:
    """Decoded-signal capture, cached as .npz so big files are parsed once."""
    path = Path(path)
    cache = Path(cache_dir) / f"{path.stem}.{max_seconds or 'all'}.npz" if cache_dir else None
    if cache and cache.exists():
        z = np.load(cache)
        return Capture(path.stem, z["t"], z["ids"], z["vals"], z["labels"])
    cap = _load_csv(path, max_seconds)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, t=cap.t, ids=cap.ids, vals=cap.vals, labels=cap.labels)
    return cap


_LOG_LINE = re.compile(r"\(([\d.]+)\)\s+\S+\s+([0-9A-Fa-f]+)#")


def load_raw_log(path):
    """(times in seconds from the first frame, decimal IDs) of a raw candump log."""
    times, ids = [], []
    with open(path, encoding="ascii", errors="ignore") as f:
        for line in f:
            m = _LOG_LINE.match(line)
            if m:
                times.append(float(m.group(1)))
                ids.append(int(m.group(2), 16))
    t = np.array(times, dtype=np.float64)
    return (t - t[0] if len(t) else t), np.array(ids, dtype=np.int32)


def attack_metadata():
    return json.loads((road_dir() / "attacks" / "capture_metadata.json").read_text())


def ambient_metadata():
    return json.loads((road_dir() / "ambient" / "capture_metadata.json").read_text())


def signal_path(kind: str, name: str) -> Path:
    return road_dir() / "signal_extractions" / kind / f"{name}.csv"


def raw_path(kind: str, name: str) -> Path:
    return road_dir() / kind / f"{name}.log"


def merge_events(times, gap: float = 1.0):
    """Collapse alarms closer than `gap` seconds into one event; returns event start times."""
    events, last = [], -math.inf
    for t in sorted(times):
        if t - last > gap:
            events.append(t)
        last = t
    return events
