"""
event_chain_viz.py — Event Chain Visualization Component
Uses shapes instead of annotations for arrows (compatible with all plotly versions)
"""

import streamlit as st
import plotly.graph_objects as go
from typing import Optional


def render_event_chain(
    event_chain: list,
    chain_timing: Optional[list] = None,
    violations: Optional[list] = None,
    title: str = "Event Chain"
):
    if not event_chain:
        st.info("No event chain data available.")
        return

    violations = violations or []
    timing_map = {}
    if chain_timing:
        timing_map = {t.get("step", ""): t.get("time_ms", 0) for t in chain_timing}

    n = len(event_chain)
    y_positions = list(range(n, 0, -1))

    colors = []
    for step in event_chain:
        is_viol = any(v.lower() in step.lower() or step.lower() in v.lower() for v in violations)
        is_dec  = any(kw in step.lower() for kw in ["detect", "decide", "check", "fuse"])
        if is_viol:
            colors.append("#FF4B4B")
        elif is_dec:
            colors.append("#FFA500")
        else:
            colors.append("#00D4AA")

    labels = []
    for step in event_chain:
        label = step.replace("_", " ").title()
        t = timing_map.get(step)
        if t:
            label += f"  [{t}ms]"
        labels.append(label)

    fig = go.Figure()

    # Draw connecting line
    fig.add_trace(go.Scatter(
        x=[0.5] * n,
        y=y_positions,
        mode="lines",
        line=dict(color="#444", width=2),
        hoverinfo="none"
    ))

    # Draw nodes
    fig.add_trace(go.Scatter(
        x=[0.5] * n,
        y=y_positions,
        mode="markers+text",
        marker=dict(
            size=22,
            color=colors,
            symbol="square",
            line=dict(color="#222", width=2)
        ),
        text=labels,
        textposition="middle right",
        textfont=dict(size=12, family="monospace", color="#E8E8E8"),
        hovertext=[f"Step {i+1}: {step}" for i, step in enumerate(event_chain)],
        hoverinfo="text"
    ))

    # Add downward arrow shapes between nodes
    shapes = []
    for i in range(n - 1):
        y_start = y_positions[i] - 0.15
        y_end   = y_positions[i + 1] + 0.15
        shapes.append(dict(
            type="line",
            x0=0.5, x1=0.5,
            y0=y_start, y1=y_end,
            xref="paper", yref="y",
            line=dict(color="#00D4AA", width=2)
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#E8E8E8")),
        xaxis=dict(visible=False, range=[0, 2.5]),
        yaxis=dict(visible=False, range=[0, n + 1]),
        shapes=shapes,
        height=max(300, n * 80),
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)


def render_chain_timing_bar(chain_timing: list, max_latency_ms: int, title: str = "Step Timing Breakdown"):
    if not chain_timing:
        return

    steps  = [t.get("step", "?").replace("_", " ").title() for t in chain_timing]
    deltas = []
    prev   = 0
    for t in chain_timing:
        curr = t.get("time_ms", 0)
        deltas.append(max(curr - prev, 0))
        prev = curr

    budget = max_latency_ms / max(len(chain_timing), 1)
    colors_bar = ["#FF4B4B" if d > budget else "#00D4AA" for d in deltas]

    fig = go.Figure(go.Bar(
        x=deltas,
        y=steps,
        orientation="h",
        marker=dict(color=colors_bar, line=dict(color="#333", width=1)),
        text=[f"{d}ms" for d in deltas],
        textposition="auto"
    ))

    fig.add_vline(
        x=budget,
        line_color="#FFA500",
        line_dash="dash",
        annotation_text="Budget/step",
        annotation_font_color="#FFA500"
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#E8E8E8")),
        xaxis=dict(title="Time (ms)", color="#CCC"),
        yaxis=dict(color="#CCC"),
        height=max(250, len(steps) * 45),
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor="#161B22",
        plot_bgcolor="#0E1117",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)


def render_scenario_comparison(scenarios: list):
    if not scenarios:
        return

    labels   = [f"{s.get('type','?').upper()} #{i+1}" for i, s in enumerate(scenarios)]
    actual   = [s.get("delay_ms", 0) for s in scenarios]
    expected = [sc.get("max_latency_ms", 100) for sc in scenarios]
    colors   = ["#FF4B4B" if s.get("violation") else "#00D4AA" for s in scenarios]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Actual Delay",
        x=labels, y=actual,
        marker_color=colors,
        text=[f"{v}ms" for v in actual],
        textposition="auto"
    ))
    fig.add_trace(go.Bar(
        name="Max Allowed",
        x=labels, y=expected,
        marker_color="#444",
        opacity=0.5
    ))

    fig.update_layout(
        barmode="overlay",
        title=dict(text="Scenario Delays vs Threshold", font=dict(size=13, color="#E8E8E8")),
        xaxis=dict(color="#CCC"),
        yaxis=dict(title="ms", color="#CCC"),
        legend=dict(font=dict(color="#CCC"), bgcolor="rgba(0,0,0,0)"),
        height=300,
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor="#161B22",
        plot_bgcolor="#0E1117"
    )

    st.plotly_chart(fig, use_container_width=True)