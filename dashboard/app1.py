"""
dashboard/app.py — LIVE STREAMING SDV Safety & Threat Detection Dashboard
==========================================================================
Real-time Streamlit dashboard.

Two live data sources:
  1. outputs/ folder — realtime_monitor.py writes live JSON events here
  2. Direct VehicleSimulator + AttackInjector (demo mode if no outputs yet)

Sections:
  1. Live Signal Strip   — speed, brake, TTC, phase, attack status (auto-refresh)
  2. Event Chain         — current event chain timing bars
  3. ISO Violations      — live violation feed
  4. Threat Monitor      — attack type + severity cards
  5. Risk Timeline       — rolling risk score sparkline
  6. Agent Memory        — iteration log from Agent1

Run:
    streamlit run dashboard/app.py
"""

import sys, os, json, time, glob, random, queue, threading
from pathlib import Path
from datetime import datetime

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st

st.set_page_config(
    page_title="SDV Live Monitor",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600;700&display=swap');
html,body,[class*="css"]{font-family:'Barlow',sans-serif;background:#0E1117;color:#E8E8E8;}
.hdr{background:linear-gradient(135deg,#0D1F0D,#0E1117,#0D0D1F);border-bottom:2px solid #00D4AA;padding:14px 24px;margin-bottom:20px;border-radius:0 0 12px 12px;}
.hdr-title{font-family:'Share Tech Mono',monospace;font-size:24px;color:#00D4AA;letter-spacing:2px;margin:0;}
.hdr-sub{color:#555;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-top:3px;}
.sec{font-family:'Share Tech Mono',monospace;font-size:12px;color:#00D4AA;letter-spacing:2px;text-transform:uppercase;border-bottom:1px solid #1E2633;padding-bottom:5px;margin-bottom:12px;}
.sigcard{background:#161B22;border:1px solid #21262D;border-radius:8px;padding:12px 14px;text-align:center;}
.sigval{font-family:'Share Tech Mono',monospace;font-size:26px;font-weight:700;margin:3px 0;}
.siglbl{color:#666;font-size:10px;letter-spacing:2px;text-transform:uppercase;}
.vpass{background:linear-gradient(90deg,#001A10,transparent);border-left:3px solid #00D4AA;padding:7px 12px;border-radius:0 6px 6px 0;color:#00D4AA;font-family:'Share Tech Mono',monospace;font-size:12px;margin-bottom:6px;}
.vfail{background:linear-gradient(90deg,#1A0000,transparent);border-left:3px solid #FF4B4B;padding:7px 12px;border-radius:0 6px 6px 0;color:#FF4B4B;font-family:'Share Tech Mono',monospace;font-size:12px;margin-bottom:6px;}
.atk{background:linear-gradient(90deg,#1A0A00,transparent);border-left:3px solid #FF8C00;padding:7px 12px;border-radius:0 6px 6px 0;color:#FF8C00;font-family:'Share Tech Mono',monospace;font-size:12px;margin-bottom:6px;}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;animation:pulse 1.5s infinite;}
.dg{background:#00D4AA;}.dr{background:#FF4B4B;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.3;}}
div[data-testid="metric-container"]{background:#161B22;border:1px solid #21262D;border-radius:8px;padding:10px 14px;}
.stButton>button{background:linear-gradient(135deg,#00D4AA,#009977);color:#000;font-family:'Share Tech Mono',monospace;font-weight:700;border:none;border-radius:6px;padding:8px 20px;width:100%;}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# STATE INIT
# ══════════════════════════════════════════════════════════════════════════════
def _init():
    defs = {
        "live_frames":      [],          # rolling window of raw frames
        "violations":       [],          # ISO violation events
        "attacks":          [],          # attack events
        "threats":          [],          # GenAI threat outputs
        "risk_history":     [],          # (timestamp, risk_score)
        "sim_running":      False,
        "sim_thread":       None,
        "sim_queue":        None,
        "last_frame":       None,
        "tick_count":       0,
        "outputs_dir":      os.path.join(ROOT, "outputs"),
        "last_file_mtime":  0.0,
        "auto_refresh":     True,
        "refresh_rate":     1,           # seconds
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()
WINDOW = 120   # keep last 120 frames (~6 seconds at 50ms)


# ══════════════════════════════════════════════════════════════════════════════
# LIVE DATA — read from outputs/ folder (written by realtime_monitor.py)
# ══════════════════════════════════════════════════════════════════════════════
def _load_latest_outputs(outputs_dir: str, max_files: int = 30):
    """Read the most recent live_*.json files from realtime_monitor."""
    pattern = os.path.join(outputs_dir, "live_*.json")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)[:max_files]
    frames, violations, attacks, threats = [], [], [], []

    for fpath in reversed(files):
        try:
            with open(fpath) as f:
                data = json.load(f)
        except Exception:
            continue

        frame = data.get("frame", {})
        eval_ = data.get("evaluation", {})
        threat= data.get("threat")

        if frame:
            # Merge evaluation into frame for display
            frame["risk_score"]  = eval_.get("risk_score", 0)
            frame["severity"]    = eval_.get("severity", "LOW")
            frame["violation"]   = eval_.get("violation", False)
            frame["_loaded_at"]  = data.get("timestamp", "")
            frames.append(frame)

            if frame.get("iso_violation_detected") or eval_.get("violation"):
                violations.append(frame)

            atk = frame.get("attack", {})
            if atk.get("active"):
                attacks.append({**atk, "timestamp_ms": frame.get("timestamp_ms", 0),
                                 "speed": frame.get("speed", 0),
                                 "delay_ms": frame.get("delay_ms", 0)})

        if threat:
            threats.append(threat)

    return frames, violations, attacks, threats


# ══════════════════════════════════════════════════════════════════════════════
# DEMO SIMULATOR (fallback when no outputs folder yet)
# ══════════════════════════════════════════════════════════════════════════════
def _demo_frame(tick: int) -> dict:
    """Generate a plausible demo frame so dashboard looks alive immediately."""
    phases = ["normal_driving","cruise_control","obstacle_ahead","emergency_brake",
              "pedestrian_detected","lane_departure"]
    phase = phases[(tick // 20) % len(phases)]
    speed = {"normal_driving":60,"cruise_control":80,"obstacle_ahead":40,
             "emergency_brake":15,"pedestrian_detected":30,"lane_departure":75}.get(phase, 60)
    speed += random.gauss(0, 3)
    brake = {"emergency_brake":95,"obstacle_ahead":50,"pedestrian_detected":35}.get(phase, 0)
    brake += random.gauss(0, 2)
    delay = {"emergency_brake": random.randint(80,145),
             "obstacle_ahead":  random.randint(60,110),}.get(phase, random.randint(40,75))
    iso_viol = delay > 100 and phase == "emergency_brake"
    atk_active = random.random() < 0.15
    atk_type = random.choice(["can_spoofing","delay_injection","speed_spoofing"]) if atk_active else "none"

    event_chain = [
        {"step":"sense",   "time_ms": random.randint(8,15)},
        {"step":"detect",  "time_ms": random.randint(25,40)},
        {"step":"decide",  "time_ms": random.randint(50,75)},
        {"step":"actuate", "time_ms": delay},
    ]
    risk = min(1.0, delay / 100.0 * (1.3 if iso_viol else 0.85))

    return {
        "timestamp_ms":         tick * 50,
        "frame_id":             tick,
        "driving_phase":        phase,
        "vehicle_speed":        round(speed, 1),
        "brake_pedal_position": round(max(0, brake), 1),
        "brake_response_time_ms": round(delay * 0.8, 1),
        "brake_asil_limit_ms":  100,
        "steering_angle":       round(random.gauss(0, 5 if phase=="lane_departure" else 1), 1),
        "obstacle_detected":    phase in ("obstacle_ahead","emergency_brake"),
        "obstacle_distance_m":  round(random.uniform(5,40) if phase in ("obstacle_ahead","emergency_brake") else 999, 1),
        "ttc_seconds":          round(random.uniform(0.5,3) if phase in ("obstacle_ahead","emergency_brake") else 999, 2),
        "pedestrian_detected":  phase == "pedestrian_detected",
        "aeb_active":           phase == "emergency_brake",
        "lane_departure_warning": phase == "lane_departure",
        "can_bus_load_pct":     round(random.uniform(20,60), 1),
        "iso_violation_detected": iso_viol,
        "iso_violation_type":   f"BRAKE_RESPONSE_EXCEEDED ({delay}ms > 100ms)" if iso_viol else "none",
        "iso_rule_id":          "ISO26262-6-8.4.5:ASIL-D" if iso_viol else "",
        "safety_state":         "critical" if iso_viol else "nominal",
        "asil_level":           "ASIL-D",
        "delay_ms":             delay,
        "event_chain":          event_chain,
        "risk_score":           round(risk, 3),
        "severity":             "CRITICAL" if risk>0.85 else "HIGH" if risk>0.65 else "MEDIUM" if risk>0.4 else "LOW",
        "violation":            iso_viol,
        "attack": {
            "active":       atk_active,
            "type":         atk_type,
            "description":  f"{atk_type} injected" if atk_active else "",
        },
        "_source": "demo"
    }


# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="hdr">
    <p class="hdr-title">🚗 SDV LIVE SAFETY & THREAT MONITOR</p>
    <p class="hdr-sub">GenAI · RAG · RL · ISO 26262 · ISO 21434 · VSS 4.0 · Real-Time</p>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<p class="sec">⚙️ Control</p>', unsafe_allow_html=True)

    auto_refresh   = st.toggle("Auto-Refresh", value=True)
    refresh_rate   = st.slider("Refresh every (s)", 0.5, 5.0, 1.0, 0.5)
    outputs_dir    = st.text_input("outputs/ path", value=st.session_state.outputs_dir)
    st.session_state.outputs_dir   = outputs_dir
    st.session_state.auto_refresh  = auto_refresh
    st.session_state.refresh_rate  = refresh_rate

    st.divider()
    st.markdown('<p class="sec">📋 Pipeline</p>', unsafe_allow_html=True)
    st.markdown("""
<div style="color:#666;font-size:11px;line-height:1.8">
Start the pipeline in a terminal:<br>
<code style="color:#00D4AA">python main_pipeline.py</code><br><br>
Or the monitor directly:<br>
<code style="color:#00D4AA">python realtime_monitor.py</code><br><br>
Dashboard reads <code>outputs/live_*.json</code> automatically.
</div>
""", unsafe_allow_html=True)

    st.divider()
    st.markdown('<p class="sec">ℹ️ Status</p>', unsafe_allow_html=True)
    out_exists = os.path.isdir(outputs_dir)
    n_files = len(glob.glob(os.path.join(outputs_dir, "live_*.json"))) if out_exists else 0
    src_color = "dg" if n_files > 0 else "dr"
    src_label = f"{n_files} live files" if n_files > 0 else "DEMO MODE (no outputs yet)"
    st.markdown(f'<span class="dot {src_color}"></span>{src_label}', unsafe_allow_html=True)

    if st.button("🗑️ Clear History"):
        for k in ["live_frames","violations","attacks","threats","risk_history"]:
            st.session_state[k] = []
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCH
# ══════════════════════════════════════════════════════════════════════════════
tick = int(time.time() * 20) % 10000   # synthetic tick for demo

out_dir    = st.session_state.outputs_dir
n_outfiles = len(glob.glob(os.path.join(out_dir, "live_*.json"))) if os.path.isdir(out_dir) else 0

if n_outfiles > 0:
    # Real data from realtime_monitor
    frames, new_viols, new_atks, new_threats = _load_latest_outputs(out_dir)
    if frames:
        st.session_state.live_frames  = (st.session_state.live_frames + frames)[-WINDOW:]
        st.session_state.violations   = (st.session_state.violations + new_viols)[-50:]
        st.session_state.attacks      = (st.session_state.attacks + new_atks)[-50:]
        st.session_state.threats      = (st.session_state.threats + new_threats)[-20:]
        last = frames[-1]
        st.session_state.last_frame   = last
        st.session_state.risk_history = (
            st.session_state.risk_history +
            [{"t": last.get("timestamp_ms",0), "r": last.get("risk_score",0)}]
        )[-200:]
    data_source = "🟢 LIVE"
else:
    # Demo mode — generate synthetic frame
    demo = _demo_frame(tick)
    st.session_state.live_frames  = (st.session_state.live_frames + [demo])[-WINDOW:]
    if demo["violation"]:
        st.session_state.violations = (st.session_state.violations + [demo])[-50:]
    if demo["attack"]["active"]:
        st.session_state.attacks = (
            st.session_state.attacks +
            [{**demo["attack"], "timestamp_ms": demo["timestamp_ms"],
              "speed": demo["vehicle_speed"], "delay_ms": demo["delay_ms"]}]
        )[-50:]
    st.session_state.last_frame = demo
    st.session_state.risk_history = (
        st.session_state.risk_history +
        [{"t": demo["timestamp_ms"], "r": demo["risk_score"]}]
    )[-200:]
    data_source = "🟡 DEMO"

last  = st.session_state.last_frame or {}
lf    = st.session_state.live_frames
rh    = st.session_state.risk_history
viols = st.session_state.violations
atks  = st.session_state.attacks


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📡 Live Signals",
    "⛓️ Event Chain",
    "🚨 Violations & Attacks",
    "📈 Risk Timeline",
    "🔍 Raw Frames",
])


# ────────────────────────────────────────────────────────────────────────────
# TAB 1 — Live Signals
# ────────────────────────────────────────────────────────────────────────────
with tab1:
    # Source + phase banner
    phase_val = last.get("driving_phase", "—")
    safety    = last.get("safety_state", "nominal")
    scolor    = {"critical":"#FF4B4B","degraded":"#FF8C00","nominal":"#00D4AA"}.get(safety,"#00D4AA")
    atk_now   = last.get("attack",{}).get("active", False)

    st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;
     background:#161B22;border:1px solid #21262D;border-radius:8px;
     padding:10px 18px;margin-bottom:16px;">
  <span style="font-family:'Share Tech Mono',monospace;font-size:13px;color:#888">
    {data_source} &nbsp;|&nbsp; Frame #{last.get('frame_id','—')} &nbsp;|&nbsp;
    <span style="color:#00D4AA">{phase_val.upper().replace('_',' ')}</span>
  </span>
  <span style="font-family:'Share Tech Mono',monospace;font-size:13px;color:{scolor}">
    ● {safety.upper()}
    {"&nbsp;&nbsp;⚡ ATTACK ACTIVE" if atk_now else ""}
  </span>
</div>
""", unsafe_allow_html=True)

    # ── Signal cards row 1 ───────────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    speed  = last.get("vehicle_speed", 0)
    brake  = last.get("brake_pedal_position", 0)
    ttc    = last.get("ttc_seconds", 999)
    delay  = last.get("delay_ms", 0)
    limit  = last.get("brake_asil_limit_ms", 100)

    sc = "#FF4B4B" if speed > 100 else "#00D4AA"
    bc = "#FF4B4B" if brake > 80  else "#FFA500" if brake > 40 else "#00D4AA"
    tc = "#FF4B4B" if ttc < 1.5   else "#FFA500" if ttc < 3   else "#00D4AA"
    dc = "#FF4B4B" if delay > limit else "#00D4AA"

    with c1:
        st.markdown(f'<div class="sigcard"><div class="siglbl">Vehicle Speed</div>'
                    f'<div class="sigval" style="color:{sc}">{speed}</div>'
                    f'<div class="siglbl">km/h</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="sigcard"><div class="siglbl">Brake Pedal</div>'
                    f'<div class="sigval" style="color:{bc}">{brake}</div>'
                    f'<div class="siglbl">%</div></div>', unsafe_allow_html=True)
    with c3:
        ttc_disp = f"{ttc:.1f}" if ttc < 100 else "—"
        st.markdown(f'<div class="sigcard"><div class="siglbl">Time-To-Collision</div>'
                    f'<div class="sigval" style="color:{tc}">{ttc_disp}</div>'
                    f'<div class="siglbl">seconds</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="sigcard"><div class="siglbl">Event Delay</div>'
                    f'<div class="sigval" style="color:{dc}">{delay}</div>'
                    f'<div class="siglbl">ms (limit {limit}ms)</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Signal cards row 2 ───────────────────────────────────────────────────
    c5,c6,c7,c8 = st.columns(4)
    steer  = last.get("steering_angle", 0)
    bus    = last.get("can_bus_load_pct", 0)
    rpm    = last.get("engine_rpm", 0)
    risk   = last.get("risk_score", 0)

    rc_color = "#FF4B4B" if risk>0.85 else "#FF8C00" if risk>0.65 else "#FFA500" if risk>0.4 else "#00D4AA"

    with c5:
        st.markdown(f'<div class="sigcard"><div class="siglbl">Steering Angle</div>'
                    f'<div class="sigval" style="color:#00D4AA">{steer}°</div>'
                    f'<div class="siglbl">degrees</div></div>', unsafe_allow_html=True)
    with c6:
        st.markdown(f'<div class="sigcard"><div class="siglbl">CAN Bus Load</div>'
                    f'<div class="sigval" style="color:{"#FF4B4B" if bus>80 else "#00D4AA"}">{bus}</div>'
                    f'<div class="siglbl">%</div></div>', unsafe_allow_html=True)
    with c7:
        st.markdown(f'<div class="sigcard"><div class="siglbl">Engine RPM</div>'
                    f'<div class="sigval" style="color:#00D4AA">{int(rpm)}</div>'
                    f'<div class="siglbl">rpm</div></div>', unsafe_allow_html=True)
    with c8:
        rl = "CRITICAL" if risk>0.85 else "HIGH" if risk>0.65 else "MEDIUM" if risk>0.4 else "LOW"
        st.markdown(f'<div class="sigcard"><div class="siglbl">Risk Score</div>'
                    f'<div class="sigval" style="color:{rc_color}">{risk:.3f}</div>'
                    f'<div class="siglbl">{rl}</div></div>', unsafe_allow_html=True)

    st.divider()

    # ── ADAS flags ────────────────────────────────────────────────────────────
    st.markdown('<p class="sec">🚦 ADAS Status</p>', unsafe_allow_html=True)
    fa1,fa2,fa3,fa4,fa5 = st.columns(5)
    def _flag(col, label, active, color_on="#FF4B4B", color_off="#1E2633"):
        col.markdown(f"""
<div style="background:{"#1A0000" if active else "#161B22"};border:1px solid {color_on if active else "#21262D"};
border-radius:8px;padding:10px;text-align:center;">
<div style="color:{color_on if active else "#555"};font-size:11px;font-family:'Share Tech Mono',monospace;
letter-spacing:1px">{"●" if active else "○"} {label}</div></div>""", unsafe_allow_html=True)

    _flag(fa1, "OBSTACLE",   last.get("obstacle_detected",False))
    _flag(fa2, "PEDESTRIAN", last.get("pedestrian_detected",False))
    _flag(fa3, "AEB ACTIVE", last.get("aeb_active",False))
    _flag(fa4, "LANE WARN",  last.get("lane_departure_warning",False), "#FFA500")
    _flag(fa5, "ATTACK",     last.get("attack",{}).get("active",False), "#FF8C00")

    st.divider()

    # ── Rolling speed + brake chart ───────────────────────────────────────────
    if len(lf) > 2:
        import plotly.graph_objects as go
        st.markdown('<p class="sec">📊 Rolling Signal History</p>', unsafe_allow_html=True)
        xs     = list(range(len(lf)))
        speeds = [f.get("vehicle_speed",0) for f in lf]
        brakes = [f.get("brake_pedal_position",0) for f in lf]
        delays = [f.get("delay_ms",0) for f in lf]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=speeds, name="Speed (km/h)", line=dict(color="#00D4AA",width=2)))
        fig.add_trace(go.Scatter(x=xs, y=brakes, name="Brake (%)",    line=dict(color="#FF4B4B",width=2)))
        fig.add_trace(go.Scatter(x=xs, y=delays, name="Delay (ms)",   line=dict(color="#FFA500",width=1,dash="dot")))
        fig.add_hline(y=100, line_color="#FF4B4B", line_dash="dash",
                      annotation_text="ISO limit 100ms", annotation_font_color="#FF4B4B",
                      annotation_position="top left")
        fig.update_layout(
            height=260, margin=dict(l=20,r=20,t=20,b=20),
            paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
            legend=dict(font=dict(color="#CCC"),bgcolor="rgba(0,0,0,0)"),
            xaxis=dict(color="#555",showgrid=False),
            yaxis=dict(color="#555",gridcolor="#1E2633"),
        )
        st.plotly_chart(fig, use_container_width=True)


# ────────────────────────────────────────────────────────────────────────────
# TAB 2 — Event Chain
# ────────────────────────────────────────────────────────────────────────────
with tab2:
    import plotly.graph_objects as go
    st.markdown('<p class="sec">⛓️ Current Event Chain Timing</p>', unsafe_allow_html=True)

    chain = last.get("event_chain", [])
    limit = last.get("brake_asil_limit_ms", 100)

    if chain:
        steps  = [e["step"].upper() for e in chain]
        times  = [e["time_ms"] for e in chain]
        total  = times[-1] if times else 0
        budget = limit / max(len(chain),1)
        deltas = [times[0]] + [times[i]-times[i-1] for i in range(1,len(times))]
        colors = ["#FF4B4B" if d > budget else "#00D4AA" for d in deltas]

        fig = go.Figure(go.Bar(
            x=deltas, y=steps, orientation="h",
            marker=dict(color=colors, line=dict(color="#333",width=1)),
            text=[f"{d}ms" for d in deltas], textposition="auto",
            textfont=dict(color="#FFF")
        ))
        fig.add_vline(x=budget, line_color="#FFA500", line_dash="dash",
                      annotation_text=f"Budget/step ({int(budget)}ms)",
                      annotation_font_color="#FFA500")
        fig.update_layout(
            height=260, margin=dict(l=20,r=20,t=30,b=20),
            paper_bgcolor="#161B22", plot_bgcolor="#0E1117",
            xaxis=dict(title="Time (ms)",color="#CCC",gridcolor="#1E2633"),
            yaxis=dict(color="#CCC"),
            title=dict(text=f"Total: {total}ms  |  ISO limit: {limit}ms  |  "
                            f"{'⚠️ VIOLATION' if total>limit else '✅ OK'}",
                       font=dict(color="#FF4B4B" if total>limit else "#00D4AA", size=13))
        )
        st.plotly_chart(fig, use_container_width=True)

        # Step cards
        st.markdown('<p class="sec">Step Breakdown</p>', unsafe_allow_html=True)
        scols = st.columns(len(chain))
        for col, step, t, d in zip(scols, steps, times, deltas):
            ok = d <= budget
            col.markdown(f"""
<div style="background:{"#001A10" if ok else "#1A0000"};border:1px solid {"#00D4AA" if ok else "#FF4B4B"};
border-radius:8px;padding:10px;text-align:center;">
<div style="color:#888;font-size:10px;letter-spacing:1px">{step}</div>
<div style="font-family:'Share Tech Mono',monospace;font-size:20px;
color:{"#00D4AA" if ok else "#FF4B4B"}">{t}ms</div>
<div style="color:#555;font-size:10px">+{d}ms</div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("No event chain in current frame.")

    st.divider()

    # ── ISO Violation detail ──────────────────────────────────────────────────
    st.markdown('<p class="sec">ISO 26262 Status</p>', unsafe_allow_html=True)
    if last.get("iso_violation_detected"):
        st.markdown(f"""
<div class="vfail">
  🔴 VIOLATION — {last.get("iso_violation_type","?")}
  <br><small style="color:#888">Rule: {last.get("iso_rule_id","?")} &nbsp;|&nbsp;
  ASIL: {last.get("asil_level","?")} &nbsp;|&nbsp;
  State: {last.get("safety_state","?").upper()}</small>
</div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div class="vpass">✅ ISO 26262 — NOMINAL &nbsp;|&nbsp; ASIL-D compliant</div>',
                    unsafe_allow_html=True)

    # Attack status
    atk = last.get("attack", {})
    if atk.get("active"):
        st.markdown(f'<div class="atk">⚡ ATTACK: {atk.get("type","?").upper()} &nbsp;|&nbsp; {atk.get("description","")}</div>',
                    unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────────────────────
# TAB 3 — Violations & Attacks
# ────────────────────────────────────────────────────────────────────────────
with tab3:
    import plotly.graph_objects as go
    col_v, col_a = st.columns(2)

    with col_v:
        st.markdown('<p class="sec">🚨 ISO Violations Feed</p>', unsafe_allow_html=True)
        if viols:
            for v in reversed(viols[-15:]):
                ts = v.get("timestamp_ms", 0)
                st.markdown(f"""
<div class="vfail">
  [{ts}ms] {v.get("iso_violation_type","?")}
  <br><small style="color:#888">{v.get("iso_rule_id","?")} · delay={v.get("delay_ms","?")}ms · risk={v.get("risk_score",0):.3f}</small>
</div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="vpass">✅ No violations detected</div>', unsafe_allow_html=True)

    with col_a:
        st.markdown('<p class="sec">⚡ Attack Feed</p>', unsafe_allow_html=True)
        if atks:
            for a in reversed(atks[-15:]):
                st.markdown(f"""
<div class="atk">
  [{a.get("timestamp_ms",0)}ms] {a.get("type","?").upper()}
  <br><small style="color:#888">{a.get("description","?")} · speed={a.get("speed",0)}km/h · delay={a.get("delay_ms",0)}ms</small>
</div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="vpass">✅ No attacks detected</div>', unsafe_allow_html=True)

    st.divider()

    # ── Attack type breakdown ─────────────────────────────────────────────────
    if atks:
        st.markdown('<p class="sec">Attack Type Breakdown</p>', unsafe_allow_html=True)
        from collections import Counter
        counts = Counter(a.get("type","?") for a in atks)
        fig = go.Figure(go.Bar(
            x=list(counts.keys()), y=list(counts.values()),
            marker_color=["#FF8C00","#FF4B4B","#FFA500","#FF6B6B"][:len(counts)],
            text=list(counts.values()), textposition="auto"
        ))
        fig.update_layout(
            height=220, margin=dict(l=20,r=20,t=20,b=20),
            paper_bgcolor="#161B22", plot_bgcolor="#0E1117",
            xaxis=dict(color="#CCC"), yaxis=dict(color="#CCC",title="Count")
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── GenAI Threat outputs ──────────────────────────────────────────────────
    if st.session_state.threats:
        st.divider()
        st.markdown('<p class="sec">🧠 GenAI Threat Analysis</p>', unsafe_allow_html=True)
        for t in reversed(st.session_state.threats[-5:]):
            sev   = t.get("severity","?")
            col   = {"CRITICAL":"#FF4B4B","HIGH":"#FF8C00","MEDIUM":"#FFA500"}.get(sev,"#00D4AA")
            chain = " → ".join(t.get("attack_chain",[])[:4])
            st.markdown(f"""
<div style="border-left:3px solid {col};background:#161B22;border-radius:0 8px 8px 0;
padding:10px 14px;margin-bottom:8px;">
  <div style="color:{col};font-weight:700;font-size:13px">{sev} — {t.get("attack_type",t.get("attack_chain",["?"])[0] if t.get("attack_chain") else "?")}</div>
  <div style="color:#AAA;font-size:11px;margin-top:4px">Chain: {chain}</div>
  <div style="color:#00D4AA;font-size:11px;margin-top:4px">🛡 {t.get("mitigation","N/A")}</div>
</div>""", unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────────────────────
# TAB 4 — Risk Timeline
# ────────────────────────────────────────────────────────────────────────────
with tab4:
    import plotly.graph_objects as go
    st.markdown('<p class="sec">📈 Risk Score Timeline</p>', unsafe_allow_html=True)

    if len(rh) > 1:
        xs = [r["t"] for r in rh]
        ys = [r["r"] for r in rh]
        pt_colors = [
            "#FF4B4B" if v>0.85 else "#FF8C00" if v>0.65 else "#FFA500" if v>0.4 else "#00D4AA"
            for v in ys
        ]

        fig = go.Figure()
        # Fill area under curve
        fig.add_trace(go.Scatter(
            x=xs, y=ys, fill="tozeroy", fillcolor="rgba(0,212,170,0.08)",
            line=dict(color="#00D4AA",width=2),
            mode="lines+markers",
            marker=dict(color=pt_colors, size=6, line=dict(color="#333",width=1)),
            hovertemplate="t=%{x}ms<br>risk=%{y:.3f}<extra></extra>"
        ))
        fig.add_hline(y=0.85, line_color="#FF4B4B", line_dash="dot",
                      annotation_text="CRITICAL (0.85)", annotation_font_color="#FF4B4B",
                      annotation_position="top left")
        fig.add_hline(y=0.65, line_color="#FF8C00", line_dash="dot",
                      annotation_text="HIGH (0.65)", annotation_font_color="#FF8C00",
                      annotation_position="top left")
        fig.add_hline(y=0.40, line_color="#FFA500", line_dash="dot",
                      annotation_text="MEDIUM (0.40)", annotation_font_color="#FFA500",
                      annotation_position="top left")
        fig.update_layout(
            height=360, margin=dict(l=20,r=20,t=20,b=20),
            paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
            xaxis=dict(title="Timestamp (ms)", color="#555", gridcolor="#1E2633"),
            yaxis=dict(title="Risk Score", range=[0,1.05], color="#555", gridcolor="#1E2633"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Stats
        r1,r2,r3,r4 = st.columns(4)
        r1.metric("Current Risk",  f"{ys[-1]:.3f}")
        r2.metric("Max Risk",      f"{max(ys):.3f}")
        r3.metric("Avg Risk",      f"{sum(ys)/len(ys):.3f}")
        r4.metric("Critical Events", sum(1 for v in ys if v>0.85))
    else:
        st.info("Collecting risk history... (auto-refreshes)")

    # ── Severity distribution pie ─────────────────────────────────────────────
    if lf:
        st.divider()
        st.markdown('<p class="sec">Severity Distribution</p>', unsafe_allow_html=True)
        from collections import Counter
        sevs = Counter(f.get("severity","LOW") for f in lf)
        color_map = {"CRITICAL":"#FF4B4B","HIGH":"#FF8C00","MEDIUM":"#FFA500","LOW":"#00D4AA"}
        fig2 = go.Figure(go.Pie(
            labels=list(sevs.keys()),
            values=list(sevs.values()),
            hole=0.5,
            marker=dict(colors=[color_map.get(s,"#CCC") for s in sevs.keys()],
                        line=dict(color="#0E1117",width=2)),
            textfont=dict(color="#E8E8E8",size=12)
        ))
        fig2.update_layout(
            height=280, margin=dict(l=20,r=20,t=20,b=20),
            paper_bgcolor="#0E1117", showlegend=True,
            legend=dict(font=dict(color="#CCC"),bgcolor="rgba(0,0,0,0)")
        )
        st.plotly_chart(fig2, use_container_width=True)


# ────────────────────────────────────────────────────────────────────────────
# TAB 5 — Raw Frames
# ────────────────────────────────────────────────────────────────────────────
with tab5:
    st.markdown('<p class="sec">🔍 Raw Frame Stream</p>', unsafe_allow_html=True)
    if last:
        st.json(last)
    if lf:
        with st.expander(f"Last {len(lf)} frames (newest first)"):
            for f in reversed(lf[-20:]):
                st.json(f)


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.auto_refresh:
    time.sleep(st.session_state.refresh_rate)
    st.rerun()