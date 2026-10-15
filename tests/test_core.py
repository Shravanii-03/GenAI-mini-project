"""
tests/test_core.py — Unit tests for SDV Safety System
Run: pytest tests/ -v
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ── RL Tests ──────────────────────────────────────────────────────────────────
class TestQLearning:

    def test_agent_initializes(self):
        from simulator_rl import QLearningAgent
        agent = QLearningAgent()
        assert agent.step_count == 0
        assert agent.epsilon == 0.30

    def test_state_encoding(self):
        from simulator_rl import QLearningAgent
        agent = QLearningAgent()
        state = agent._state(120.0, "dry", 50.0)
        assert state == (6, 0, 2)   # 120//20=6, dry=0, 50//25=2

    def test_reward_violation(self):
        from simulator_rl import QLearningAgent
        agent = QLearningAgent()
        r = agent._reward(150, 100, True, 1.8, False)
        assert r == -2.5   # critical violation

    def test_reward_safe(self):
        from simulator_rl import QLearningAgent
        agent = QLearningAgent()
        r = agent._reward(80, 100, False, 0.8, False)
        assert r > 1.0   # safe with margin bonus

    def test_q_table_updates(self):
        from simulator_rl import QLearningAgent
        agent = QLearningAgent(epsilon=0.0)
        next_delay, idx = agent.suggest_next_delay(120, "dry", 50, 100)
        agent.update(120, "dry", 50, idx, True, 1.5, False, next_delay, 100)
        assert agent.step_count == 1
        assert len(agent.q_table) > 0

    def test_epsilon_decays(self):
        from simulator_rl import QLearningAgent
        agent = QLearningAgent(epsilon=0.30)
        for _ in range(10):
            nd, idx = agent.suggest_next_delay(100, "dry", 50, 100)
            agent.update(100, "dry", 50, idx, False, 1.0, False, nd, 100)
        assert agent.epsilon < 0.30

    def test_run_simulation_api(self):
        from simulator_rl import run_simulation
        result = run_simulation({
            "delay": 120, "max_delay": 100,
            "road_condition": "dry", "cpu_load": 50,
            "violation": True, "risk_score": 1.5, "attacked": False
        })
        assert "next_delay" in result
        assert "rl_reward" in result
        assert "rl_epsilon" in result
        assert result["violation"] == 1


# ── RAG Tests ─────────────────────────────────────────────────────────────────
class TestRAGEngine:

    def test_retrieve_iso(self):
        from rag_engine import retrieve
        results = retrieve("brake timing", "iso", top_k=2)
        assert isinstance(results, list)

    def test_retrieve_attack(self):
        from rag_engine import retrieve
        results = retrieve("can spoofing delay", "attack", top_k=2)
        assert isinstance(results, list)

    def test_context_not_empty(self):
        from rag_engine import get_context_for_llm
        ctx = get_context_for_llm("emergency brake")
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_tfidf_score(self):
        from rag_engine import _tfidf_score, _tokenize
        q = _tokenize("brake timing")
        d = _tokenize("brake timing ISO 26262 latency")
        corpus = [d, _tokenize("steering wheel angle")]
        score = _tfidf_score(q, d, corpus)
        assert score > 0


# ── Vehicle Simulator Tests ───────────────────────────────────────────────────
class TestVehicleSimulator:

    def test_tick_returns_dict(self):
        from vehicle_simulator import VehicleSimulator
        sim = VehicleSimulator()
        frame = sim.tick()
        assert isinstance(frame, dict)

    def test_frame_has_required_keys(self):
        from vehicle_simulator import VehicleSimulator
        sim = VehicleSimulator()
        frame = sim.tick()
        required = ["speed", "delay_ms", "mode", "road_condition",
                    "cpu_load", "event_chain", "vehicle_speed",
                    "brake_pedal_position", "iso_violation_detected"]
        for key in required:
            assert key in frame, f"Missing key: {key}"

    def test_event_chain_has_4_steps(self):
        from vehicle_simulator import VehicleSimulator
        sim = VehicleSimulator()
        frame = sim.tick()
        assert len(frame["event_chain"]) == 4

    def test_normal_driving_delay_under_100ms(self):
        from vehicle_simulator import VehicleSimulator
        sim = VehicleSimulator()
        # Skip startup phase
        for _ in range(25):
            sim.tick()
        # Now in normal_driving — delays should be mostly under 100ms
        delays = [sim.tick()["delay_ms"] for _ in range(20)]
        under = sum(1 for d in delays if d < 100)
        assert under >= 12, f"Too many violations in normal driving: {delays}"

    def test_frame_id_increments(self):
        from vehicle_simulator import VehicleSimulator
        sim = VehicleSimulator()
        f1 = sim.tick()
        f2 = sim.tick()
        assert f2["frame_id"] == f1["frame_id"] + 1


# ── Attack Injector Tests ─────────────────────────────────────────────────────
class TestAttackInjector:

    def _dummy_frame(self):
        return {
            "speed": 60.0, "delay_ms": 80,
            "mode": "normal_driving", "road_condition": "dry",
            "cpu_load": 50, "event_chain": [],
            "attack": {"active": False}
        }

    def test_inject_returns_dict(self):
        from attack_injector import inject_attack
        frame = inject_attack(self._dummy_frame())
        assert isinstance(frame, dict)
        assert "attack" in frame

    def test_attack_modifies_frame(self):
        from attack_injector import AttackInjector
        inj = AttackInjector(attack_probability=1.0)  # always attack
        frame = inj.inject(self._dummy_frame())
        assert frame["attack"]["active"] is True

    def test_no_attack_leaves_frame_intact(self):
        from attack_injector import AttackInjector
        inj = AttackInjector(attack_probability=0.0)  # never attack
        frame = inj.inject(self._dummy_frame())
        assert frame["attack"]["active"] is False
        assert frame["speed"] == 60.0


# ── Reasoning Engine Tests ────────────────────────────────────────────────────
class TestReasoningEngine:

    def _parsed(self):
        return {"max_delay_ms": 100, "event": "brake",
                "component": "brake_ecu", "iso_standard": "ISO 26262"}

    def _scenario(self, delay, road="dry", cpu=50):
        return {
            "actual_delay_ms": delay,
            "type": "normal",
            "parameters": {"road_condition": road, "ecu_cpu_load_pct": cpu},
            "event_chain_timing": [
                {"step": "sense", "time_ms": 10},
                {"step": "actuate", "time_ms": delay}
            ]
        }

    def test_no_violation_under_limit(self):
        from reasoning_engine import evaluate_scenario
        ev = evaluate_scenario(self._parsed(), self._scenario(80))
        assert ev["violation"] is False

    def test_violation_over_limit(self):
        from reasoning_engine import evaluate_scenario
        ev = evaluate_scenario(self._parsed(), self._scenario(150))
        assert ev["violation"] is True

    def test_risk_increases_with_delay(self):
        from reasoning_engine import evaluate_scenario
        ev_low  = evaluate_scenario(self._parsed(), self._scenario(80))
        ev_high = evaluate_scenario(self._parsed(), self._scenario(150))
        assert ev_high["risk_score"] > ev_low["risk_score"]

    def test_icy_road_increases_risk(self):
        from reasoning_engine import evaluate_scenario
        ev_dry = evaluate_scenario(self._parsed(), self._scenario(110, road="dry"))
        ev_icy = evaluate_scenario(self._parsed(), self._scenario(110, road="icy"))
        assert ev_icy["risk_score"] > ev_dry["risk_score"]

    def test_severity_critical_at_high_risk(self):
        from reasoning_engine import evaluate_scenario
        ev = evaluate_scenario(self._parsed(), self._scenario(200, road="icy", cpu=90))
        assert ev["severity"] in ("CRITICAL", "HIGH")


# ── Prompt Templates Tests ────────────────────────────────────────────────────
class TestPromptTemplates:

    def test_parse_prompt_has_requirement(self):
        from prompt_templates import get_requirement_parse_prompt
        p = get_requirement_parse_prompt("Brake within 100ms")
        assert "Brake within 100ms" in p
        assert "JSON" in p

    def test_threat_prompt_has_severity_rules(self):
        from prompt_templates import get_threat_reasoning_prompt
        parsed   = {"max_delay_ms": 100, "event": "brake", "component": "ecu"}
        scenario = {"actual_delay_ms": 150,
                    "parameters": {"road_condition": "dry", "ecu_cpu_load_pct": 50}}
        evaluation = {"risk_score": 1.8, "severity": "CRITICAL"}
        p = get_threat_reasoning_prompt(parsed, scenario, evaluation)
        assert "CRITICAL" in p
        assert "1.5" in p   # severity threshold

    def test_timing_prompt_has_asil_levels(self):
        from prompt_templates import get_timing_extraction_prompt
        p = get_timing_extraction_prompt("Brake within 100ms", "ISO context")
        assert "ASIL-D" in p
        assert "100ms" in p


# ── Memory Tests ──────────────────────────────────────────────────────────────
class TestMemory:

    def test_store_and_retrieve(self):
        from memory import AgentMemory
        mem = AgentMemory()
        scenario   = {"type": "normal", "parameters": {"road_condition": "dry", "ecu_cpu_load_pct": 50}}
        evaluation = {"actual_delay_ms": 80, "violation": False, "risk_score": 0.8, "bottleneck_step": None}
        threat     = {"severity": "LOW"}
        mem.store(scenario, evaluation, threat)
        assert len(mem.get_history()) == 1

    def test_violation_tracked(self):
        from memory import AgentMemory
        mem = AgentMemory()
        scenario   = {"type": "stress", "parameters": {"road_condition": "icy", "ecu_cpu_load_pct": 80}}
        evaluation = {"actual_delay_ms": 150, "violation": True, "risk_score": 1.8, "bottleneck_step": None}
        threat     = {"severity": "CRITICAL"}
        mem.store(scenario, evaluation, threat)
        summary = mem.summary()
        assert summary["total_violations"] == 1
        assert summary["critical_violations"] == 1

    def test_summary_rates(self):
        from memory import AgentMemory
        mem = AgentMemory()
        for i in range(4):
            viol = i < 2
            mem.store(
                {"type": "t", "parameters": {"road_condition": "dry", "ecu_cpu_load_pct": 50}},
                {"actual_delay_ms": 150 if viol else 80, "violation": viol,
                 "risk_score": 1.5 if viol else 0.8, "bottleneck_step": None},
                {"severity": "HIGH" if viol else "LOW"}
            )
        s = mem.summary()
        assert s["violation_rate_pct"] == 50.0