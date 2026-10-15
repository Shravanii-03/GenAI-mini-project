"""
dashboard/rebuilt_app.py - browser front end for the rebuilt pipeline (sdv/).

    streamlit run dashboard/rebuilt_app.py

Tabs
  Attack explorer   pick a scenario, an attack and a defence configuration and watch one emulated run
  Pipeline          run python -m sdv from the browser, or load the last saved run
  Conformance       can the extracted deadline be met, and proven?
  Defences          which attacks does each defence configuration leave open?
  Evidence          the audited evidence bundle, with a button that re-runs every check
  Results           the experiment tables (experiments/RESULTS.md) and the project figures

Everything shown comes from the emulator and the saved results; nothing here is a measurement on a real vehicle.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from sdv.analysis.bounds import FLOOD_FAMILIES, FORGING, latency_bound_ms
from sdv.analysis.defence_assessment import DEFENCES, chain_for
from sdv.attacks.library import ALL_ATTACKS, make_attack
from sdv.plant.longitudinal import decel_for_road, latest_safe_latency_ms
from sdv.plant.profile import apply_profile, load_profile
from sdv.runner import execute
from sdv.schemas import Scenario

OUT_DIR = ROOT / "outputs" / "dashboard_run"
SAVED_RUNS = {"Last command-line run": ROOT / "outputs" / "pipeline_run",
              "Last run with the CARLA-calibrated plant": ROOT / "outputs" / "pipeline_run_carla",
              "Last dashboard run": OUT_DIR}
PROFILES = {"Configured defaults (7.85 m/s^2)": None,
            "CARLA Model 3 (5.31 m/s^2)": ROOT / "experiments" / "profiles" / "carla_model3.json"}

st.set_page_config(page_title="SDV safety pipeline", page_icon="🚗", layout="wide")
st.markdown("""
<style>
.small {font-size: 0.85rem; color: #6b7280;}
.verdict-ok {color: #2e8b57; font-weight: 600;}
.verdict-bad {color: #c0392b; font-weight: 600;}
.verdict-warn {color: #d9822b; font-weight: 600;}
</style>""", unsafe_allow_html=True)

st.title("🚗 Temporal safety and threat detection for software-defined vehicles")
st.caption("Emulated CAN bus, brake chain and braking physics. Assumed ECU timings; every result is from the emulator or "
           "the saved experiment logs, not from a real vehicle.")


def load_summary(path: Path):
    file = path / "pipeline_summary.json"
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else None


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Pipeline")
    requirement = st.text_area("Requirement", "Brake within 100 ms if an obstacle is detected.", height=80)
    blue = st.selectbox("Blue team", ["enumerate", "random", "none"], help="LLM mode needs an API key and is not offered here")
    n_family = st.slider("Attacks sampled per family", 10, 60, 30, step=5)
    assess_n = st.slider("Attacks sampled per variant (defence assessment)", 10, 60, 20, step=5)
    profile_name = st.selectbox("Plant", list(PROFILES))
    run_clicked = st.button("▶ Run pipeline", type="primary", width="stretch")
    st.divider()
    available = [k for k, v in SAVED_RUNS.items() if (v / "pipeline_summary.json").exists()]
    saved_choice = st.selectbox("Or load a saved run", ["(none)"] + available)

if run_clicked:
    from sdv.pipeline import run_pipeline
    profile = load_profile(PROFILES[profile_name]) if PROFILES[profile_name] else None
    with st.spinner("Running the pipeline (about a minute)..."):
        st.session_state["summary"] = run_pipeline(requirement, seed=1, n_per_family=n_family, blue=blue,
                                                   out_dir=str(OUT_DIR), plant_profile=profile, assess_n=assess_n)
        st.session_state["run_dir"] = OUT_DIR
elif saved_choice != "(none)" and st.session_state.get("loaded") != saved_choice:
    st.session_state["summary"] = load_summary(SAVED_RUNS[saved_choice])
    st.session_state["run_dir"] = SAVED_RUNS[saved_choice]
    st.session_state["loaded"] = saved_choice

summary = st.session_state.get("summary")
run_dir = st.session_state.get("run_dir")

tabs = st.tabs(["Attack explorer", "Pipeline", "Conformance", "Defences", "Evidence", "Results"])

# ------------------------------------------------------------------ attack explorer
with tabs[0]:
    st.subheader("One emulated run")
    st.markdown("An obstacle becomes a threat `gap` metres ahead of a car at `speed`. The brake chain "
                "(sensor → perception → decision → brake) runs over the emulated CAN bus while an attacker acts. "
                "The car collides if the brake takes effect after the **point of no return**.")
    left, right = st.columns([1, 1])
    with left:
        speed = st.slider("Speed (km/h)", 30, 100, 60)
        gap = st.slider("Obstacle gap (m)", 8.0, 80.0, 24.0, step=1.0)
        load = st.slider("CPU load", 0.0, 0.9, 0.3, step=0.05)
        seed = st.number_input("Random seed", 0, 10_000, 1)
        defence = st.selectbox("Defence configuration", [name for name, _ in DEFENCES], index=0,
                               help="radar_or: failover to the radar; +guard: gateway guard; +auth: message authentication "
                                    "with a watchdog")
    with right:
        family = st.selectbox("Attack", ["(no attack)"] + list(ALL_ATTACKS))
        params, extra = {}, {}
        if family != "(no attack)":
            for key, (lo, hi) in ALL_ATTACKS[family].PARAM_BOUNDS.items():
                if key == "k":
                    params[key] = st.slider(key, int(lo), int(hi), int(lo))
                else:
                    params[key] = st.slider(key, float(lo), float(hi), float((lo + hi) / 2))
            if family in FLOOD_FAMILIES:
                node = st.checkbox("Attacker is a node on the safety bus (not behind the gateway guard)")
                extra["segment"] = "safety" if node else "untrusted"
            if family in FORGING:
                extra["holds_key"] = st.checkbox("Attacker holds the signing key")
    scenario = Scenario(v0_kmh=float(speed), d0_m=float(gap), cpu_load=float(load))
    chain = chain_for(dict(DEFENCES)[defence])
    selected_profile = load_profile(PROFILES[profile_name]) if PROFILES[profile_name] else None
    attack = None if family == "(no attack)" else make_attack(family, **params, **extra)
    with apply_profile(selected_profile):          # the explorer follows the plant chosen in the sidebar
        ponr = latest_safe_latency_ms(scenario)
        braking = decel_for_road("dry")
        result, chain_obj = execute(scenario, int(seed), chain, attacks=[attack] if attack else [])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Point of no return", f"{ponr:.0f} ms", help="Latest brake delay that still avoids the obstacle")
    if result.e2e_latency_ms is None:
        c2.metric("Brake latency", "never braked")
    else:
        c2.metric("Brake latency", f"{result.e2e_latency_ms:.0f} ms", delta=f"{ponr - result.e2e_latency_ms:.0f} ms to spare"
                  if ponr > 0 else None)
    c3.metric("Outcome", "COLLISION" if result.outcome.collision else "safe stop",
              delta=f"impact {result.outcome.impact_speed_ms * 3.6:.0f} km/h" if result.outcome.collision else None,
              delta_color="inverse")
    c4.metric("Chain started by", chain_obj.trigger_source or "nothing")
    if ponr < 0:
        st.warning("This scenario is unavoidable even with zero delay: the obstacle is too close for this speed.")
    stages = pd.DataFrame({"stage": list(result.stage_ms), "ms": list(result.stage_ms.values())})
    if not stages.empty:
        st.bar_chart(stages.set_index("stage"), horizontal=True)
    if attack is not None:
        try:
            with apply_profile(selected_profile):
                bound = latency_bound_ms(scenario, make_attack(family, **params, **extra), chain)
            verdict = bound.total_ms <= ponr
            st.markdown(f"**Analytic worst case for this attack:** {bound.total_ms:.0f} ms against a point of no return of "
                        f"{ponr:.0f} ms → " + ('<span class="verdict-ok">proven safe for any random seed</span>' if verdict
                                               else '<span class="verdict-warn">not provable (the bound is conservative)</span>'),
                        unsafe_allow_html=True)
        except ValueError:
            pass
    st.caption(f"Braking assumed at {braking:.2f} m/s². Rejected frames by authentication: "
               f"{chain_obj.rejected_frames}.")

# ------------------------------------------------------------------ pipeline
with tabs[1]:
    if not summary:
        st.info("Run the pipeline from the sidebar, or load a saved run.")
    elif "error" in summary:
        st.error(summary["error"])
    else:
        st.subheader("Pipeline summary")
        a, b, c, d = st.columns(4)
        a.metric("Attack-induced hazards (round 0)", summary["hazards_round0"])
        b.metric("Missed by the monitors", summary["missed_round0"])
        c.metric("Hazards flagged in time", f"{summary['in_time_before']:.0%} → {summary['in_time_after']:.0%}")
        d.metric("False-alarm rate", f"{summary['fpr_before']:.2f} → {summary['fpr_after']:.2f}")
        st.markdown(f"**Spec:** deadline {summary['spec']['deadline_ms']:g} ms, `{summary['spec']['formula']}` "
                    f"({summary['spec_method']})")
        profile = summary.get("plant_profile")
        st.markdown("**Plant:** " + (f"{profile['name']} ({profile['decel_ms2']} m/s², ramp {profile['brake_ramp_ms']} ms)"
                                     if profile else "configured defaults"))
        st.markdown("**Verified monitor rules**")
        for rule in summary["rules"]:
            st.code(json.dumps(rule), language="json")
        if summary.get("rules_dropped_by_deployment_check"):
            st.warning(f"{len(summary['rules_dropped_by_deployment_check'])} verified rule(s) were dropped because the deployed "
                       "monitor (baseline monitors plus rules) would exceed the false-alarm cap.")
        if summary["round1_missed"]:
            st.markdown("**Residual risk after the blue team** (sampled attacks that still cause a collision unnoticed)")
            st.dataframe(pd.DataFrame([{"family": k, "missed": f"{v}/{summary['round1_sampled_per_family']}"}
                                       for k, v in summary["round1_missed"].items()]), hide_index=True)

# ------------------------------------------------------------------ conformance
with tabs[2]:
    conf = summary.get("conformance") if summary else None
    if not conf:
        st.info("Run or load a pipeline run to see requirement conformance.")
    else:
        st.subheader(f"Can the {conf['deadline_ms']:g} ms requirement be met, and proven?")
        st.caption(conf["convention"])
        rows = []
        for name, c in conf["configs"].items():
            rows.append({"configuration": name, "verdict": c["verdict"],
                         "analytic worst case (ms)": round(c["bound_max_ms"]),
                         "slowest simulated run (ms)": round(c["observed_max_ms"]),
                         "smallest provable deadline (ms)": round(c["smallest_provable_deadline_ms"])})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        first = next(iter(conf["configs"].values()))
        st.markdown("**Where the worst case comes from** (baseline configuration, worst scenario)")
        parts = pd.DataFrame({"part": list(first["worst_case_breakdown_ms"]), "ms": list(first["worst_case_breakdown_ms"].values())})
        st.bar_chart(parts.set_index("part"), horizontal=True)
        st.caption("The bound uses worst-case compute times (an assumed 4-sigma jitter on each stage), so it is larger than any "
                   "simulated run. 'Not provable' means the bound is too coarse to decide, not that the system is unsafe.")

# ------------------------------------------------------------------ defences
with tabs[3]:
    da = summary.get("defence_assessment") if summary else None
    if not da:
        st.info("Run or load a pipeline run with the defence assessment to see this tab.")
    else:
        st.subheader("Which attacks does each defence leave open?")
        names = da["defences"]
        rec = {r["variant"]: r for r in da["recommendation"]}
        table = pd.DataFrame([{"attack variant": r["variant"], **{n: r["hazard"][n] for n in names},
                               "cheapest sufficient defence": rec[r["variant"]]["config"] or "OPEN"} for r in da["rows"]])

        def colour(value):
            if isinstance(value, float):
                shade = int(255 - min(1.0, value / 0.6) * 170)
                return f"background-color: rgb(255,{shade},{shade})"
            return "font-weight: 600; color: #c0392b" if value == "OPEN" else ""

        styled = table.style.map(colour, subset=names + ["cheapest sufficient defence"]).format({n: "{:.0%}" for n in names})
        st.dataframe(styled, hide_index=True, width="stretch")
        st.markdown("**Open after every defence:** " + (", ".join(f"`{v}`" for v in da["open"]) or "none"))
        st.caption(f"{da['n_per_variant']} sampled attacks per variant; 'covered' means a sampled hazard share of at most "
                   f"{da['eps']:.0%}. A small sample cannot certify a defence: zero hazards in 40 samples still allows about 9% "
                   f"at 95% confidence. Analytic bound violations: {da['bound_violations']}/{da['bound_runs']} simulated runs.")

# ------------------------------------------------------------------ evidence
with tabs[4]:
    bundle_file = (run_dir / "evidence_bundle.json") if run_dir else None
    if not bundle_file or not bundle_file.exists():
        st.info("No evidence bundle in this run (it needs at least one verified monitor rule).")
    else:
        bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
        st.subheader("Audited evidence")
        st.markdown(f"Requirement → spec → counter-example (`{bundle['violation']['attack']['family']}`) → threat → rule → "
                    "outcome under every defence.")
        if st.button("🔁 Re-run every check"):
            from sdv.evidence.audit import audit
            with st.spinner("Re-simulating every claim..."):
                report = audit(bundle)
            message = f"{report['passed']}/{report['total']} checks re-verified"
            if report["all_passed"]:
                st.success(message)
            else:
                st.error(message)
            st.dataframe(pd.DataFrame([{"check": c["name"], "result": "PASS" if c["passed"] else "FAIL",
                                        "detail": c["detail"]} for c in report["checks"]]), hide_index=True,
                         width="stretch")
        md = run_dir / "evidence.md"
        if md.exists():
            with st.expander("Evidence document", expanded=False):
                st.markdown(md.read_text(encoding="utf-8"))

# ------------------------------------------------------------------ results
with tabs[5]:
    results = (ROOT / "experiments" / "RESULTS.md").read_text(encoding="utf-8")
    sections = re.split(r"\n(?=## )", results)
    named = {s.splitlines()[0].lstrip("# ").strip(): s for s in sections if s.startswith("## ")}
    choice = st.selectbox("Experiment", list(named))
    st.markdown(named[choice])
    figs = sorted((ROOT / "docs" / "figs").glob("*.png"))
    if figs:
        with st.expander("Project figures"):
            for fig in figs:
                st.image(str(fig), caption=fig.name)
