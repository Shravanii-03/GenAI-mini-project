import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = r"C:\Users\Shimona\Documents\GenAI_project\docs\figs"
os.makedirs(OUT, exist_ok=True)

NAVY, TEAL, ORANGE, GREY, RED, GREEN = "#1f3a5f", "#2a7f8e", "#d9822b", "#6b7280", "#c0392b", "#2e8b57"


def box(ax, x, y, w, h, text, color, fs=9, tc="white"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=color, ec="none"))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc, wrap=True)


def arrow(ax, p, q, color=GREY):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=12, lw=1.4, color=color))


# ---------- Figure 1: the whole project on one page ----------
fig, ax = plt.subplots(figsize=(10, 6.4))
ax.set_xlim(0, 10)
ax.set_ylim(0, 6.4)
ax.axis("off")

box(ax, 0.2, 5.3, 2.2, 0.8, "1. Requirement\n(plain English)", NAVY)
box(ax, 3.0, 5.3, 2.2, 0.8, "2. LLM + RAG spec agent\nmakes a timing rule", NAVY)
box(ax, 5.8, 5.3, 2.0, 0.8, "Timing spec\n(deadline in ms)", GREY)
arrow(ax, (2.4, 5.7), (3.0, 5.7))
arrow(ax, (5.2, 5.7), (5.8, 5.7))

ax.add_patch(FancyBboxPatch((2.2, 2.55), 5.6, 2.35, boxstyle="round,pad=0.02,rounding_size=0.1",
                            fc="#eef3f8", ec=NAVY, lw=1.5))
ax.text(5.0, 4.68, "3. Emulated vehicle (no real car needed)", ha="center", fontsize=10, color=NAVY, weight="bold")
for i, (t, c) in enumerate([("Sensor\n+ radar", TEAL), ("Perception", TEAL), ("Decision", TEAL), ("Brake\nactuator", TEAL)]):
    box(ax, 2.45 + i * 1.32, 3.75, 1.1, 0.7, t, c, fs=8.5)
    if i < 3:
        arrow(ax, (3.55 + i * 1.32, 4.1), (3.77 + i * 1.32, 4.1))
ax.add_patch(FancyBboxPatch((2.45, 3.1), 5.1, 0.42, boxstyle="round,pad=0.01,rounding_size=0.05", fc=ORANGE, ec="none"))
ax.text(5.0, 3.31, "CAN bus (arbitration, queues, background traffic)", ha="center", va="center", fontsize=8.5, color="white")
ax.text(5.0, 2.78, "Braking physics: exact 'point of no return'  ->  collision or safe stop",
        ha="center", fontsize=8.5, color=NAVY)

box(ax, 0.2, 3.3, 1.7, 1.2, "4. Attacks\n9 families\n(flood, forged\nsensor, delay...)", RED, fs=8.5)
arrow(ax, (1.9, 3.9), (2.2, 3.9), RED)
box(ax, 8.1, 3.3, 1.7, 1.2, "7. Defences\nradar failover\ngateway guard\nauthentication", GREEN, fs=8.5)
arrow(ax, (8.1, 3.9), (7.8, 3.9), GREEN)

box(ax, 0.2, 0.9, 1.9, 1.1, "5. Red team search\nfinds attacks that\ncause a crash", RED, fs=8.5)
box(ax, 2.35, 0.9, 1.9, 1.1, "6. Monitors + blue\nrules (LLM proposes,\nverifier decides)", NAVY, fs=8.5)
box(ax, 4.5, 0.9, 1.9, 1.1, "8. Analytic bound\nproves safe for\nany seed", GREEN, fs=8.5)
box(ax, 6.65, 0.9, 1.5, 1.1, "9. Evidence\n+ auditor re-runs\nevery claim", GREY, fs=8.5)
box(ax, 8.4, 0.9, 1.4, 1.1, "10. Real data\nROAD (done)\nCARLA (pending)", ORANGE, fs=8.5)
for x in (1.15, 3.3, 5.45, 7.4, 9.1):
    arrow(ax, (x, 2.0), (x, 2.5), "#9aa5b1")
ax.text(5.0, 0.35, "Everything above is reproducible with one command and checked by 484 automated tests.",
        ha="center", fontsize=9, color=GREY, style="italic")
fig.savefig(os.path.join(OUT, "fig1_overview.png"), dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------- Figure 2: why delay matters (illustrative timeline) ----------
fig, ax = plt.subplots(figsize=(9, 3.0))
ponr = 353
rows = [("Normal driving", [("sense + compute + bus", 75, TEAL)]),
        ("Under a delay attack", [("waiting for the attack to stop", 260, RED), ("then braking chain", 75, TEAL)]),
        ("Same attack + radar failover", [("radar triggers the chain", 80, GREEN)])]
for i, (name, segs) in enumerate(rows[::-1]):
    left = 0
    for label, w, c in segs:
        ax.barh(i, w, left=left, color=c, height=0.5)
        if w > 150:
            ax.text(left + w / 2, i, label, ha="center", va="center", color="white", fontsize=8)
        elif len(segs) == 1:
            ax.text(left + w + 6, i, label, ha="left", va="center", color="black", fontsize=8)
        else:
            ax.text(left + w / 2, i + 0.38, label, ha="center", va="bottom", color="black", fontsize=8)
        left += w
    ax.text(-8, i, name, ha="right", va="center", fontsize=9)
ax.axvline(ponr, color="black", ls="--")
ax.text(ponr + 6, 2.35, "point of no return\n(example: 353 ms)", fontsize=8, va="top")
ax.text(412, 1, "COLLISION", color=RED, fontsize=10, weight="bold", va="center")
ax.set_xlim(0, 480)
ax.set_xlabel("time after the obstacle appears (ms)   [illustrative numbers, not a measurement]")
ax.set_yticks([])
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
fig.savefig(os.path.join(OUT, "fig2_timeline.png"), dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------- Figure 3: measured results ----------
fig, axs = plt.subplots(1, 2, figsize=(10, 3.7))
a = axs[0]
names = ["forged sensor\n(masquerade)", "gateway\ndelay", "DoS flood", "dual-sensor\nattacker"]
before = [44.9, 25.3, 27.8, 47.8]
after = [0.0, 0.0, 27.4, 47.5]
x = range(4)
a.bar([i - 0.2 for i in x], before, 0.4, color=RED, label="no defence")
a.bar([i + 0.2 for i in x], after, 0.4, color=GREEN, label="radar failover")
a.set_xticks(list(x))
a.set_xticklabels(names, fontsize=8)
a.set_ylabel("% of attack space causing a collision")
a.set_title("Experiment E9: redundancy", fontsize=10)
a.set_ylim(0, 56)
a.legend(fontsize=8, frameon=False, loc="upper center", ncol=2)
b = axs[1]
names2 = ["flood from\nOBD/infotainment", "dual-sensor\nattacker", "flood from a node\non the safety bus", "dual attacker\nwith the key"]
v1 = [26.2, 43.3, 27.3, 43.0]
v2 = [0.0, 4.3, 25.0, 43.0]
b.bar([i - 0.2 for i in x], v1, 0.4, color=ORANGE, label="failover only")
b.bar([i + 0.2 for i in x], v2, 0.4, color=GREEN, label="+ guard + authentication")
b.set_xticks(list(x))
b.set_xticklabels(names2, fontsize=8)
b.set_title("Experiment E12: what is left", fontsize=10)
b.set_ylim(0, 56)
b.legend(fontsize=8, frameon=False, loc="upper center", ncol=2)
for ax_ in axs:
    for s in ("top", "right"):
        ax_.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig3_results.png"), dpi=200, bbox_inches="tight")
plt.close(fig)
print("figures done")
