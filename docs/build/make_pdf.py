from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ROOT = r"C:\Users\Shimona\Documents\GenAI_project"
OUT = ROOT + r"\docs\PROJECT_EXPLAINED.pdf"
FIG = ROOT + r"\docs\figs"

NAVY = colors.HexColor("#1f3a5f")
TEAL = colors.HexColor("#2a7f8e")
LIGHT = colors.HexColor("#eef3f8")
GREY = colors.HexColor("#6b7280")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=10, leading=14.5, spaceAfter=6)
h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=16, textColor=NAVY,
                    spaceBefore=14, spaceAfter=6)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=TEAL,
                    spaceBefore=8, spaceAfter=3)
small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.5, textColor=GREY)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=2, spaceAfter=2)
code = ParagraphStyle("code", fontName="Courier", fontSize=7.6, leading=9.6, backColor=colors.HexColor("#f5f6f8"),
                      borderPadding=5, leftIndent=4, rightIndent=4, spaceBefore=3, spaceAfter=8)
cell = ParagraphStyle("cell", parent=body, fontSize=8.8, leading=11.5, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
title = ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=24, textColor=NAVY,
                       alignment=TA_LEFT, leading=28)
callout = ParagraphStyle("callout", parent=body, backColor=LIGHT, borderPadding=7, borderColor=NAVY, borderWidth=0.6,
                         spaceBefore=6, spaceAfter=10)

story = []


def P(text, style=body):
    story.append(Paragraph(text, style))


def B(items):
    for t in items:
        story.append(Paragraph(t, bullet, bulletText="-"))
    story.append(Spacer(1, 4))


def C(text):
    story.append(Preformatted(text.strip("\n"), code))


def table(rows, widths, header=True):
    data = [[Paragraph(str(c), cellb if (header and i == 0) else cell) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d1d9")),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
        style += [("BACKGROUND", (0, i), (-1, i), LIGHT) for i in range(2, len(rows), 2)]
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 8))


def fig(name, width_cm, caption):
    from PIL import Image as PILImage
    w, h = PILImage.open(f"{FIG}\\{name}").size
    story.append(KeepTogether([Image(f"{FIG}\\{name}", width=width_cm * cm, height=width_cm * cm * h / w),
                               Paragraph(caption, small)]))
    story.append(Spacer(1, 6))


# ------------------------------------------------------------------ cover / intro
story.append(Spacer(1, 1.2 * cm))
story.append(Paragraph("Temporal Safety and Threat Detection<br/>for Software-Defined Vehicles", title))
story.append(Spacer(1, 6))
P("<b>The whole project explained simply, with code</b>", ParagraphStyle("sub", parent=body, fontSize=13, textColor=TEAL))
P("Updated on 15 October 2026 from the repository on branch <font face='Courier'>rebuild</font>. Every number in this "
  "document comes from a logged run in <font face='Courier'>experiments/RESULTS.md</font>. Things that are assumed, "
  "unfinished or not proven are said plainly.", small)

story.append(Paragraph("1. What is this project, in one minute?", h1))
P("Modern cars are computers on wheels. Their parts (sensors, brake computer, radar, infotainment) talk to each other "
  "over a shared wire called the <b>CAN bus</b>. That bus has no passwords: any device plugged into it can send "
  "messages that look real. An attacker who gets onto the bus can <b>delay</b> the brake message, <b>flood</b> the wire "
  "so nothing else gets through, or <b>forge</b> the distance the sensor reports so the car thinks the road is clear.")
P("The important question is not only <i>'was an attack detected?'</i> but <i>'was it detected, or stopped, "
  "<b>in time</b> to avoid a crash?'</i> Every crash scenario has a <b>point of no return</b>: the last moment at which "
  "braking can still save you. After that, nothing can.")
story.append(Paragraph(
    "<b>Our idea:</b> build a safe, repeatable test bench (an emulated car), attack it in many ways, measure whether "
    "defences act before the point of no return, add defences that actually remove crashes, and "
    "<b>prove</b> (for our model) how long the brake can be delayed by a given attacker.", callout))

fig("fig1_overview.png", 16.8, "Figure 1. The whole project on one page. Numbers match the sections below.")

# ------------------------------------------------------------------ vehicle
story.append(Paragraph("2. The emulated car (part 3)", h1))
P("We cannot attack a real car, so we built a small <b>discrete-event emulator</b>: a clock that jumps from one event "
  "to the next, in whole microseconds, so a run with the same seed always gives the same answer. It has three layers.")
story.append(Paragraph("2a. The CAN bus", h2))
P("Frames compete for the wire. When the bus is free, the frame with the <b>lowest ID wins</b> (that is how real CAN "
  "works), and nobody can interrupt a frame in progress. A frame's length uses the worst-case bit-stuffing formula from "
  "the CAN literature, at 500 kbit/s. The background traffic comes from the message catalogue in "
  "<font face='Courier'>Knowledge_base/can_messages.json</font>.")
C('''
# sdv/bus/can_bus.py
def frame_bits(dlc: int) -> int:
    return 8 * dlc + 47 + (34 + 8 * dlc - 1) // 4      # worst case; 8 data bytes = 135 bits = 270 us

# when the bus is idle, the pending frame with the lowest identifier wins arbitration
winner = min(self._pending, key=lambda item: (item[1].can_id, item[0]))
''')
story.append(Paragraph("2b. The brake chain", h2))
P("Four steps pass messages over the bus: <b>sensor</b> (sends distance and speed every 10 ms) to "
  "<b>perception</b> (raises a hazard when the reported time-to-collision drops below 2 s) to <b>decision</b> to the "
  "<b>brake actuator</b>. The compute time of each ECU (25, 15 and 25 ms on average, with random jitter and a CPU-load "
  "factor) is <b>assumed</b>; the delays through the bus are not assumed, they emerge from queues and arbitration.")
story.append(Paragraph("2c. The braking physics and the point of no return", h2))
P("A short formula gives the exact answer: the car keeps its speed until the brake takes effect, then braking ramps up "
  "to its maximum. The largest delay that still avoids the obstacle is the point of no return.")
C('''
# sdv/plant/longitudinal.py
def latest_safe_latency_s(v0, d0, decel, ramp_s):
    """Point of no return. Negative means a collision is unavoidable even at zero latency."""
    return (d0 - braking_distance(v0, decel, ramp_s)) / v0
''')
P("Example: at 60 km/h with the obstacle 24 m ahead on a dry road, the car can wait about 353 ms before braking; "
  "after that it hits the obstacle.")
fig("fig2_timeline.png", 15.5,
    "Figure 2. Why timing matters (illustrative numbers). A delay attack pushes the brake past the point of no return; "
    "a second, independent sensor lets the chain start without waiting.")

# ------------------------------------------------------------------ attacks
story.append(Paragraph("3. The attacks (part 4)", h1))
P("Each attack family is a small class with a declared <b>capability</b> (what access the attacker needs) and "
  "<b>parameter bounds</b> (how strong it may be), so a search can explore them fairly.")
table([
    ["Family", "What the attacker does", "Access needed"],
    ["DoS flood, priority abuse, low-and-slow", "Sends many high-priority frames so real ones wait", "a node on the bus"],
    ["Selective suppression", "Drops some of the sensor's frames", "compromised ECU or gateway"],
    ["Gateway delay, jitter injection", "Holds sensor frames back (fixed or random time)", "compromised gateway"],
    ["Sensor drift", "Slowly raises the reported distance", "compromised gateway"],
    ["Masquerade", "Replaces the sensor's frames with forged ones (constant extra distance)", "compromised gateway"],
    ["Dual masquerade", "Forges the sensor <b>and</b> the radar the same way", "compromised gateway"],
], [4.6 * cm, 8.2 * cm, 4.2 * cm])
C('''
# sdv/attacks/library.py  (masquerade: forged frames at the legitimate period)
def flt(frame, now):
    if start <= now < end and frame.can_id == SENSOR_ID and frame.data.get("distance_m") is not None:
        frame.data["distance_m"] += self.bias_m          # the lie
        frame.data["forged"], frame.data["holds_key"] = True, self.holds_key
        return frame, int(self.phase_shift_ms * 1000)
    return frame, 0
''')
P("<b>Hazard volume</b> is the share of an attack family's parameter space that causes a collision, found by sampling "
  "uniformly. Without any defence: masquerade 45%, DoS flood 28%, gateway delay 25%, suppression 4%, jitter 3%.")

# ------------------------------------------------------------------ monitors
story.append(Paragraph("4. Detecting attacks in time (part 6)", h1))
P("<b>Monitors</b> watch the bus (they see frames, never the attacker's label) and raise an alarm: a frame-rate "
  "detector, a plausibility check, a deadline monitor, and a fused combination. All learn what 'normal' looks like from "
  "attack-free runs only. The key measure is borrowed from cyber-physical-systems research (the <i>detection "
  "deadline</i> idea of Akowuah and Kong): the <b>detection margin</b> is how much time was left between the alarm "
  "and the point of no return.")
C('''
# detection margin = (latest safe latency) - (time the alarm came + 20 ms for the response)
# positive: the alarm was early enough to act; negative: too late
''')
B(["<b>Main finding:</b> usual scores (recall, F1) make detectors look good, but the best fused detector flags only "
   "about 63% of attack-caused crashes <i>in time</i>.",
   "<b>A concrete blind spot:</b> a forged sensor that adds a constant distance, starting before the obstacle appears, "
   "looks perfectly self-consistent, so single-sensor checks miss it."])

# ------------------------------------------------------------------ search / LLM
story.append(Paragraph("5. Searching for dangerous attacks (part 5)", h1))
P("The <b>red team</b> looks for attack parameters that cause a crash. We compared random search, grid search, "
  "Q-learning, an evolution strategy, Bayesian optimisation, and an LLM that suggests where to start (grounded in the "
  "knowledge base). <b>Honest result:</b> the clever methods were no better than random sampling in this small space; "
  "the LLM helped only where it named the real mechanism.")

story.append(Paragraph("6. Where the LLM and RAG are used (part 2 and part 6)", h1))
P("<b>Spec agent.</b> A requirement in plain English becomes a machine-checkable rule. RAG looks up real signal "
  "names (the official COVESA vehicle-signal catalogue, 1,382 signals) so the model cannot invent them; a validator "
  "repairs bad output.")
C('''
Requirement : "Brake within 100 ms if an obstacle is detected."
Timing spec : G(obstacle_detected -> F[0,100 ms] brake_applied)      # signal temporal logic, deadline 100 ms
''')
P("<b>Blue agent.</b> After the red team finds an attack the monitors missed, an LLM proposes a new monitor rule, but "
  "a deterministic <b>verifier</b> decides whether it is accepted (at most 2% false alarms on normal runs, and at "
  "least one missed hazard now caught in time).")
C('''
# a verified rule: if the sensor and the radar disagree about distance by more than 1 m, alarm
{'type': 'cross_check', 'id_a': '0x2A0', 'id_b': '0x2B0', 'field': 'distance_m',
 'tol': 1.0, 'max_skew_ms': 15.0}
''')
P("<b>Honest result:</b> random rule proposals plus the same verifier did about as well as the LLM, so the "
  "verifier, not the LLM, does the work. The LLM measurably helps in one place: turning English into specs with the "
  "right signal names (retrieval raises correct-signal matching from about 6% to about 85% on our benchmark).", body)

# ------------------------------------------------------------------ defences
story.append(Paragraph("7. Defences that remove crashes (part 7)", h1))
P("Three defences, each added to the emulated car and each measured against every attack family.")
story.append(Paragraph("7a. Radar failover (experiment E9)", h2))
P("Perception also reads an independent radar and brakes if <b>either</b> channel says the obstacle is close. "
  "A forged sensor alone can no longer hide the road.")
C('''
# sdv/system/brake_chain.py
if frame.data.get("obstacle") and not self._detected:
    ttc = self._reported_ttc(frame)                      # distance / speed
    if ttc is not None and ttc <= self.params.ttc_trigger_s:
        self._start_chain(frame, channel)                # channel is "sensor" OR "radar"
''')
story.append(Paragraph("7b. Gateway guard (experiment E12)", h2))
P("A gateway between the untrusted side (the OBD port, infotainment) and the safety bus lets through only whitelisted "
  "message IDs, at a limited rate. A flood from that side never reaches the safety bus.")
C('''
# sdv/bus/guard.py
if frame.src != UNTRUSTED_SRC:
    return frame, 0                         # only frames from the untrusted side are checked
cycle_ms = self.allowed.get(frame.can_id)
if cycle_ms is None:
    self.blocked += 1
    return None, 0                          # ID not allowed from that side: dropped before arbitration
''')
story.append(Paragraph("7c. Message authentication plus a fail-safe watchdog (experiment E12)", h2))
P("Frames carry a signature (idealised SecOC-style MAC). A gateway that changes a frame invalidates it and it is "
  "rejected. If neither the sensor nor the radar delivers a valid frame for 30 ms, the car brakes anyway (fail-safe).")
C('''
# sdv/system/brake_chain.py
if frame.data.get("forged") and not frame.data.get("holds_key"):
    self.rejected_frames += 1               # MAC verification fails; the frame is discarded
    return
''')
fig("fig3_results.png", 16.8,
    "Figure 3. Measured results (hazard volume = share of the attack space that causes a collision). "
    "Left: radar failover. Right: after adding the gateway guard and authentication.")
table([
    ["Attack", "radar failover only", "all three defences"],
    ["Flood from the untrusted side (OBD/infotainment)", "26.2%", "0.0%"],
    ["Dual-sensor attacker (forges both channels)", "43.3%", "4.3%  (3.0-6.3%)"],
    ["Flood from a node already on the safety bus", "27.3%", "25.0%  (still open)"],
    ["Dual-sensor attacker who holds the signing key", "43.0%", "43.0%  (still open)"],
], [8.2 * cm, 4.2 * cm, 4.6 * cm])
B(["<b>What is left, plainly:</b> a flood from a node already on the safety bus, and an attacker who holds the key. "
   "Authentication moves trust to key management; the guard moves it to the network design.",
   "<b>Costs we measured:</b> authentication adds about 1 ms to normal braking. It stops a single forged channel from "
   "causing unwanted braking, but if both channels are corrupted the watchdog now brakes with nothing in the way "
   "(an availability cost). Radar-only voting without authentication lets a radar forger cause unwanted braking.",
   "<b>Assumptions:</b> the MAC is idealised (key management and freshness not modelled); the 30 ms watchdog and 0.5 ms "
   "verification time are assumed."])

# ------------------------------------------------------------------ bound
story.append(Paragraph("8. Proving a safe limit: the analytic bound (part 8)", h1))
P("Testing shows what happened in the runs we tried. A <b>bound</b> says what can <i>never</i> be exceeded. For a "
  "scenario and an attack, <font face='Courier'>sdv/analysis/bounds.py</font> computes the worst-case time from the "
  "obstacle appearing to the brake acting, using classic CAN response-time analysis plus a model of each attack. "
  "If that time is below the point of no return, <b>no random seed can cause a crash</b>.")
C('''
# L = T_trig + R_channel + P + R_detect + D + R_cmd + A
#   T_trig   when the first frame reporting 'close' can be sent (a forged distance delays it)
#   R_*      worst-case CAN frame response times (queues, blocking, the attacker's frames)
#   P, D, A  worst-case compute times of perception, decision and the brake actuator
proven_safe = latency_bound_ms(scenario, attack, chain).total_ms <= latest_safe_latency_ms(scenario)
''')
B(["<b>It held in every test:</b> 0 violations in more than 31,000 simulated runs per configuration set, and 0 of 260 "
   "adversarial searches (a search that tries to <i>break</i> the bound) found a counter-example.",
   "<b>The adversarial search found three real bugs</b> in my first versions (floods that leave a queue behind). They "
   "are fixed and each has a regression test.",
   "<b>It is conservative:</b> the median bound is about twice the observed latency, so 'unknown' means 'the bound is "
   "too coarse', not 'unsafe'.",
   "<b>It is a proof for the model</b> (assumed compute times, the emulated bus), not for a real vehicle."])

# ------------------------------------------------------------------ evidence & real data
story.append(Paragraph("9. Evidence you can re-check (part 9)", h1))
P("The pipeline writes an <b>evidence bundle</b>: requirement, spec, the attack that caused a crash, the threat it "
  "maps to, the fix, and the outcome under every defence. An <b>auditor</b> then re-runs every claim from scratch "
  "(20 checks) and fails if any number was changed. We tested this by tampering with latencies, bounds, rules and "
  "citations; each is caught. It is checked consistency on an emulation, not a certified safety case.")
story.append(Paragraph("10. Real data: the ROAD dataset (part 10)", h1))
P("To avoid relying only on our emulator, we replayed 13 <b>real</b> attack recordings from one vehicle (Oak Ridge "
  "National Laboratory). Detectors learned only from normal driving. Results: a redundancy cross-check caught real "
  "single-signal forgeries within about 4 ms with zero false alarms on held-out normal data; forgeries that stay inside "
  "the normal range (reverse-light attacks, 0/6) were missed by everything; a simple frame-rate detector was unusable "
  "(about 409 false alarms per hour). ROAD has no braking and no dual-sensor attacker, so it validates the detectors "
  "only, not crashes or margins.")

# ------------------------------------------------------------------ status
story.append(Paragraph("11. Where things stand, and what is not proven", h1))
table([
    ["Item", "Status"],
    ["Emulator, attacks, monitors, search, spec agent, blue loop", "Done, reproducible with one command (also rerun in the cloud), 484 tests pass"],
    ["Defences (failover, guard, authentication) and the analytic bound", "Done, validated by simulation and adversarial search"],
    ["Evidence chain and auditor", "Done, tamper-tested"],
    ["Real attack data (ROAD)", "Done (13 captures, one vehicle): detectors, and the authentication + watchdog defence replayed on the real attacks"],
    ["CARLA check of the braking physics", "Done (4 runs on CARLA 0.9.15): the plant's structure agrees to about 11 ms once calibrated; my default braking numbers are optimistic"],
    ["Research paper", "Not written yet (planned after the CARLA step)"],
], [8.0 * cm, 9.0 * cm])
P("<b>Limits to state honestly in any paper:</b>")
B(["Everything about vehicles is emulated, with <b>assumed</b> ECU timings (a sensitivity test shows the conclusions "
   "survive 0.5x to 2x, but absolute percentages should not be quoted as real-world rates).",
   "Novelty is incremental: the 'detection deadline' idea already exists; our contribution is applying and extending it "
   "to bus-level CAN attacks, the defences, the proof-style bound, and the open, audited artifact. I read one close "
   "related paper (Berdich and Groza) only as an abstract.",
   "Two attacker types are still not stopped: a flood from a node on the safety bus, and a key holder.",
   "The LLM did not beat random proposals for monitor rules; this is reported as a negative result."])

story.append(Paragraph("12. How to run it", h1))
C('''
python -m pytest tests -q                                  # 484 tests
python -m sdv --requirement "Brake within 100 ms if an obstacle is detected." --blue enumerate
python experiments/reproduce_all.py                        # regenerates every result table (about 40 min)
python experiments/e12_defences.py --scenarios 6 --samples 100   # one experiment
''')
P("Key folders: <font face='Courier'>sdv/</font> (the code), <font face='Courier'>experiments/</font> "
  "(E1-E13 and <font face='Courier'>RESULTS.md</font>), <font face='Courier'>docs/</font> (novelty analysis, CARLA "
  "notes), <font face='Courier'>tests/</font>.", body)

story.append(Paragraph("Glossary", h1))
table([
    ["Term", "Meaning"],
    ["CAN bus", "The shared wire that car computers use to talk; no built-in security"],
    ["ECU", "A small computer in the car (sensor, brake controller, ...)"],
    ["Point of no return", "The latest brake delay that still avoids the obstacle"],
    ["Detection margin / deadline", "Time between an alarm and the point of no return"],
    ["Hazard volume", "Share of an attack's parameter space that causes a crash"],
    ["RAG", "Looking facts up in a knowledge base before the LLM answers"],
    ["STL", "Signal temporal logic: a formula such as 'brake within 100 ms'"],
    ["MAC / SecOC", "A signature on each message so forgeries are rejected"],
    ["Red / blue team", "Red looks for attacks; blue builds defences"],
], [4.5 * cm, 12.5 * cm])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.2 * cm, "Temporal Safety and Threat Detection for SDVs - project explained")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                        bottomMargin=2 * cm, title="Project explained", author="Project team")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("built", OUT)
