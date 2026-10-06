"""Render an evidence bundle (and its audit) as a GSN-style Markdown document."""


def render_markdown(bundle: dict, report: dict = None) -> str:
    req, spec, vio, thr, mit = (bundle[k] for k in ("requirement", "spec", "violation", "threat", "mitigation"))
    rec, pat, ver = vio["recorded"], thr["kb_pattern"], mit["verification"]
    mark = {c["name"]: ("PASS" if c["passed"] else "FAIL") for c in (report or {"checks": []})["checks"]}
    tick = lambda name: f" [{mark[name]}]" if name in mark else ""
    lines = [
        f"# Evidence bundle: {req.get('id', 'requirement')}",
        "",
        f"**G1.** The vehicle meets: *{req['text']}* (extracted by {req.get('method', 'unknown')})",
        "",
        "## S1. Specification",
        f"- Deadline {spec['deadline_ms']} ms; formula `{spec['formula']}`"
        f"{tick('spec_formula_parses')}{tick('spec_bound_matches_deadline')}",
        "",
        "## S2. Counter-example found by the red team",
        f"- Attack `{vio['attack']['family']}` with parameters {vio['attack']['params']}",
        f"- Scenario {vio['scenario']}, seed {vio['seed']}",
        f"- Recorded: latency {rec['e2e_latency_ms']:.1f} ms, robustness {rec['robustness_ms']:.1f} ms, "
        f"collision={rec['collision']}, latest safe latency {rec['latest_safe_latency_ms']:.1f} ms"
        f"{tick('violation_reproduces')}{tick('violation_is_real')}",
        "",
        "## S3. Threat",
        f"- Family `{thr['family']}`; attacker capability: {thr['capability']}{tick('attack_is_known')}",
        f"- Knowledge-base pattern {pat['id']} *{pat['name']}* (severity {pat['severity']}, "
        f"likelihood {pat['likelihood']}, TARA risk {pat['tara_risk_score']}); KB mitigation: {pat['mitigation']}"
        f"{tick('kb_pattern_matches_the_knowledge_base')}",
        "",
        "## S4. Mitigation",
        f"- Monitor rule `{mit['rule']}`{tick('rule_is_valid')}",
        f"- Verified false-alarm rate {ver['fpr']:.3f} (cap {ver['fpr_cap']}), turns {ver['new_timely']} missed "
        f"hazard(s) into in-time detections{tick('rule_fpr_reproduces')}{tick('rule_catches_the_violation_in_time')}",
        "",
        "## Residual risk",
    ]
    residual = bundle.get("residual_risk") or {}
    lines += [f"- `{fam}`: {info}" for fam, info in residual.items()] or ["- none recorded"]
    if report:
        lines += ["", f"## Audit: {report['passed']}/{report['total']} checks re-verified "
                      f"(coverage {report['coverage']:.0%})"]
        lines += [f"- {c['name']}: {'PASS' if c['passed'] else 'FAIL'} - {c['detail']}" for c in report["checks"]]
    lines += ["", "*Machine-checked consistency on an emulated system; not a certified safety case.*"]
    return "\n".join(lines)
