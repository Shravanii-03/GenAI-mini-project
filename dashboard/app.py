"""
dashboard/app.py — GenAI SDV Safety & Threat Detection Dashboard
══════════════════════════════════════════════════════════════════
Real-time Streamlit dashboard for the SDV safety pipeline.

Sections:
  1. Run Analysis — input requirement / upload code / load trace
  2. Live Signals — vehicle speed, brake delay, steering angle
  3. Event Chain — visual activity diagram with violation markers
  4. Safety Alerts — timing violations per scenario
  5. Threat Monitor — topology-aware attack chain alerts
  6. Risk Timeline — risk score history across iterations
  7. Memory Summary — agent iteration log

Run: streamlit run dashboard/app.py
"""

import sys
import os
import json
import time
import random
import threading
from pathlib import Path
from datetime import datetime

# ── Path fix so imports work from dashboard/ subfolder ────────────────
ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st

# ── Page config MUST be first Streamlit call ─────────────────────────
st.set_page_config(
    page_title="SDV Safety Monitor",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Imports after path fix ────────────────────────────────────────────
from dashboard.components.event_chain_viz import (
    render_event_chain,
    render_chain_timing_bar,
    render_scenario_comparison
)
from dashboard.components.risk_monitor import (
    render_risk_gauge,
    render_threat_alert,
    render_timing_alert,
    render_risk_history,
    render_summary_metrics
)


# ══════════════════════════════════════════════════════════════════════
# CUSTOM CSS — dark industrial automotive theme
# ══════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Barlow', sans-serif;
    background-color: #0E1117;
    color: #E8E8E8;
}

.main-header {
    background: linear-gradient(135deg, #0D1F0D 0%, #0E1117 50%, #0D0D1F 100%);
    border-bottom: 2px solid #00D4AA;
    padding: 18px 24px 14px;
    margin-bottom: 24px;
    border-radius: 0 0 12px 12px;
}

.main-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 26px;
    color: #00D4AA;
    letter-spacing: 2px;
    margin: 0;
}

.main-sub {
    color: #555;
    font-size: 12px;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-top: 4px;
}

.section-header {
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    color: #00D4AA;
    letter-spacing: 2px;
    text-transform: uppercase;
    border-bottom: 1px solid #1E2633;
    padding-bottom: 6px;
    margin-bottom: 14px;
}

.signal-card {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 8px;
    padding: 14px 16px;
    text-align: center;
}

.signal-value {
    font-family: 'Share Tech Mono', monospace;
    font-size: 28px;
    font-weight: 700;
    margin: 4px 0;
}

.signal-label {
    color: #666;
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
}

.verdict-pass {
    background: linear-gradient(90deg, #001A10, transparent);
    border-left: 3px solid #00D4AA;
    padding: 8px 14px;
    border-radius: 0 6px 6px 0;
    color: #00D4AA;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    margin-bottom: 8px;
}

.verdict-fail {
    background: linear-gradient(90deg, #1A0000, transparent);
    border-left: 3px solid #FF4B4B;
    padding: 8px 14px;
    border-radius: 0 6px 6px 0;
    color: #FF4B4B;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    margin-bottom: 8px;
}

.status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 6px;
    animation: pulse 1.5s infinite;
}
.dot-green { background: #00D4AA; }
.dot-red   { background: #FF4B4B; }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
}

div[data-testid="metric-container"] {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 8px;
    padding: 12px 16px;
}

div[data-testid="stSidebarContent"] {
    background: #0A0D12;
    border-right: 1px solid #1E2633;
}

.stButton > button {
    background: linear-gradient(135deg, #00D4AA, #009977);
    color: #000;
    font-family: 'Share Tech Mono', monospace;
    font-weight: 700;
    letter-spacing: 1px;
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    width: 100%;
    transition: all 0.2s;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #00FFCC, #00D4AA);
    transform: translateY(-1px);
}

.stTextInput input, .stSelectbox select, .stTextArea textarea {
    background: #161B22 !important;
    color: #E8E8E8 !important;
    border: 1px solid #30363D !important;
    border-radius: 6px !important;
}

.stTabs [data-baseweb="tab"] {
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    letter-spacing: 1px;
    color: #666;
}
.stTabs [aria-selected="true"] {
    color: #00D4AA !important;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# SESSION STATE INIT
# ══════════════════════════════════════════════════════════════════════
def _init_state():
    defaults = {
        "pipeline_result": None,
        "running": False,
        "live_signals": {"speed_kmh": 0.0, "brake_delay_ms": 0.0, "steering_angle": 0.0},
        "signal_history": [],
        "mode": "requirement",
        "last_run": None
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ══════════════════════════════════════════════════════════════════════
# SIMULATED LIVE SIGNAL GENERATOR
# ══════════════════════════════════════════════════════════════════════
def _simulate_live_signals(scenario_type: str = "normal") -> dict:
    """Generate realistic simulated live vehicle signals."""
    base_speed = {"normal": 60, "edge": 80, "stress": 110}.get(scenario_type, 60)
    return {
        "speed_kmh":        round(base_speed + random.gauss(0, 5), 1),
        "brake_delay_ms":   round(abs(random.gauss(
            {"normal": 60, "edge": 90, "stress": 130}.get(scenario_type, 60), 15
        )), 1),
        "steering_angle":   round(random.gauss(0, 8), 1),
        "timestamp":        datetime.now().isoformat()
    }


# ══════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="main-header">
    <p class="main-title">🚗 SDV SAFETY & THREAT MONITOR</p>
    <p class="main-sub">GenAI-Based Real-Time Temporal Safety · ISO 26262 · ISO 21434</p>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# SIDEBAR — Controls
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<p class="section-header">⚙️ Pipeline Control</p>', unsafe_allow_html=True)

    mode = st.selectbox(
        "Analysis Mode",
        ["requirement", "code", "trace"],
        index=["requirement", "code", "trace"].index(st.session_state.mode)
    )
    st.session_state.mode = mode

    st.divider()

    if mode == "requirement":
        user_req = st.text_area(
            "Safety Requirement",
            value="Brake within 100ms if obstacle detected",
            height=80
        )
    elif mode == "code":
        code_options = [
            "datasets/code_samples/brake_python.py",
            "datasets/code_samples/brake_cpp.cpp",
            "datasets/code_samples/brake_rust.rs"
        ]
        selected_code = st.selectbox("Code File", code_options)
    else:
        trace_options = [
            "datasets/runtime_traces/scenario_1_trace.json",
            "datasets/runtime_traces/scenario_2_trace.json",
            "datasets/runtime_traces/scenario_3_trace.json"
        ]
        selected_trace = st.selectbox("Runtime Trace", trace_options)

    st.divider()

    run_btn = st.button("▶ RUN ANALYSIS", use_container_width=True)

    st.divider()
    st.markdown('<p class="section-header">📁 Load Result</p>', unsafe_allow_html=True)
    uploaded = st.file_uploader("Load saved JSON output", type=["json"])
    if uploaded:
        try:
            data = json.load(uploaded)
            st.session_state.pipeline_result = data
            st.success("Loaded!")
        except Exception as e:
            st.error(f"Parse error: {e}")

    st.divider()
    st.markdown('<p class="section-header">ℹ️ System Info</p>', unsafe_allow_html=True)
    status_color = "dot-green" if st.session_state.pipeline_result else "dot-red"
    status_text  = "Results loaded" if st.session_state.pipeline_result else "No results yet"
    st.markdown(f'<span class="status-dot {status_color}"></span>{status_text}', unsafe_allow_html=True)
    if st.session_state.last_run:
        st.caption(f"Last run: {st.session_state.last_run}")


# ══════════════════════════════════════════════════════════════════════
# RUN PIPELINE
# ══════════════════════════════════════════════════════════════════════
if run_btn:
    with st.spinner("🔄 Running SDV safety analysis pipeline..."):
        try:
            if mode == "requirement":
                # Import lazily to avoid breaking dashboard if LLM not configured
                from main_pipeline import run_requirement_mode
                result = run_requirement_mode(user_req)

            elif mode == "code":
                from main_pipeline import run_code_mode
                result = run_code_mode(selected_code)

            else:
                from main_pipeline import run_trace_mode
                result = run_trace_mode(selected_trace)

            st.session_state.pipeline_result = result
            st.session_state.last_run = datetime.now().strftime("%H:%M:%S")
            st.success("✅ Analysis complete!")
            st.rerun()

        except Exception as e:
            st.error(f"Pipeline error: {e}")
            st.info("💡 Check your GROQ_API_KEY in .env and that all modules are in the root folder.")


# ══════════════════════════════════════════════════════════════════════
# MAIN CONTENT — show results or demo
# ══════════════════════════════════════════════════════════════════════
result = st.session_state.pipeline_result

# If no result yet, show demo data
if result is None:
    st.markdown("""
<div style="text-align:center; padding: 60px 20px; color: #444;">
    <div style="font-size:48px; margin-bottom:16px">🚗</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:18px; color:#00D4AA; margin-bottom:8px">
        AWAITING ANALYSIS
    </div>
    <div style="font-size:13px; color:#555; letter-spacing:1px">
        Enter a safety requirement in the sidebar and click RUN ANALYSIS
    </div>
    <div style="font-size:12px; color:#333; margin-top:20px">
        Example: "Brake within 100ms if obstacle detected"
    </div>
</div>
""", unsafe_allow_html=True)

    # Show demo with trace data
    st.markdown('<p class="section-header">🗂️ Quick Demo — Scenario Traces</p>', unsafe_allow_html=True)
    trace_col1, trace_col2, trace_col3 = st.columns(3)
    traces_info = [
        {"id": "S1", "name": "Accelerates Instead of Braking", "verdict": "FAIL", "severity": "CRITICAL"},
        {"id": "S2", "name": "Wrong Sensor Used", "verdict": "FAIL", "severity": "HIGH"},
        {"id": "S3", "name": "Brake Before Detection", "verdict": "FAIL", "severity": "HIGH"},
    ]
    for col, t in zip([trace_col1, trace_col2, trace_col3], traces_info):
        with col:
            v_class = "verdict-fail" if t["verdict"] == "FAIL" else "verdict-pass"
            st.markdown(f"""
<div class="{v_class}">
    {t['id']}: {t['name']}<br>
    <small>{t['severity']}</small>
</div>
""", unsafe_allow_html=True)
    st.stop()


# ══════════════════════════════════════════════════════════════════════
# RESULTS DISPLAY
# ══════════════════════════════════════════════════════════════════════

pipeline_mode = result.get("mode", "requirement")

# ── TABS ─────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Overview",
    "⛓️ Event Chain",
    "⏱️ Timing",
    "🚨 Threats",
    "🧠 Agent Memory"
])


# ────────────────────────────────────────────────────────────────────
# TAB 1: Overview
# ────────────────────────────────────────────────────────────────────
with tab1:
    if pipeline_mode == "requirement":
        agent_out = result.get("agent_output", {})
        scenarios = agent_out.get("scenarios", [])
        mem       = agent_out.get("memory_summary", {})

        # Top metrics
        st.markdown('<p class="section-header">📈 Summary Metrics</p>', unsafe_allow_html=True)
        render_summary_metrics(agent_out)

        st.divider()

        # Live signals simulation
        st.markdown('<p class="section-header">📡 Live Vehicle Signals (Simulated)</p>',
                    unsafe_allow_html=True)

        # Simulate signal for last scenario type
        last_type = scenarios[-1].get("type", "normal") if scenarios else "normal"
        live = _simulate_live_signals(last_type)

        sig1, sig2, sig3 = st.columns(3)
        speed_color = "#FF4B4B" if live["speed_kmh"] > 100 else "#00D4AA"
        brake_color = "#FF4B4B" if live["brake_delay_ms"] > agent_out.get("max_delay_ms", 100) else "#00D4AA"
        steer_color = "#FFA500" if abs(live["steering_angle"]) > 30 else "#00D4AA"

        with sig1:
            st.markdown(f"""
<div class="signal-card">
    <div class="signal-label">Vehicle Speed</div>
    <div class="signal-value" style="color:{speed_color}">{live['speed_kmh']}</div>
    <div class="signal-label">km/h</div>
</div>
""", unsafe_allow_html=True)

        with sig2:
            st.markdown(f"""
<div class="signal-card">
    <div class="signal-label">Brake Delay</div>
    <div class="signal-value" style="color:{brake_color}">{live['brake_delay_ms']}</div>
    <div class="signal-label">ms</div>
</div>
""", unsafe_allow_html=True)

        with sig3:
            st.markdown(f"""
<div class="signal-card">
    <div class="signal-label">Steering Angle</div>
    <div class="signal-value" style="color:{steer_color}">{live['steering_angle']}°</div>
    <div class="signal-label">degrees</div>
</div>
""", unsafe_allow_html=True)

        st.divider()

        # Risk gauges per scenario
        st.markdown('<p class="section-header">🎯 Risk Scores by Scenario</p>', unsafe_allow_html=True)
        gcols = st.columns(min(len(scenarios), 3))
        for i, (col, s) in enumerate(zip(gcols, scenarios[:3])):
            with col:
                render_risk_gauge(
                    s.get("risk_score", 0),
                    label=f"{s.get('type','?').upper()} #{i+1}"
                )

        # Scenario verdicts
        st.markdown('<p class="section-header">📋 Scenario Verdicts</p>', unsafe_allow_html=True)
        for s in scenarios:
            v_class = "verdict-fail" if s.get("violation") else "verdict-pass"
            icon    = "❌" if s.get("violation") else "✅"
            road    = s.get("road_condition", "?")
            st.markdown(f"""
<div class="{v_class}">
    {icon} [{s.get('type','?').upper()}] 
    delay={s.get('delay_ms','?')}ms 
    | risk={s.get('risk_score','?')} 
    | road={road}
    | {s.get('severity','?')}
</div>
""", unsafe_allow_html=True)

        # Explanation
        if agent_out.get("explanation"):
            st.divider()
            st.markdown('<p class="section-header">💬 GenAI Safety Explanation</p>',
                        unsafe_allow_html=True)
            st.info(agent_out["explanation"])

    elif pipeline_mode == "code":
        code_result = result.get("code_analysis", {})
        st.markdown('<p class="section-header">🔍 Code Analysis Result</p>',
                    unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        with cc1:
            st.metric("Language",  code_result.get("language", "?").upper())
            st.metric("CAN IDs",   len(code_result.get("can_ids", [])))
        with cc2:
            st.metric("VSS Signals",       len(code_result.get("vss_signals", [])))
            st.metric("Safety Functions",  len(code_result.get("safety_functions", [])))

        with st.expander("Full Extraction Result"):
            st.json(code_result)

    elif pipeline_mode == "trace":
        val = result.get("validation", {})
        st.markdown('<p class="section-header">⏱️ Trace Validation Result</p>',
                    unsafe_allow_html=True)
        component = val.get("scenario_name", "SDV Component")
        render_timing_alert(val.get("actual_ms", 0), val.get("expected_ms", 100), component)

        t1, t2, t3 = st.columns(3)
        with t1: st.metric("Risk Level", val.get("risk_level", "?"))
        with t2: st.metric("Verdict",    val.get("verdict", "?"))
        with t3: st.metric("Bottleneck", val.get("bottleneck", {}).get("step", "N/A") if val.get("bottleneck") else "None")

        with st.expander("Full Validation"):
            st.json(val)


# ────────────────────────────────────────────────────────────────────
# TAB 2: Event Chain
# ────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown('<p class="section-header">⛓️ Event Chain Visualization</p>',
                unsafe_allow_html=True)

    if pipeline_mode == "requirement":
        agent_out = result.get("agent_output", {})
        chain     = agent_out.get("event_chain", [])
        scenarios = agent_out.get("scenarios", [])

        if chain:
            # Collect violated steps from all scenarios
            all_attack_steps = []
            for s in scenarios:
                if s.get("violation") and s.get("attack_chain"):
                    all_attack_steps.extend(s["attack_chain"][:1])

            render_event_chain(
                event_chain=chain,
                violations=all_attack_steps,
                title=f"{agent_out.get('event','event').title()} Event Chain — {agent_out.get('iso_standard','')}"
            )

            st.divider()
            # Scenario comparison bar
            st.markdown('<p class="section-header">📊 Scenario Delay Comparison</p>',
                        unsafe_allow_html=True)
            scenarios_with_max = [
                {**s, "max_latency_ms": agent_out.get("max_delay_ms", 100)}
                for s in scenarios
            ]
            render_scenario_comparison(scenarios_with_max)

            # Mermaid diagram
            st.divider()
            st.markdown('<p class="section-header">🔷 Mermaid Diagram (copy-paste ready)</p>',
                        unsafe_allow_html=True)
            from diagram_generator import generate_mermaid_from_chain
            mermaid = generate_mermaid_from_chain(chain, title=f"{agent_out.get('event','event').title()} Chain")
            st.code(f"```mermaid\n{mermaid}\n```", language="markdown")

    elif pipeline_mode == "trace":
        from main_pipeline import run_trace_mode
        trace_path = result.get("trace_path", "")
        if trace_path and os.path.exists(trace_path):
            with open(trace_path) as f:
                trace_data = json.load(f)
            chain = trace_data.get("events", [])
            chain_timing = trace_data.get("event_chain_timing", [])
            violations = [e for e in chain if "INVALID" in e or "PREMATURE" in e]
            render_event_chain(chain, chain_timing, violations,
                               title=trace_data.get("name", "Trace"))
    else:
        code_res = result.get("code_analysis", {})
        render_event_chain(
            code_res.get("event_chain", []),
            title=f"{code_res.get('language','?').upper()} Code Event Chain"
        )


# ────────────────────────────────────────────────────────────────────
# TAB 3: Timing
# ────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown('<p class="section-header">⏱️ Timing Analysis</p>', unsafe_allow_html=True)

    if pipeline_mode == "requirement":
        timing_ext = result.get("timing_extraction", {})
        agent_out  = result.get("agent_output", {})

        # Timing extraction result
        if timing_ext:
            tc1, tc2, tc3 = st.columns(3)
            with tc1:
                st.metric("Max Latency",  f"{timing_ext.get('total_latency_ms','?')} ms")
            with tc2:
                st.metric("ASIL Level",   timing_ext.get("asil_level", "?"))
            with tc3:
                st.metric("ISO Rule",     timing_ext.get("iso_rule_id", "N/A") or "N/A")

            breakdown = timing_ext.get("breakdown_ms", {})
            if breakdown:
                st.markdown('<p class="section-header">🔧 Timing Budget Breakdown</p>',
                            unsafe_allow_html=True)
                import plotly.graph_objects as go
                steps  = list(breakdown.keys())
                values = list(breakdown.values())
                total  = sum(values) or 1
                colors = ["#00D4AA", "#00A882", "#007A5E", "#005A44", "#003D2E"]

                fig = go.Figure(go.Pie(
                    labels=[s.replace("_ms","").replace("_"," ").title() for s in steps],
                    values=values,
                    hole=0.5,
                    marker=dict(colors=colors[:len(steps)],
                                line=dict(color="#0E1117", width=2)),
                    textinfo="label+percent",
                    textfont=dict(color="#E8E8E8", size=12)
                ))
                fig.update_layout(
                    title=dict(text=f"Total: {sum(values)}ms budget", font=dict(color="#CCC")),
                    height=280,
                    margin=dict(l=20, r=20, t=50, b=20),
                    paper_bgcolor="#0E1117",
                    showlegend=False
                )
                st.plotly_chart(fig, use_container_width=True)

            if timing_ext.get("iso_warning"):
                st.warning(f"⚠️ ISO Warning: {timing_ext['iso_warning']}")
            elif timing_ext.get("iso_compliant"):
                st.success("✅ Timing is ISO 26262 compliant")

        st.divider()

        # Per-scenario timing alerts
        st.markdown('<p class="section-header">🔔 Per-Scenario Timing Alerts</p>',
                    unsafe_allow_html=True)
        for s in agent_out.get("scenarios", []):
            render_timing_alert(
                s.get("delay_ms", 0),
                agent_out.get("max_delay_ms", 100),
                f"{s.get('type','?').upper()} — {s.get('road_condition','?')}"
            )

    elif pipeline_mode == "trace":
        val = result.get("validation", {})
        render_timing_alert(val.get("actual_ms", 0), val.get("expected_ms", 100), "Trace Scenario")

        chain_steps = val.get("chain_steps", [])
        if chain_steps:
            st.markdown('<p class="section-header">📊 Per-Step Timing</p>', unsafe_allow_html=True)
            render_chain_timing_bar(
                [{"step": s["step"], "time_ms": s["time_ms"]} for s in chain_steps],
                val.get("expected_ms", 100)
            )

        if val.get("chain_order_violations"):
            st.markdown('<p class="section-header">❌ Event Chain Order Violations</p>',
                        unsafe_allow_html=True)
            for v in val["chain_order_violations"]:
                st.error(f"[{v['rule_id']}] {v['violation']}")


# ────────────────────────────────────────────────────────────────────
# TAB 4: Threats
# ────────────────────────────────────────────────────────────────────
with tab4:
    st.markdown('<p class="section-header">🚨 Cyber-Physical Threat Analysis</p>',
                unsafe_allow_html=True)

    threats = []
    if pipeline_mode == "requirement":
        threats = result.get("topology_threats", [])
        # Fallback to agent output threats
        if not threats:
            for s in result.get("agent_output", {}).get("scenarios", []):
                if s.get("attack_chain"):
                    threats.append({
                        "attack_type":               "unknown",
                        "severity":                  s.get("severity", "?"),
                        "tara_score":                s.get("risk_score", 0),
                        "topology_path":             s.get("attack_chain", [])[:4],
                        "attack_chain":              s.get("attack_chain", []),
                        "mitigation":                s.get("mitigation", "N/A"),
                        "software_to_physical_impact": "See attack chain"
                    })
    elif pipeline_mode == "trace":
        # Build synthetic threat from trace
        trace_path = result.get("trace_path", "")
        if trace_path and os.path.exists(trace_path):
            with open(trace_path) as f:
                td = json.load(f)
            threats = [{
                "attack_type":    td.get("violation_reason", "timing violation"),
                "severity":       td.get("severity", "HIGH"),
                "tara_score":     td.get("risk_score", 0),
                "topology_path":  ["Sensor", "ECU", "Actuator", "Physical"],
                "attack_chain":   td.get("events", [])[:4],
                "mitigation":     "Review event chain ordering per ISO 26262"
            }]

    if threats:
        # Critical threats first
        from dashboard.components.risk_monitor import render_risk_gauge
        crit = [t for t in threats if t.get("severity") == "CRITICAL"]
        high = [t for t in threats if t.get("severity") == "HIGH"]
        rest = [t for t in threats if t.get("severity") not in ("CRITICAL", "HIGH")]

        if crit:
            st.markdown("**🚨 CRITICAL**")
            for t in crit: render_threat_alert(t)
        if high:
            st.markdown("**⚠️ HIGH**")
            for t in high: render_threat_alert(t)
        if rest:
            st.markdown("**🔶 OTHER**")
            for t in rest: render_threat_alert(t)

        # TARA scores bar chart
        if len(threats) > 1:
            st.divider()
            st.markdown('<p class="section-header">📊 TARA Score Comparison</p>',
                        unsafe_allow_html=True)
            import plotly.graph_objects as go
            labels = [f"{i+1}. {t.get('attack_type','?').upper()}" for i, t in enumerate(threats)]
            scores = [t.get("tara_score", 0) for t in threats]
            colors_t = [
                "#FF4B4B" if s >= 0.85 else
                "#FF8C00" if s >= 0.65 else
                "#FFA500" if s >= 0.40 else "#00D4AA"
                for s in scores
            ]
            fig = go.Figure(go.Bar(
                x=labels, y=scores,
                marker_color=colors_t,
                text=[f"{s:.3f}" for s in scores],
                textposition="auto"
            ))
            fig.add_hline(y=0.85, line_color="#FF4B4B", line_dash="dot")
            fig.update_layout(
                yaxis=dict(range=[0, 1.0], title="TARA Score", color="#CCC"),
                xaxis=dict(color="#CCC"),
                height=280,
                margin=dict(l=20, r=20, t=30, b=60),
                paper_bgcolor="#161B22",
                plot_bgcolor="#0E1117"
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No threat data available. Run a requirement or trace analysis.")


# ────────────────────────────────────────────────────────────────────
# TAB 5: Agent Memory
# ────────────────────────────────────────────────────────────────────
with tab5:
    st.markdown('<p class="section-header">🧠 Agent Memory & Iteration Log</p>',
                unsafe_allow_html=True)

    if pipeline_mode == "requirement":
        agent_out = result.get("agent_output", {})
        mem = agent_out.get("memory_summary", {})

        if mem:
            mc1, mc2, mc3, mc4 = st.columns(4)
            with mc1: st.metric("Total Tests",  mem.get("total_tests", 0))
            with mc2: st.metric("Violations",   mem.get("total_violations", 0))
            with mc3: st.metric("Violation Rate", f"{mem.get('violation_rate_pct',0)}%")
            with mc4: st.metric("Avg Risk",      mem.get("avg_risk_score", 0))

            st.divider()

            # Risk history chart
            history = [{"risk_score": r, "actual_delay_ms": d}
                       for r, d in zip(
                           [s.get("risk_score", 0) for s in agent_out.get("scenarios", [])],
                           [s.get("delay_ms", 0)   for s in agent_out.get("scenarios", [])]
                       )]
            render_risk_history(history)

            # RL summary
            rl = result.get("rl_summary", {})
            if rl:
                st.divider()
                st.markdown('<p class="section-header">🔁 RL Adaptive Simulation Summary</p>',
                            unsafe_allow_html=True)
                rc1, rc2, rc3 = st.columns(3)
                with rc1: st.metric("RL Tests",     rl.get("total_tests", 0))
                with rc2: st.metric("Max Delay",    f"{rl.get('max_delay_ms',0)}ms")
                with rc3: st.metric("Min Delay",    f"{rl.get('min_delay_ms',0)}ms")

        # Next action
        next_act = agent_out.get("next_action")
        if next_act:
            st.divider()
            st.markdown('<p class="section-header">➡️ Agent Next Recommended Action</p>',
                        unsafe_allow_html=True)
            st.markdown(f"""
<div style="background:#161B22; border:1px solid #00D4AA; border-radius:8px; padding:14px 18px;">
    <span style="color:#00D4AA; font-family:'Share Tech Mono',monospace">{next_act}</span>
</div>
""", unsafe_allow_html=True)

        # Full JSON expander
        with st.expander("📄 Full Agent Output JSON"):
            st.json(agent_out)

    else:
        with st.expander("📄 Full Pipeline Output"):
            st.json(result)


# ══════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("""
<div style="text-align:center; color:#333; font-size:11px; letter-spacing:2px; padding:8px">
    GenAI-Based Real-Time Temporal Safety & Threat Detection for SDVs
    · Based on TUM Paper (arXiv:2601.02215) · ISO 26262 · ISO 21434
</div>
""", unsafe_allow_html=True)