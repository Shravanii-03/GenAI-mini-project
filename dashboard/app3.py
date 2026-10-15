"""
dashboard/app.py — ULTIMATE LIVE SDV Safety & Threat Detection Dashboard
===========================================================================
Real-time streaming dashboard combining best features from all versions.

Features:
  ✅ Auto-refreshing live data (1s interval)
  ✅ Reads from realtime_monitor.py outputs/
  ✅ ASIL-D compliance tracking (ISO 26262)
  ✅ Event chain timing visualization
  ✅ RL learning curves with Q-states
  ✅ PlantUML + Mermaid diagrams
  ✅ Attack injection monitoring
  ✅ Risk timeline with severity zones
  ✅ Novelty tracking vs TUM paper

6 Tabs:
  1. 📡 Live Signals    — 8 metrics + ADAS flags + rolling chart
  2. ⛓️ Event Chain     — timing bars + step breakdown + ISO status
  3. 📈 Risk & RL      — risk timeline + Q-learning + epsilon decay
  4. 🚨 Threats        — violations + attacks + GenAI threat analysis
  5. 🔷 Diagrams       — live Mermaid + saved PNGs + PlantUML
  6. 🏆 Novelties      — 7 modules with live metrics vs paper

Run:
    streamlit run dashboard/app.py
"""

import sys, os, json, time, glob, random, base64
from pathlib import Path
from collections import Counter

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import plotly.graph_objects as go

st.set_page_config(
    page_title="SDV Safety Monitor — ASIL-D",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM CSS — Industrial Automotive Theme
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Barlow', sans-serif;
    background-color: #0E1117;
    color: #E8E8E8;
}

.hdr {
    background: linear-gradient(135deg, #0D1F0D 0%, #0E1117 50%, #0D0D1F 100%);
    border-bottom: 3px solid #00D4AA;
    padding: 16px 24px;
    margin-bottom: 20px;
    border-radius: 0 0 12px 12px;
}

.hdr-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 26px;
    color: #00D4AA;
    letter-spacing: 2px;
    margin: 0;
}

.hdr-sub {
    color: #666;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-top: 4px;
}

.sec {
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    color: #00D4AA;
    letter-spacing: 2px;
    text-transform: uppercase;
    border-bottom: 1px solid #1E2633;
    padding-bottom: 6px;
    margin-bottom: 14px;
}

.sigcard {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 8px;
    padding: 12px 14px;
    text-align: center;
    margin-bottom: 8px;
}

.sigval {
    font-family: 'Share Tech Mono', monospace;
    font-size: 28px;
    font-weight: 700;
    margin: 4px 0;
}

.siglbl {
    color: #666;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
}

.vpass {
    background: linear-gradient(90deg, #001A10, transparent);
    border-left: 3px solid #00D4AA;
    padding: 8px 12px;
    border-radius: 0 6px 6px 0;
    color: #00D4AA;
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    margin-bottom: 6px;
}

.vfail {
    background: linear-gradient(90deg, #1A0000, transparent);
    border-left: 3px solid #FF4B4B;
    padding: 8px 12px;
    border-radius: 0 6px 6px 0;
    color: #FF4B4B;
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    margin-bottom: 6px;
}

.atk {
    background: linear-gradient(90deg, #1A0A00, transparent);
    border-left: 3px solid #FF8C00;
    padding: 8px 12px;
    border-radius: 0 6px 6px 0;
    color: #FF8C00;
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    margin-bottom: 6px;
}

.asil-badge {
    display: inline-block;
    background: #0D1F0D;
    border: 1px solid #00D4AA;
    border-radius: 4px;
    padding: 4px 8px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: #00D4AA;
    letter-spacing: 1px;
}

.novelty {
    background: #0D1F2D;
    border: 1px solid #00D4AA;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 10px;
}

.novelty-title {
    color: #00D4AA;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    font-weight: 700;
}

.novelty-desc {
    color: #AAA;
    font-size: 12px;
    margin-top: 4px;
    line-height: 1.6;
}

.novelty-metric {
    color: #00D4AA;
    font-size: 11px;
    font-family: 'Share Tech Mono', monospace;
    margin-top: 6px;
}

div[data-testid="metric-container"] {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 8px;
    padding: 12px 14px;
}

.stButton > button {
    background: linear-gradient(135deg, #00D4AA, #009977);
    color: #000;
    font-family: 'Share Tech Mono', monospace;
    font-weight: 700;
    border: none;
    border-radius: 6px;
    padding: 10px 22px;
    width: 100%;
    transition: all 0.2s;
}

.stButton > button:hover {
    background: linear-gradient(135deg, #00FFCC, #00D4AA);
    transform: translateY(-1px);
}

.stTextInput input {
    background: #161B22 !important;
    color: #E8E8E8 !important;
    border: 1px solid #30363D !important;
    border-radius: 6px !important;
}

.stSelectbox select {
    background: #161B22 !important;
    color: #E8E8E8 !important;
    border: 1px solid #30363D !important;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# STATE INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════
def _init_state():
    defaults = {
        "live_frames":    [],          # Rolling window of frames
        "violations":     [],          # ISO violation events
        "attacks":        [],          # Detected attacks
        "threats":        [],          # GenAI threat analysis
        "risk_history":   [],          # Risk timeline
        "rl_history":     [],          # RL learning curve
        "last_frame":     None,
        "auto_refresh":   True,
        "refresh_rate":   1.0,         # seconds
        "outputs_dir":    os.path.join(ROOT, "outputs"),
        "req_input":      "Brake within 100ms if obstacle detected",
        "tick_count":     0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()
WINDOW = 150  # Keep last 150 frames


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════
def load_latest_from_outputs(outputs_dir):
    """Load latest frame from realtime_monitor.py output"""
    path = os.path.join(outputs_dir, "live_latest.json")
    if not os.path.exists(path):
        return None, None, None
    
    try:
        with open(path) as f:
            data = json.load(f)
        
        frame  = data.get("frame", {})
        eval_  = data.get("evaluation", {})
        threat = data.get("threat")
        
        # Merge evaluation into frame
        frame["risk_score"] = eval_.get("risk_score", 0)
        frame["severity"]   = eval_.get("severity", "LOW")
        frame["violation"]  = eval_.get("violation", False)
        frame["_loaded_at"] = data.get("timestamp", "")
        
        return frame, eval_, threat
    except Exception as e:
        return None, None, None


def generate_demo_frame(tick):
    """Generate realistic demo data when no live data available"""
    phases = ["startup", "normal_driving", "cruise_control", "obstacle_ahead",
              "emergency_brake", "pedestrian_detected", "lane_departure", "recovery"]
    phase = phases[(tick // 15) % len(phases)]
    
    speed_map = {
        "startup": 0, "normal_driving": 55, "cruise_control": 80,
        "obstacle_ahead": 40, "emergency_brake": 15,
        "pedestrian_detected": 30, "lane_departure": 75, "recovery": 25
    }
    speed = speed_map.get(phase, 60) + random.gauss(0, 2)
    
    brake_map = {
        "emergency_brake": 95, "obstacle_ahead": 55,
        "pedestrian_detected": 35, "recovery": 20
    }
    brake = max(0, brake_map.get(phase, 0) + random.gauss(0, 1))
    
    delay_map = {
        "emergency_brake": random.randint(88, 135),
        "obstacle_ahead": random.randint(58, 100),
        "pedestrian_detected": random.randint(60, 95)
    }
    delay = delay_map.get(phase, random.randint(38, 72))
    
    iso_violation = delay > 100 and phase == "emergency_brake"
    attack_active = random.random() < 0.15
    attack_type = random.choice(["can_spoofing", "delay_injection", "speed_spoofing"]) if attack_active else "none"
    
    risk = min(2.0, delay / 100 * (1.4 if iso_violation else 0.9))
    severity = "CRITICAL" if risk > 1.3 else "HIGH" if risk > 1.1 else "MEDIUM" if risk > 0.9 else "LOW"
    
    # RL state
    epsilon = max(0.05, 0.30 - tick * 0.0015)
    q_states = min(60, tick // 4 + 1)
    reward = -2.5 if iso_violation else 1.0 + random.uniform(0, 0.5)
    
    event_chain = [
        {"step": "sense",   "time_ms": max(1, int(delay * 0.15))},
        {"step": "detect",  "time_ms": max(2, int(delay * 0.38))},
        {"step": "decide",  "time_ms": max(3, int(delay * 0.70))},
        {"step": "actuate", "time_ms": delay},
    ]
    
    return {
        "timestamp_ms": tick * 50,
        "frame_id": tick,
        "driving_phase": phase,
        "vehicle_speed": round(speed, 1),
        "brake_pedal_position": round(brake, 1),
        "delay_ms": delay,
        "brake_asil_limit_ms": 100,
        "violation": iso_violation,
        "iso_rule_id": "ISO26262-6-8.4.5",
        "risk_score": round(risk, 3),
        "severity": severity,
        "ttc_seconds": round(random.uniform(0.5, 5.0), 2) if phase in ["obstacle_ahead", "pedestrian_detected"] else 999,
        "steering_angle": round(random.gauss(0, 5), 1),
        "engine_rpm": int(1200 + speed * 25),
        "can_bus_load_pct": random.randint(30, 85),
        "obstacle_detected": phase in ["obstacle_ahead", "emergency_brake", "pedestrian_detected"],
        "pedestrian_detected": phase == "pedestrian_detected",
        "aeb_active": phase in ["emergency_brake", "pedestrian_detected"],
        "lane_departure_warning": phase == "lane_departure",
        "safety_state": "critical" if iso_violation else "degraded" if risk > 0.9 else "nominal",
        "attack": {
            "active": attack_active,
            "type": attack_type,
            "description": f"Attack: {attack_type}" if attack_active else ""
        },
        "event_chain": event_chain,
        "rl_epsilon": epsilon,
        "rl_q_states": q_states,
        "rl_reward": reward,
        "rl_action_ms": random.choice([-20, -10, 0, +10]),
        "rl_steps": tick,
    }


# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="hdr">
    <div class="hdr-title">🚗 SDV SAFETY & THREAT MONITOR</div>
    <div class="hdr-sub">GenAI-Based Real-Time Temporal Safety · ISO 26262 · ASIL-D</div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR CONTROLS
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<p class="sec">⚙️ Controls</p>', unsafe_allow_html=True)
    
    st.session_state.auto_refresh = st.checkbox("🔄 Auto-Refresh", value=st.session_state.auto_refresh)
    st.session_state.refresh_rate = st.slider("Refresh Rate (s)", 0.5, 5.0, st.session_state.refresh_rate, 0.5)
    
    st.divider()
    st.markdown('<p class="sec">📝 Requirement</p>', unsafe_allow_html=True)
    req = st.text_area("Safety Requirement", st.session_state.req_input, height=80)
    st.session_state.req_input = req
    
    if st.button("▶ Show Run Command"):
        st.code(f'python realtime_monitor.py', language="bash")
        st.caption(f'Requirement: "{req}"')
    
    st.divider()
    st.markdown('<p class="sec">📂 Data Source</p>', unsafe_allow_html=True)
    outputs_dir = st.text_input("outputs/ path", value=st.session_state.outputs_dir)
    st.session_state.outputs_dir = outputs_dir
    
    live_path = os.path.join(outputs_dir, "live_latest.json")
    is_live = os.path.exists(live_path)
    
    if is_live:
        st.markdown('<span style="color:#00D4AA;font-size:12px;font-family:\'Share Tech Mono\',monospace">🟢 LIVE DATA</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="color:#FF8C00;font-size:12px;font-family:\'Share Tech Mono\',monospace">🟡 DEMO MODE</span>', unsafe_allow_html=True)
    
    st.divider()
    if st.button("🗑️ Clear History"):
        for k in ["live_frames", "violations", "attacks", "threats", "risk_history", "rl_history"]:
            st.session_state[k] = []
        st.session_state.tick_count = 0
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# FETCH DATA
# ══════════════════════════════════════════════════════════════════════════════
tick = st.session_state.tick_count
frame, eval_, threat = load_latest_from_outputs(st.session_state.outputs_dir)

if frame:
    # Live data
    st.session_state.live_frames = (st.session_state.live_frames + [frame])[-WINDOW:]
    if frame.get("violation"):
        st.session_state.violations = (st.session_state.violations + [frame])[-60:]
    if frame.get("attack", {}).get("active"):
        st.session_state.attacks = (st.session_state.attacks + [frame])[-60:]
    if threat:
        st.session_state.threats = (st.session_state.threats + [threat])[-20:]
    st.session_state.risk_history = (st.session_state.risk_history + [{
        "t": frame.get("timestamp_ms", 0),
        "r": frame.get("risk_score", 0)
    }])[-200:]
    if "rl_epsilon" in frame:
        st.session_state.rl_history.append({
            "step": frame.get("rl_steps", tick),
            "epsilon": frame.get("rl_epsilon", 0.3),
            "q_states": frame.get("rl_q_states", 0),
            "reward": frame.get("rl_reward", 0),
            "action": frame.get("rl_action_ms", 0)
        })
    data_source = "🟢 LIVE"
else:
    # Demo mode
    demo = generate_demo_frame(tick)
    st.session_state.live_frames = (st.session_state.live_frames + [demo])[-WINDOW:]
    if demo["violation"]:
        st.session_state.violations = (st.session_state.violations + [demo])[-60:]
    if demo["attack"]["active"]:
        st.session_state.attacks = (st.session_state.attacks + [demo])[-60:]
    st.session_state.risk_history = (st.session_state.risk_history + [{
        "t": demo["timestamp_ms"],
        "r": demo["risk_score"]
    }])[-200:]
    st.session_state.rl_history.append({
        "step": tick,
        "epsilon": demo["rl_epsilon"],
        "q_states": demo["rl_q_states"],
        "reward": demo["rl_reward"],
        "action": demo["rl_action_ms"]
    })
    frame = demo
    data_source = "🟡 DEMO"

st.session_state.tick_count += 1

# Shortcuts
last = frame
lf = st.session_state.live_frames
rh = st.session_state.risk_history
rlh = st.session_state.rl_history[-120:]
viols = st.session_state.violations
atks = st.session_state.attacks
threats = st.session_state.threats


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📡 Live Signals",
    "⛓️ Event Chain",
    "📈 Risk & RL",
    "🚨 Threats",
    "🔷 Diagrams",
    "🏆 Novelties"
])


# ──────────────────────────────────────────────────────────────────────────────
# TAB 1: LIVE SIGNALS
# ──────────────────────────────────────────────────────────────────────────────
with tab1:
    phase = last.get("driving_phase", "—")
    safety = last.get("safety_state", "nominal")
    safety_color = {"critical": "#FF4B4B", "degraded": "#FF8C00", "nominal": "#00D4AA"}.get(safety, "#00D4AA")
    attack_now = last.get("attack", {}).get("active", False)
    
    st.markdown(f"""
<div style="display:flex;justify-content:space-between;background:#161B22;border:1px solid #21262D;
border-radius:8px;padding:12px 18px;margin-bottom:16px;">
    <span style="font-family:'Share Tech Mono',monospace;font-size:13px;color:#888">
        {data_source} &nbsp;|&nbsp; Frame #{last.get('frame_id', '—')} &nbsp;|&nbsp; 
        <span style="color:#00D4AA">{phase.upper().replace('_', ' ')}</span>
    </span>
    <span style="font-family:'Share Tech Mono',monospace;font-size:13px;color:{safety_color}">
        ● {safety.upper()}{'&nbsp;&nbsp;⚡ ATTACK' if attack_now else ''}
    </span>
</div>
""", unsafe_allow_html=True)
    
    # Top row metrics
    speed = last.get("vehicle_speed", 0)
    brake = last.get("brake_pedal_position", 0)
    ttc = last.get("ttc_seconds", 999)
    delay = last.get("delay_ms", 0)
    limit = last.get("brake_asil_limit_ms", 100)
    
    c1, c2, c3, c4 = st.columns(4)
    
    metrics = [
        (c1, "Vehicle Speed", speed, "km/h", speed > 100),
        (c2, "Brake Pedal", brake, "%", brake > 80),
        (c3, "TTC", f"{ttc:.1f}" if ttc < 100 else "—", "sec", ttc < 1.5),
        (c4, "Event Delay", delay, f"ms/{limit}ms", delay > limit)
    ]
    
    for col, label, value, unit, warn in metrics:
        color = "#FF4B4B" if warn else "#00D4AA"
        col.markdown(f"""
<div class="sigcard">
    <div class="siglbl">{label}</div>
    <div class="sigval" style="color:{color}">{value}</div>
    <div class="siglbl">{unit}</div>
</div>
""", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Bottom row metrics
    risk = last.get("risk_score", 0)
    rpm = last.get("engine_rpm", 0)
    steer = last.get("steering_angle", 0)
    bus_load = last.get("can_bus_load_pct", 0)
    
    risk_color = "#FF4B4B" if risk > 1.3 else "#FF8C00" if risk > 1.1 else "#FFA500" if risk > 0.9 else "#00D4AA"
    risk_label = "CRITICAL" if risk > 1.3 else "HIGH" if risk > 1.1 else "MEDIUM" if risk > 0.9 else "LOW"
    
    c5, c6, c7, c8 = st.columns(4)
    
    metrics2 = [
        (c5, "Steering", f"{steer}°", "deg", abs(steer) > 20),
        (c6, "CAN Bus Load", bus_load, "%", bus_load > 80),
        (c7, "Engine RPM", int(rpm), "rpm", False),
        (c8, "Risk Score", f"{risk:.3f}", risk_label, risk > 1.1)
    ]
    
    for col, label, value, unit, warn in metrics2:
        if label == "Risk Score":
            color = risk_color
        else:
            color = "#FF4B4B" if warn else "#00D4AA"
        col.markdown(f"""
<div class="sigcard">
    <div class="siglbl">{label}</div>
    <div class="sigval" style="color:{color}">{value}</div>
    <div class="siglbl">{unit}</div>
</div>
""", unsafe_allow_html=True)
    
    st.divider()
    
    # ADAS Flags
    st.markdown('<p class="sec">🚦 ADAS Status <span class="asil-badge">ASIL-D</span></p>', unsafe_allow_html=True)
    fa1, fa2, fa3, fa4, fa5 = st.columns(5)
    
    def _flag(col, label, active, color="#FF4B4B"):
        bg = "#1A0000" if active else "#161B22"
        border = color if active else "#21262D"
        text_color = color if active else "#555"
        symbol = "●" if active else "○"
        col.markdown(f"""
<div style="background:{bg};border:1px solid {border};border-radius:8px;padding:10px;text-align:center;">
    <div style="color:{text_color};font-size:11px;font-family:'Share Tech Mono',monospace">
        {symbol} {label}
    </div>
</div>
""", unsafe_allow_html=True)
    
    _flag(fa1, "OBSTACLE", last.get("obstacle_detected", False))
    _flag(fa2, "PEDESTRIAN", last.get("pedestrian_detected", False))
    _flag(fa3, "AEB ACTIVE", last.get("aeb_active", False))
    _flag(fa4, "LANE WARN", last.get("lane_departure_warning", False), "#FFA500")
    _flag(fa5, "ATTACK", attack_now, "#FF8C00")
    
    # Rolling history chart
    if len(lf) > 2:
        st.divider()
        st.markdown('<p class="sec">📊 Rolling History (Last 150 Frames)</p>', unsafe_allow_html=True)
        
        xs = [f.get("frame_id", i) for i, f in enumerate(lf)]
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs,
            y=[f.get("vehicle_speed", 0) for f in lf],
            name="Speed (km/h)",
            line=dict(color="#00D4AA", width=2)
        ))
        fig.add_trace(go.Scatter(
            x=xs,
            y=[f.get("brake_pedal_position", 0) for f in lf],
            name="Brake (%)",
            line=dict(color="#FF4B4B", width=2)
        ))
        fig.add_trace(go.Scatter(
            x=xs,
            y=[f.get("delay_ms", 0) for f in lf],
            name="Delay (ms)",
            line=dict(color="#FFA500", width=1, dash="dot")
        ))
        fig.add_hline(
            y=100,
            line_color="#FF4B4B",
            line_dash="dash",
            annotation_text="ISO 100ms",
            annotation_font_color="#FF4B4B",
            annotation_position="top left"
        )
        fig.update_layout(
            height=280,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            legend=dict(font=dict(color="#CCC"), bgcolor="rgba(0,0,0,0)"),
            xaxis=dict(title="Frame ID", color="#555", showgrid=False),
            yaxis=dict(color="#555", gridcolor="#1E2633")
        )
        st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 2: EVENT CHAIN
# ──────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown('<p class="sec">⛓️ Event Chain Timing <span class="asil-badge">ISO 26262-6-8.4</span></p>', unsafe_allow_html=True)
    
    chain = last.get("event_chain", [])
    limit = last.get("brake_asil_limit_ms", 100)
    
    if chain:
        steps = [e["step"].upper() for e in chain]
        times = [e["time_ms"] for e in chain]
        total = times[-1] if times else 0
        budget = limit / max(len(chain), 1)
        
        # Calculate deltas
        deltas = [times[0]] + [times[i] - times[i-1] for i in range(1, len(times))]
        colors = ["#FF4B4B" if d > budget else "#00D4AA" for d in deltas]
        
        fig = go.Figure(go.Bar(
            x=deltas,
            y=steps,
            orientation="h",
            marker=dict(color=colors, line=dict(color="#333", width=1)),
            text=[f"{d}ms" for d in deltas],
            textposition="auto",
            textfont=dict(color="#FFF", size=12)
        ))
        fig.add_vline(
            x=budget,
            line_color="#FFA500",
            line_dash="dash",
            annotation_text=f"Budget ({int(budget)}ms)",
            annotation_font_color="#FFA500"
        )
        
        title_text = f"Total: {total}ms | Limit: {limit}ms | {' VIOLATION' if total > limit else ' OK'}"
        title_color = "#FF4B4B" if total > limit else "#00D4AA"
        
        fig.update_layout(
            height=260,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor="#161B22",
            plot_bgcolor="#0E1117",
            xaxis=dict(title="Time (ms)", color="#CCC", gridcolor="#1E2633"),
            yaxis=dict(color="#CCC"),
            title=dict(text=title_text, font=dict(color=title_color, size=14))
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Step breakdown cards
        st.markdown('<p class="sec"> Step Breakdown</p>', unsafe_allow_html=True)
        cols = st.columns(len(chain))
        for i, (col, step_data) in enumerate(zip(cols, chain)):
            step_name = step_data["step"].upper()
            step_time = step_data["time_ms"]
            delta = deltas[i]
            is_over = delta > budget
            
            col.markdown(f"""
<div style="background:#161B22;border:1px solid {'#FF4B4B' if is_over else '#21262D'};border-radius:8px;padding:10px;text-align:center;">
    <div style="color:#AAA;font-size:10px">{step_name}</div>
    <div style="color:{'#FF4B4B' if is_over else '#00D4AA'};font-size:20px;font-weight:700;font-family:'Share Tech Mono',monospace">{delta}ms</div>
    <div style="color:#666;font-size:9px">Cumulative: {step_time}ms</div>
</div>
""", unsafe_allow_html=True)
    
    else:
        st.info("No event chain data available")
    
    # ISO compliance status
    st.divider()
    st.markdown('<p class="sec">✅ ISO 26262 Compliance Status</p>', unsafe_allow_html=True)
    
    iso_rule = last.get("iso_rule_id", "ISO26262-6-8.4.5")
    violation = last.get("violation", False)
    
    if violation:
        st.markdown(f'<div class="vfail"> VIOLATION: {iso_rule} — Delay {delay}ms exceeds {limit}ms limit</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="vpass"> COMPLIANT: {iso_rule} — Delay {delay}ms within {limit}ms limit</div>', unsafe_allow_html=True)
    
    # Attack status
    if attack_now:
        attack_type = last.get("attack", {}).get("type", "unknown").upper()
        attack_desc = last.get("attack", {}).get("description", "")
        st.markdown(f'<div class="atk"> ATTACK DETECTED: {attack_type}<br><small>{attack_desc}</small></div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3: RISK & RL
# ──────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown('<p class="sec">📈 Risk Score Timeline</p>', unsafe_allow_html=True)
    
    if len(rh) > 1:
        xs = [r["t"] for r in rh]
        ys = [r["r"] for r in rh]
        
        point_colors = [
            "#FF4B4B" if v > 1.3 else "#FF8C00" if v > 1.1 else "#FFA500" if v > 0.9 else "#00D4AA"
            for v in ys
        ]
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs,
            y=ys,
            fill="tozeroy",
            fillcolor="rgba(0,212,170,0.08)",
            line=dict(color="#00D4AA", width=2),
            mode="lines+markers",
            marker=dict(color=point_colors, size=6, line=dict(color="#333", width=1)),
            hovertemplate="t=%{x}ms<br>risk=%{y:.3f}<extra></extra>"
        ))
        
        # Severity thresholds
        fig.add_hline(y=1.3, line_color="#FF4B4B", line_dash="dot",
                      annotation_text="CRITICAL (1.3)", annotation_font_color="#FF4B4B",
                      annotation_position="top left")
        fig.add_hline(y=1.1, line_color="#FF8C00", line_dash="dot",
                      annotation_text="HIGH (1.1)", annotation_font_color="#FF8C00",
                      annotation_position="top left")
        fig.add_hline(y=0.9, line_color="#FFA500", line_dash="dot",
                      annotation_text="MEDIUM (0.9)", annotation_font_color="#FFA500",
                      annotation_position="top left")
        
        fig.update_layout(
            height=320,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            xaxis=dict(title="Timestamp (ms)", color="#555", gridcolor="#1E2633"),
            yaxis=dict(title="Risk Score", range=[0, max(ys) * 1.1], color="#555", gridcolor="#1E2633"),
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Risk stats
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Current Risk", f"{ys[-1]:.3f}")
        r2.metric("Max Risk", f"{max(ys):.3f}")
        r3.metric("Avg Risk", f"{sum(ys)/len(ys):.3f}")
        r4.metric("Critical Events", sum(1 for v in ys if v > 1.3))
    else:
        st.info("Collecting risk history... (auto-refreshes)")
    
    # RL Learning Curve
    if len(rlh) > 1:
        st.divider()
        st.markdown('<p class="sec">🤖 RL Q-Learning Metrics</p>', unsafe_allow_html=True)
        
        fig2 = go.Figure()
        
        # Epsilon decay
        fig2.add_trace(go.Scatter(
            x=[r["step"] for r in rlh],
            y=[r["epsilon"] for r in rlh],
            name="Epsilon (ε)",
            line=dict(color="#00D4AA", width=2),
            yaxis="y"
        ))
        
        # Q-states growth
        fig2.add_trace(go.Scatter(
            x=[r["step"] for r in rlh],
            y=[r["q_states"] for r in rlh],
            name="Q-States",
            line=dict(color="#FFA500", width=2),
            yaxis="y2"
        ))
        
        fig2.update_layout(
            height=280,
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor="#161B22",
            plot_bgcolor="#0E1117",
            title=dict(text="RL Exploration vs Exploitation", font=dict(color="#CCC", size=13)),
            xaxis=dict(title="Training Steps", color="#555", gridcolor="#1E2633"),
            yaxis=dict(title="Epsilon", color="#00D4AA", gridcolor="#1E2633", range=[0, 0.35]),
            yaxis2=dict(title="Q-States", overlaying="y", side="right", color="#FFA500", showgrid=False),
            legend=dict(font=dict(color="#CCC"), bgcolor="rgba(0,0,0,0)")
        )
        st.plotly_chart(fig2, use_container_width=True)
        
        # RL stats
        rc1, rc2, rc3, rc4 = st.columns(4)
        current_rl = rlh[-1]
        rc1.metric("Epsilon", f"{current_rl['epsilon']:.3f}")
        rc2.metric("Q-States", current_rl['q_states'])
        rc3.metric("Last Reward", f"{current_rl['reward']:.2f}")
        rc4.metric("Last Action", f"{current_rl['action']:+d}ms")


# ──────────────────────────────────────────────────────────────────────────────
# TAB 4: THREATS
# ──────────────────────────────────────────────────────────────────────────────
with tab4:
    col_v, col_a = st.columns(2)
    
    with col_v:
        st.markdown('<p class="sec">🚨 ISO Violations Feed</p>', unsafe_allow_html=True)
        if viols:
            for v in reversed(viols[-15:]):
                ts = v.get("timestamp_ms", 0)
                iso_rule = v.get("iso_rule_id", "?")
                delay_val = v.get("delay_ms", "?")
                risk_val = v.get("risk_score", 0)
                st.markdown(f"""
<div class="vfail">
    [{ts}ms] ISO VIOLATION
    <br><small style="color:#888">{iso_rule} · delay={delay_val}ms · risk={risk_val:.3f}</small>
</div>
""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="vpass">✅ No violations detected</div>', unsafe_allow_html=True)
    
    with col_a:
        st.markdown('<p class="sec">⚡ Attack Feed</p>', unsafe_allow_html=True)
        if atks:
            for a in reversed(atks[-15:]):
                ts = a.get("timestamp_ms", 0)
                a_type = a.get("attack", {}).get("type", "?").upper()
                a_desc = a.get("attack", {}).get("description", "")
                speed_val = a.get("vehicle_speed", 0)
                delay_val = a.get("delay_ms", 0)
                st.markdown(f"""
<div class="atk">
    [{ts}ms] {a_type}
    <br><small style="color:#888">{a_desc} · speed={speed_val}km/h · delay={delay_val}ms</small>
</div>
""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="vpass">✅ No attacks detected</div>', unsafe_allow_html=True)
    
    # Attack type breakdown
    if atks:
        st.divider()
        st.markdown('<p class="sec">Attack Type Distribution</p>', unsafe_allow_html=True)
        
        counts = Counter(a.get("attack", {}).get("type", "?") for a in atks)
        
        fig = go.Figure(go.Bar(
            x=list(counts.keys()),
            y=list(counts.values()),
            marker_color=["#FF8C00", "#FF4B4B", "#FFA500", "#FF6B6B"][:len(counts)],
            text=list(counts.values()),
            textposition="auto"
        ))
        fig.update_layout(
            height=240,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="#161B22",
            plot_bgcolor="#0E1117",
            xaxis=dict(color="#CCC"),
            yaxis=dict(color="#CCC", title="Count")
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # GenAI Threat Analysis
    if threats:
        st.divider()
        st.markdown('<p class="sec">🧠 GenAI Threat Analysis</p>', unsafe_allow_html=True)
        
        for t in reversed(threats[-5:]):
            sev = t.get("severity", "?")
            sev_color = {"CRITICAL": "#FF4B4B", "HIGH": "#FF8C00", "MEDIUM": "#FFA500"}.get(sev, "#00D4AA")
            chain_steps = t.get("attack_chain", [])[:4]
            chain_text = " → ".join(chain_steps) if chain_steps else "N/A"
            mitigation = t.get("mitigation", "N/A")
            
            st.markdown(f"""
<div style="border-left:3px solid {sev_color};background:#161B22;border-radius:0 8px 8px 0;
padding:12px 16px;margin-bottom:10px;">
    <div style="color:{sev_color};font-weight:700;font-size:13px">{sev} THREAT</div>
    <div style="color:#AAA;font-size:11px;margin-top:6px">Chain: {chain_text}</div>
    <div style="color:#00D4AA;font-size:11px;margin-top:6px">🛡 Mitigation: {mitigation}</div>
</div>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 5: DIAGRAMS
# ──────────────────────────────────────────────────────────────────────────────
with tab5:
    st.markdown('<p class="sec">🔷 Activity Diagrams</p>', unsafe_allow_html=True)
    
    # Check for saved diagrams
    diagram_dir = os.path.join(st.session_state.outputs_dir, "diagrams")
    
    if os.path.exists(diagram_dir):
        png_files = sorted(glob.glob(os.path.join(diagram_dir, "*.png")), key=os.path.getmtime, reverse=True)
        
        if png_files:
            st.markdown(f"Found {len(png_files)} diagrams")
            
            # Show latest diagram
            latest = png_files[0]
            st.image(latest, caption=os.path.basename(latest), use_container_width=True)
            
            # Show more in expander
            if len(png_files) > 1:
                with st.expander(f"📁 View all {len(png_files)} diagrams"):
                    cols = st.columns(2)
                    for i, png in enumerate(png_files[1:6]):  # Max 5 more
                        col = cols[i % 2]
                        col.image(png, caption=os.path.basename(png), use_container_width=True)
        else:
            st.info("No diagrams generated yet. Run: `python generate_all_visuals.py`")
    else:
        st.info(f"Diagram directory not found: {diagram_dir}")
    
    # Live Mermaid diagram generator
    st.divider()
    st.markdown('<p class="sec">⚡ Live Mermaid Diagram</p>', unsafe_allow_html=True)
    
    if chain:
        mermaid_code = "graph TD\n"
        mermaid_code += "    START([Start])\n"
        
        for i, step in enumerate(chain):
            step_name = step["step"].upper()
            step_time = step["time_ms"]
            node_id = f"STEP{i}"
            
            if i == 0:
                mermaid_code += f"    START --> {node_id}[\"{step_name}<br/>{step_time}ms\"]\n"
            else:
                prev_id = f"STEP{i-1}"
                mermaid_code += f"    {prev_id} --> {node_id}[\"{step_name}<br/>{step_time}ms\"]\n"
        
        mermaid_code += f"    STEP{len(chain)-1} --> END([End])\n"
        
        # Style nodes
        if last.get("violation"):
            mermaid_code += "    style END fill:#ff4b4b,stroke:#ff4b4b,color:#fff\n"
        else:
            mermaid_code += "    style END fill:#00d4aa,stroke:#00d4aa,color:#000\n"
        
        st.code(mermaid_code, language="mermaid")
        
        with st.expander("📄 Copy Mermaid Code"):
            st.code(mermaid_code)
    
    # PlantUML command
    st.divider()
    st.markdown('<p class="sec">🔧 Generate PlantUML Diagrams</p>', unsafe_allow_html=True)
    
    if st.button("▶ Run Diagram Generator"):
        st.code("python generate_all_visuals.py", language="bash")
        st.caption("This will generate PlantUML diagrams + comparison charts")


# ──────────────────────────────────────────────────────────────────────────────
# TAB 6: NOVELTIES
# ──────────────────────────────────────────────────────────────────────────────
with tab6:
    st.markdown('<p class="sec">🏆 System Novelties vs TUM Paper (arXiv:2601.02215)</p>', unsafe_allow_html=True)
    
    novelties = [
        {
            "id": "MODULE 1",
            "title": "Multi-Language Parser",
            "desc": "Parses Python, C++, Rust code (paper: Python only)",
            "metric": f"Languages: 3 vs 1",
            "proof": "Implemented in multi_lang_parser.py"
        },
        {
            "id": "MODULE 3",
            "title": "GenAI Timing Extractor",
            "desc": "LLM extracts timing constraints from natural language requirements + ISO docs",
            "metric": f"Accuracy: RAG-enhanced",
            "proof": "timing_extractor.py with RAG retrieval"
        },
        {
            "id": "MODULE 4",
            "title": "Real-Time Temporal Validator",
            "desc": "Dynamic runtime validation (paper: static pre-deployment only)",
            "metric": f"Violations detected: {len(viols)}",
            "proof": f"Live monitoring active, {len(lf)} frames processed"
        },
        {
            "id": "MODULE 5",
            "title": "GenAI Threat Generator",
            "desc": "AI-powered cyber-physical attack chain generation with topology awareness",
            "metric": f"Threats generated: {len(threats)}",
            "proof": f"Attack types: {len(set(a.get('attack',{}).get('type') for a in atks))} detected"
        },
        {
            "id": "MODULE 6",
            "title": "RAG Knowledge Base",
            "desc": "Automotive-specific retrieval: VSS, CAN, ISO 26262, attack patterns",
            "metric": "Knowledge sources: 4",
            "proof": "rag_engine.py with ChromaDB/TF-IDF"
        },
        {
            "id": "MODULE 7",
            "title": "Live Streaming Dashboard",
            "desc": "Real-time monitoring with event chains, RL curves, attack feeds (paper: offline reports)",
            "metric": f"Auto-refresh: {st.session_state.refresh_rate}s",
            "proof": f"Streaming {len(lf)} frames, live updates"
        },
        {
            "id": "RL ADAPTATION",
            "title": "Reinforcement Learning",
            "desc": "Q-learning adapts timing scenarios, explores edge cases (paper: no RL)",
            "metric": f"Q-States: {rlh[-1]['q_states'] if rlh else 0}",
            "proof": f"Epsilon: {rlh[-1]['epsilon']:.3f}, Steps: {rlh[-1]['step']}" if rlh else "Initializing..."
        }
    ]
    
    for nov in novelties:
        st.markdown(f"""
<div class="novelty">
    <div class="novelty-title">{nov['id']}: {nov['title']}</div>
    <div class="novelty-desc">{nov['desc']}</div>
    <div class="novelty-metric">📊 {nov['metric']} · ✅ {nov['proof']}</div>
</div>
""", unsafe_allow_html=True)
    
    st.divider()
    
    # System comparison table
    st.markdown('<p class="sec">📋 Feature Comparison</p>', unsafe_allow_html=True)
    
    comparison = {
        "Feature": [
            "Code Language Support",
            "Timing Extraction",
            "Runtime Validation",
            "Threat Generation",
            "Knowledge Base",
            "Visualization",
            "RL Adaptation"
        ],
        "TUM Paper": [
            "Python only",
            "Manual",
            "Static (pre-deployment)",
            "Manual threat modeling",
            "None",
            "Offline diagrams",
            "No"
        ],
        "Our System": [
            "Python + C++ + Rust",
            "GenAI + RAG",
            "Real-time streaming",
            "AI-generated attack chains",
            "VSS + CAN + ISO + Attacks",
            "Live dashboard + diagrams",
            "Q-learning with exploration"
        ]
    }
    
    st.table(comparison)


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("""
<div style="text-align:center;color:#333;font-size:11px;letter-spacing:2px;padding:8px">
    GenAI-Based Real-Time Temporal Safety & Threat Detection for SDVs
    · ISO 26262 ASIL-D · ISO 21434 · Based on TUM Paper (arXiv:2601.02215)
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.auto_refresh:
    time.sleep(st.session_state.refresh_rate)
    st.rerun()