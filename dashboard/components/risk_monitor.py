"""
risk_monitor.py — Real-Time Risk Monitor Components
Renders live risk scores, threat alerts, timing gauges for the dashboard.
"""

import streamlit as st
import plotly.graph_objects as go
from typing import Optional


# ──────────────────────────────────────────────────────────────────────
# Risk gauge
# ──────────────────────────────────────────────────────────────────────

def render_risk_gauge(risk_score: float, label: str = "Risk Score"):
    """Render a speedometer-style gauge for risk score (0–1)."""
    color = (
        "#FF4B4B" if risk_score >= 0.85 else
        "#FF8C00" if risk_score >= 0.65 else
        "#FFA500" if risk_score >= 0.40 else
        "#00D4AA"
    )
    level = (
        "CRITICAL" if risk_score >= 0.85 else
        "HIGH"     if risk_score >= 0.65 else
        "MEDIUM"   if risk_score >= 0.40 else
        "LOW"
    )

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=round(risk_score, 3),
        title={"text": f"{label}<br><span style='font-size:0.8em;color:{color}'>{level}</span>",
               "font": {"color": "#E8E8E8", "size": 14}},
        number={"font": {"color": color, "size": 28}},
        gauge={
            "axis": {"range": [0, 1], "tickcolor": "#555", "tickfont": {"color": "#AAA"}},
            "bar": {"color": color},
            "bgcolor": "#1A1F2E",
            "bordercolor": "#333",
            "steps": [
                {"range": [0.0, 0.40], "color": "#0D2B1F"},
                {"range": [0.40, 0.65], "color": "#2B2000"},
                {"range": [0.65, 0.85], "color": "#2B1500"},
                {"range": [0.85, 1.0],  "color": "#2B0000"},
            ],
            "threshold": {
                "line": {"color": "#FF4B4B", "width": 3},
                "thickness": 0.75,
                "value": 0.85
            }
        }
    ))

    fig.update_layout(
        height=220,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor="#0E1117",
        font={"color": "#CCC"}
    )
    st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────
# Threat alert card
# ──────────────────────────────────────────────────────────────────────

def render_threat_alert(threat: dict):
    """Render a styled threat alert card."""
    severity = threat.get("severity", "LOW")
    tara     = threat.get("tara_score", 0.0)
    atk_type = threat.get("attack_type", "unknown")
    chain    = threat.get("attack_chain", [])
    path     = threat.get("topology_path", [])
    mitig    = threat.get("mitigation", "N/A")

    color_map = {
        "CRITICAL": "#FF4B4B",
        "HIGH":     "#FF8C00",
        "MEDIUM":   "#FFA500",
        "LOW":      "#00D4AA"
    }
    icon_map = {
        "CRITICAL": "🚨",
        "HIGH":     "⚠️",
        "MEDIUM":   "🔶",
        "LOW":      "🟢"
    }
    color = color_map.get(severity, "#CCC")
    icon  = icon_map.get(severity, "ℹ️")

    st.markdown(f"""
<div style="
    border-left: 4px solid {color};
    background: #161B22;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    margin-bottom: 10px;
">
    <div style="display:flex; justify-content:space-between; align-items:center">
        <span style="color:{color}; font-weight:700; font-size:14px">{icon} {severity} — {atk_type.upper()}</span>
        <span style="color:#888; font-size:12px">TARA: {tara}</span>
    </div>
    <div style="color:#AAA; font-size:12px; margin-top:6px">
        <b style="color:#CCC">Attack Path:</b> {" → ".join(path)}
    </div>
    <div style="color:#888; font-size:11px; margin-top:4px">
        <b style="color:#CCC">Chain:</b> {" | ".join(chain[:3])}
    </div>
    <div style="color:#00D4AA; font-size:11px; margin-top:6px">
        🛡 {mitig}
    </div>
</div>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────
# Timing violation alert
# ──────────────────────────────────────────────────────────────────────

def render_timing_alert(actual_ms: int, expected_ms: int, component: str):
    """Render a timing violation or pass banner."""
    if actual_ms > expected_ms:
        overshoot = actual_ms - expected_ms
        pct = round((actual_ms / expected_ms - 1) * 100, 1)
        st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #2B0000, #1A0000);
    border: 1px solid #FF4B4B;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 12px;
">
    <span style="color:#FF4B4B; font-weight:700; font-size:15px">
        ⏱️ TIMING VIOLATION — {component.upper()}
    </span>
    <div style="color:#CCC; font-size:13px; margin-top:6px">
        Actual: <b style="color:#FF4B4B">{actual_ms}ms</b>
        &nbsp;|&nbsp; Max: <b style="color:#AAA">{expected_ms}ms</b>
        &nbsp;|&nbsp; Overshoot: <b style="color:#FF8C00">+{overshoot}ms ({pct}% over)</b>
    </div>
</div>
""", unsafe_allow_html=True)
    else:
        margin = expected_ms - actual_ms
        st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #001A10, #000D08);
    border: 1px solid #00D4AA;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 12px;
">
    <span style="color:#00D4AA; font-weight:700; font-size:15px">
        ✅ TIMING OK — {component.upper()}
    </span>
    <div style="color:#CCC; font-size:13px; margin-top:6px">
        Actual: <b style="color:#00D4AA">{actual_ms}ms</b>
        &nbsp;|&nbsp; Max: <b style="color:#AAA">{expected_ms}ms</b>
        &nbsp;|&nbsp; Margin: <b style="color:#00D4AA">{margin}ms safe</b>
    </div>
</div>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────
# Risk history sparkline
# ──────────────────────────────────────────────────────────────────────

def render_risk_history(history: list):
    """Render a line chart of risk scores across iterations."""
    if not history:
        return

    x = list(range(1, len(history) + 1))
    y = [h.get("risk_score", 0) for h in history]
    colors = [
        "#FF4B4B" if v >= 0.85 else
        "#FF8C00" if v >= 0.65 else
        "#FFA500" if v >= 0.40 else
        "#00D4AA"
        for v in y
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines+markers",
        line=dict(color="#00D4AA", width=2),
        marker=dict(color=colors, size=8, line=dict(color="#333", width=1)),
        hovertemplate="Iter %{x}: risk=%{y:.3f}<extra></extra>"
    ))
    fig.add_hline(y=0.85, line_color="#FF4B4B", line_dash="dot",
                  annotation_text="CRITICAL", annotation_font_color="#FF4B4B")
    fig.add_hline(y=0.65, line_color="#FF8C00", line_dash="dot",
                  annotation_text="HIGH", annotation_font_color="#FF8C00")

    fig.update_layout(
        title=dict(text="Risk Score History", font=dict(size=13, color="#E8E8E8")),
        xaxis=dict(title="Iteration", color="#CCC", dtick=1),
        yaxis=dict(title="Risk Score", range=[0, 1.1], color="#CCC"),
        height=280,
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor="#161B22",
        plot_bgcolor="#0E1117"
    )
    st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────
# Summary metrics row
# ──────────────────────────────────────────────────────────────────────

def render_summary_metrics(agent_output: dict):
    """Render a clean metrics row from agent output."""
    scenarios  = agent_output.get("scenarios", [])
    mem        = agent_output.get("memory_summary", {})
    violations = sum(1 for s in scenarios if s.get("violation"))
    total      = len(scenarios)
    max_delay  = max((s.get("delay_ms", 0) for s in scenarios), default=0)
    avg_risk   = round(sum(s.get("risk_score", 0) for s in scenarios) / total, 3) if total else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Tests", total)
    with col2:
        st.metric("Violations", violations,
                  delta=f"{round(violations/total*100,1)}%" if total else "0%",
                  delta_color="inverse")
    with col3:
        st.metric("Max Delay", f"{max_delay}ms",
                  delta=f"vs {agent_output.get('max_delay_ms',100)}ms limit",
                  delta_color="inverse" if max_delay > agent_output.get("max_delay_ms", 100) else "normal")
    with col4:
        st.metric("Avg Risk", avg_risk)