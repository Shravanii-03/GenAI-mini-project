import random
import copy
from enum import Enum


class AttackType(Enum):
    NONE = "none"
    CAN_SPOOFING = "can_spoofing"
    DELAY_INJECTION = "delay_injection"
    SPEED_SPOOFING = "speed_spoofing"


class AttackInjector:

    def __init__(self, attack_probability=0.25):
        self.attack_probability = attack_probability
        self.last_attack = None

        print(f"[AttackInjector] Ready — attack probability: {attack_probability*100:.0f}%")


    def _should_attack(self, frame):
        return random.random() < self.attack_probability


    def _can_spoofing(self, frame):
        attacked = copy.deepcopy(frame)

        fake_speed = random.randint(5, 30)
        attacked["speed"] = fake_speed

        description = f"CAN Spoofing — fake speed injected: {fake_speed} km/h"

        return attacked, description


    def _delay_injection(self, frame):
        attacked = copy.deepcopy(frame)

        delay_increase = random.randint(30, 120)
        attacked["delay_ms"] += delay_increase

        description = f"Delay Injection — added {delay_increase} ms"

        return attacked, description


    def _speed_spoofing(self, frame):
        attacked = copy.deepcopy(frame)

        fake_speed = frame["speed"] + random.choice([-20, 40])
        fake_speed = max(0, fake_speed)

        attacked["speed"] = fake_speed

        description = f"Speed Spoofing — fake speed {fake_speed} km/h"

        return attacked, description


    def inject(self, frame):

        if not self._should_attack(frame):
            frame["attack"] = {"active": False}
            return frame

        attack_type = random.choice([
            AttackType.CAN_SPOOFING,
            AttackType.DELAY_INJECTION,
            AttackType.SPEED_SPOOFING
        ])

        handlers = {
            AttackType.CAN_SPOOFING: self._can_spoofing,
            AttackType.DELAY_INJECTION: self._delay_injection,
            AttackType.SPEED_SPOOFING: self._speed_spoofing
        }

        attacked_frame, description = handlers[attack_type](frame)

        attacked_frame["attack"] = {
            "active": True,
            "type": attack_type.value,
            "description": description
        }

        print(f"[AttackInjector] {attack_type.value.upper()} → {description}")

        return attacked_frame


# GLOBAL WRAPPER
_injector = None

def inject_attack(frame):
    global _injector

    if _injector is None:
        _injector = AttackInjector()

    return _injector.inject(frame)