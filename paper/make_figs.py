"""
Figures for the paper (vector PDF, single-column width).

Numbers are not typed in by hand where the code can produce them:
  fig_bound   - the analytic worst-case latency bound for the headline scenario (60 km/h, obstacle at 24 m, CPU load 0.3),
                printed by sdv.analysis.bounds.latency_bound_ms (command in paper/README.md); the point of no return comes
                from sdv.plant.longitudinal.latest_safe_latency_ms.
  fig_defence - hazard volume per attack variant and defence configuration, copied from experiments/RESULTS.md (E12 table).
  fig_carla   - point of no return in CARLA against the closed form (E13, run 4).
  fig_road    - ROAD watchdog threshold trade-off (E15).
  fig_arch    - the emulated system.

    python paper/make_figs.py
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 7, "font.family": "serif", "axes.linewidth": 0.6, "pdf.fonttype": 42})

PONR = 353.2

# ---------------------------------------------------------------- fig_bound
parts = [("trigger + channel", 11.3), ("perception", 51.1), ("decision", 30.7), ("actuator", 45.0), ("detect/command frames", 1.4)]
cases = [
    ("benign", 139.5, True),
    ("flood 3000/s, 400 ms", 148.2, False),
    ("flood 4000/s, 400 ms", 603.9, False),
    ("forged +40 m", 939.5, False),
    ("forged +40 m, failover", 139.5, False),
]
fig, ax = plt.subplots(figsize=(3.45, 2.1))
hatches = ["", "//", "..", "xx", "--"]
for i, (label, total, split) in enumerate(cases):
    y = len(cases) - 1 - i
    if split:
        left = 0.0
        for (name, v), h in zip(parts, hatches):
            ax.barh(y, v, left=left, color="0.85" if h == "" else "white", edgecolor="black", hatch=h, linewidth=0.5, label=name)
            left += v
    else:
        ax.barh(y, total, color="0.75" if total <= PONR else "0.35", edgecolor="black", linewidth=0.5)
    ax.text(total + 14, y, f"{total:.0f} ms", va="center", fontsize=6.5)
ax.axvline(PONR, color="black", linestyle="--", linewidth=0.9)
ax.text(PONR, len(cases) - 0.35, "point of no return 353 ms", fontsize=6.5, ha="center", va="bottom")
ax.set_yticks(range(len(cases)))
ax.set_yticklabels([c[0] for c in reversed(cases)])
ax.set_xlim(0, 1250)
ax.set_ylim(-0.6, len(cases) - 0.1)
ax.set_xlabel("worst-case latency to brake onset (ms)")
ax.legend(loc="upper right", fontsize=5.0, frameon=False, handlelength=1.4, labelspacing=0.15, bbox_to_anchor=(1.0, 1.0))
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(pad=0.3)
fig.savefig(os.path.join(OUT, "fig_bound.pdf"))
plt.close(fig)

# -------------------------------------------------------------- fig_defence
rows = [
    ("single-channel\n(7 families)", [0.0, 0.0, 0.0, 0.0]),
    ("flood,\nuntrusted", [26.2, 0.0, 23.8, 0.0]),
    ("dual-sensor\nforgery", [43.3, 43.3, 4.3, 4.3]),
    ("flood from a\nsafety-bus node", [27.3, 27.3, 25.0, 25.0]),
    ("dual forgery,\nkey holder", [43.0, 43.0, 43.0, 43.0]),
]
configs = ["failover", "+ guard", "+ authentication", "+ guard + authentication"]
hat = ["", "//", "..", "xx"]
fig, ax = plt.subplots(figsize=(3.45, 2.3))
n = len(configs)
w = 0.2
for j, (cfg, h) in enumerate(zip(configs, hat)):
    xs = [i + (j - (n - 1) / 2) * w for i in range(len(rows))]
    vals = [r[1][j] for r in rows]
    ax.bar(xs, vals, width=w * 0.92, color="0.8" if j % 2 == 0 else "0.45", edgecolor="black", hatch=h, linewidth=0.5, label=cfg)
    for x, v in zip(xs, vals):
        if True:
            ax.text(x, v + 0.8, f"{v:.0f}", ha="center", fontsize=5.5)
ax.set_xticks(range(len(rows)))
ax.set_xticklabels([r[0] for r in rows], fontsize=5.6)
ax.set_ylabel("hazard volume (% of attack space)")
ax.set_ylim(0, 58)
ax.legend(fontsize=5.8, frameon=False, loc="upper left", ncol=2, columnspacing=0.8, handlelength=1.4)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(pad=0.3)
fig.savefig(os.path.join(OUT, "fig_defence.pdf"))
plt.close(fig)


# ----------------------------------------------------------------- fig_arch
def box(ax, x, y, w, h, text, fc="white", fs=6.0, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.02", fc=fc, ec="black", lw=0.6, ls=ls))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)


def arrow(ax, x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="-|>", lw=0.7, color="black"))


fig, ax = plt.subplots(figsize=(3.45, 2.4))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
ax.add_patch(plt.Rectangle((0.02, 0.50), 0.96, 0.06, fc="0.8", ec="black", lw=0.6))
ax.text(0.5, 0.53, "safety CAN bus, 500 kbit/s, 9 background messages", ha="center", va="center", fontsize=5.6)
box(ax, 0.02, 0.77, 0.2, 0.17, "primary\nsensor\n0x2A0")
box(ax, 0.26, 0.77, 0.2, 0.17, "radar\n0x2B0\n(redundant)")
box(ax, 0.55, 0.77, 0.19, 0.17, "gateway\nguard", fc="0.9")
box(ax, 0.79, 0.77, 0.19, 0.17, "untrusted\nsegment", ls="--")
for x in (0.12, 0.36):
    arrow(ax, x, 0.77, x, 0.56)
arrow(ax, 0.79, 0.855, 0.74, 0.855)
arrow(ax, 0.645, 0.77, 0.645, 0.56)
box(ax, 0.02, 0.10, 0.32, 0.27, "perception ECU\nMAC, TTC trigger,\nfailover, watchdog", fc="0.92", fs=5.2)
box(ax, 0.39, 0.10, 0.17, 0.27, "decision\nECU 0x1C0", fs=5.6)
box(ax, 0.61, 0.10, 0.16, 0.27, "brake\nECU 0x1A0", fs=5.6)
box(ax, 0.82, 0.10, 0.16, 0.27, "vehicle\nplant", fc="0.9", fs=5.6)
arrow(ax, 0.18, 0.50, 0.18, 0.37)
arrow(ax, 0.34, 0.235, 0.39, 0.235)
arrow(ax, 0.56, 0.235, 0.61, 0.235)
arrow(ax, 0.77, 0.235, 0.82, 0.235)
ax.text(0.5, 0.025, "attackers: forge, delay or drop at the gateway; flood; hold the key", ha="center", fontsize=5.4, style="italic")
fig.savefig(os.path.join(OUT, "fig_arch.pdf"), bbox_inches="tight", pad_inches=0.02)
plt.close(fig)

# ---------------------------------------------------------------- fig_carla
scen = ["40 km/h\n14 m", "50 km/h\n20 m", "60 km/h\n30 m", "80 km/h\n45 m"]
carla = [73, 49, 195, 15]
fitted = [81, 54, 207, 0]          # closed form with CARLA's fitted parameters (-4 ms plotted as 0: collision unavoidable)
default = [527, 530, 713, 584]
fig, ax = plt.subplots(figsize=(3.45, 1.9))
x = np.arange(len(scen))
w = 0.26
ax.bar(x - w, carla, w * 0.92, color="0.2", edgecolor="black", linewidth=0.5, label="CARLA (measured)")
ax.bar(x, fitted, w * 0.92, color="0.75", edgecolor="black", linewidth=0.5, hatch="//", label="closed form, fitted to CARLA")
ax.bar(x + w, default, w * 0.92, color="white", edgecolor="black", linewidth=0.5, hatch="..", label="closed form, default parameters")
for xi, v in zip(x + w, default):
    ax.text(xi, v + 10, f"{v}", ha="center", fontsize=5.5)
ax.set_xticks(x)
ax.set_xticklabels(scen, fontsize=6)
ax.set_ylabel("point of no return (ms)")
ax.set_ylim(0, 900)
ax.legend(fontsize=5.6, frameon=False, loc="upper left", handlelength=1.4)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(pad=0.3)
fig.savefig(os.path.join(OUT, "fig_carla.pdf"))
plt.close(fig)

# ----------------------------------------------------------------- fig_road
ks = [2, 3, 5, 10]
false_per_h = [62.2, 41.5, 38.9, 31.1]
median_ms = [30, 30, 50, 100]
fig, ax = plt.subplots(figsize=(3.45, 1.8))
ax.plot(ks, false_per_h, "o-", color="black", lw=0.8, ms=3, label="false triggers per hour")
ax.set_xlabel("watchdog threshold k (silence = k x period)")
ax.set_ylabel("false triggers / hour")
ax.set_ylim(0, 100)
ax.set_xscale("log")
ax.set_xticks(ks)
ax.set_xticklabels([str(k) for k in ks])
ax.minorticks_off()
ax2 = ax.twinx()
ax2.plot(ks, median_ms, "s--", color="0.4", lw=0.8, ms=3, label="median detection delay")
ax2.set_ylabel("median delay (ms)")
ax2.set_ylim(0, 160)
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, fontsize=5.6, frameon=False, loc="upper right", handlelength=1.8)
ax.spines[["top"]].set_visible(False)
ax2.spines[["top"]].set_visible(False)
fig.tight_layout(pad=0.3)
fig.savefig(os.path.join(OUT, "fig_road.pdf"))
plt.close(fig)
print("wrote", sorted(os.listdir(OUT)))
