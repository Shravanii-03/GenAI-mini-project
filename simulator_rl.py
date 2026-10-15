"""
simulator_rl.py — Q-Learning based Adaptive RL for SDV Safety
==============================================================
Proper reinforcement learning that actually LEARNS from violations.

State  : (delay_bucket, road_condition, cpu_load_bucket)
Actions: adjust delay target by [-20, -10, 0, +10, +20] ms
Reward : +1 safe, -1 violation, -2 critical violation
Policy : epsilon-greedy Q-learning with decay
"""

import random

import json
from pathlib import Path

# ── Q-Table ───────────────────────────────────────────────────────────────────
ACTIONS      = [-20, -10, 0, 10, 20]   # ms adjustments
ROAD_MAP     = {"dry": 0, "wet": 1, "icy": 2, "foggy": 2}
Q_TABLE_FILE = "rl_qtable.json"

class QLearningAgent:
    """
    State: (delay_bucket, road_bucket, cpu_bucket)
      delay_bucket : delay // 20  (0=0-19ms, 1=20-39ms ... 10=200ms+)
      road_bucket  : 0=dry, 1=wet, 2=icy/foggy
      cpu_bucket   : cpu_load // 25  (0=0-24%, 1=25-49%, 2=50-74%, 3=75-100%)

    Action: index into ACTIONS list
    """

    def __init__(
        self,
        alpha: float = 0.15,     # learning rate
        gamma: float = 0.90,     # discount factor
        epsilon: float = 0.30,   # initial exploration rate
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
    ):
        self.alpha         = alpha
        self.gamma         = gamma
        self.epsilon       = epsilon
        self.epsilon_min   = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.q_table       = {}   # (state_tuple) → [q_val per action]
        self.step_count    = 0
        self.total_reward  = 0.0
        self.violations    = 0
        self.episode_log   = []   # track learning history

    # ── State encoding ─────────────────────────────────────────────────────────
    def _state(self, delay_ms: float, road: str, cpu_load: float) -> tuple:
        delay_b = min(int(delay_ms) // 20, 10)
        road_b  = ROAD_MAP.get(road, 0)
        cpu_b   = min(int(cpu_load) // 25, 3)
        return (delay_b, road_b, cpu_b)

    def _get_q(self, state: tuple) -> list:
        if state not in self.q_table:
            self.q_table[state] = [0.0] * len(ACTIONS)
        return self.q_table[state]

    # ── Action selection (epsilon-greedy) ─────────────────────────────────────
    def choose_action(self, delay_ms: float, road: str, cpu_load: float) -> int:
        state = self._state(delay_ms, road, cpu_load)
        if random.random() < self.epsilon:
            return random.randrange(len(ACTIONS))   # explore
        q = self._get_q(state)
        return q.index(max(q))                      # exploit

    # ── Reward function ────────────────────────────────────────────────────────
    def _reward(self, delay_ms: float, max_delay: float,
                 violation: bool, risk_score: float, attacked: bool) -> float:
        if not violation:
            margin = (max_delay - delay_ms) / max_delay
            return 1.0 + margin * 0.5      # bonus for larger safety margin
        else:
            if risk_score >= 1.5:
                return -2.5                # critical violation
            elif attacked:
                return -1.5                # attack-induced violation
            else:
                return -1.0               # normal violation

    # ── Q-table update (Bellman equation) ─────────────────────────────────────
    def update(
        self,
        delay_ms:   float,
        road:       str,
        cpu_load:   float,
        action_idx: int,
        violation:  bool,
        risk_score: float,
        attacked:   bool,
        next_delay: float,
        max_delay:  float,
    ) -> float:
        state      = self._state(delay_ms, road, cpu_load)
        next_state = self._state(next_delay, road, cpu_load)

        reward = self._reward(delay_ms, max_delay, violation, risk_score, attacked)
        self.total_reward += reward
        if violation:
            self.violations += 1

        q_now  = self._get_q(state)
        q_next = self._get_q(next_state)

        # Bellman update
        old_val = q_now[action_idx]
        new_val = old_val + self.alpha * (
            reward + self.gamma * max(q_next) - old_val
        )
        q_now[action_idx] = new_val

        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        self.step_count += 1

        self.episode_log.append({
            "step":       self.step_count,
            "delay_ms":   delay_ms,
            "action":     ACTIONS[action_idx],
            "reward":     round(reward, 3),
            "violation":  violation,
            "epsilon":    round(self.epsilon, 4),
            "q_updated":  round(new_val, 4),
        })

        return reward

    # ── Suggest next delay ─────────────────────────────────────────────────────
    def suggest_next_delay(
        self,
        current_delay: float,
        road: str,
        cpu_load: float,
        max_delay: float,
    ) -> float:
        action_idx  = self.choose_action(current_delay, road, cpu_load)
        delta       = ACTIONS[action_idx]
        next_delay  = max(0.0, current_delay + delta)
        return next_delay, action_idx

    # ── Stats ──────────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        return {
            "steps":         self.step_count,
            "total_reward":  round(self.total_reward, 2),
            "violations":    self.violations,
            "epsilon":       round(self.epsilon, 4),
            "q_states":      len(self.q_table),
            "avg_reward":    round(self.total_reward / max(self.step_count, 1), 3),
        }

    # ── Persistence ────────────────────────────────────────────────────────────
    def save(self, path: str = Q_TABLE_FILE):
        data = {
            "q_table":     {str(k): v for k, v in self.q_table.items()},
            "epsilon":     self.epsilon,
            "step_count":  self.step_count,
            "total_reward":self.total_reward,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self, path: str = Q_TABLE_FILE):
        if not Path(path).exists():
            return
        with open(path) as f:
            data = json.load(f)
        self.q_table     = {eval(k): v for k, v in data.get("q_table", {}).items()}
        self.epsilon     = data.get("epsilon", self.epsilon)
        self.step_count  = data.get("step_count", 0)
        self.total_reward= data.get("total_reward", 0.0)


# ── Global agent instance (singleton for realtime_monitor) ───────────────────
_agent = QLearningAgent()
_agent.load()   # load saved Q-table if exists

def get_agent() -> QLearningAgent:
    return _agent


# ── Backward-compatible API (used by realtime_monitor.py) ────────────────────

def simulate(delay: float, max_delay: float) -> dict:
    violation   = delay > max_delay
    delay_score = round(delay / max_delay, 2) if max_delay > 0 else 0
    return {
        "actual_delay":  delay,
        "violation":     1 if violation else 0,
        "delay_score":   delay_score,
    }


def run_simulation(input_data: dict) -> dict:
    """
    Drop-in replacement for old run_simulation().
    Now uses Q-learning agent internally.
    """
    delay     = input_data.get("delay", 100)
    max_delay = input_data.get("max_delay", 100)
    road      = input_data.get("road_condition", "dry")
    cpu_load  = input_data.get("cpu_load", 50)
    violation = input_data.get("violation", delay > max_delay)
    risk      = input_data.get("risk_score", delay / max_delay)
    attacked  = input_data.get("attacked", False)

    sim = simulate(delay, max_delay)

    # Q-agent picks next delay
    next_delay, action_idx = _agent.suggest_next_delay(delay, road, cpu_load, max_delay)

    # Update Q-table
    reward = _agent.update(
        delay_ms   = delay,
        road       = road,
        cpu_load   = cpu_load,
        action_idx = action_idx,
        violation  = bool(violation),
        risk_score = risk,
        attacked   = attacked,
        next_delay = next_delay,
        max_delay  = max_delay,
    )

    # Periodically save Q-table
    if _agent.step_count % 50 == 0:
        _agent.save()

    return {
        "input_delay":   delay,
        "actual_delay":  sim["actual_delay"],
        "violation":     sim["violation"],
        "delay_score":   sim["delay_score"],
        "next_delay":    next_delay,
        "rl_action_ms":  ACTIONS[action_idx],
        "rl_reward":     round(reward, 3),
        "rl_epsilon":    round(_agent.epsilon, 4),
        "rl_q_states":   len(_agent.q_table),
        "rl_steps":      _agent.step_count,
    }


def apply_adaptive_learning(agent1_output: dict, steps_per_scenario: int = 3) -> list:
    """Used by Agent1 / integrated pipeline."""
    max_delay = agent1_output.get("max_delay_ms", 100)
    scenarios = agent1_output.get("scenarios", [])
    results   = []

    for scenario in scenarios:
        delay = scenario.get("delay_ms", scenario.get("actual_delay_ms", 0))
        road  = scenario.get("parameters", {}).get("road_condition", "dry")
        cpu   = scenario.get("parameters", {}).get("ecu_cpu_load_pct", 50)

        for step in range(steps_per_scenario):
            result = run_simulation({
                "delay": delay, "max_delay": max_delay,
                "road_condition": road, "cpu_load": cpu,
            })
            results.append({
                "scenario_type": scenario.get("type"),
                "original_delay": delay,
                "iteration": step + 1,
                **result
            })
            delay = result["next_delay"]

    return results