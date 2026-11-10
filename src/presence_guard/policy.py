"""Which factors are proved, and is the policy satisfied?

The policy is deliberately about *counts*, not a fixed AND-chain:

    password (always required) + at least N of {fingerprint, phone, face}

so "password + phone + fingerprint" and "password + face + fingerprint" are
both valid without the policy having to enumerate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FACTORS = ("password", "fingerprint", "phone", "face")


@dataclass
class FactorState:
    """What each factor currently proves. Nothing here locks anything."""

    password: bool = False
    fingerprint: bool = False
    phone: bool = False
    face: bool = False
    phone_meters: float | None = None
    face_similarity: float | None = None
    face_threshold: float | None = None
    notes: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "password": self.password,
            "fingerprint": self.fingerprint,
            "phone": self.phone,
            "face": self.face,
            "phone_meters": self.phone_meters,
            "face_similarity": self.face_similarity,
            "face_threshold": self.face_threshold,
            "notes": self.notes,
        }


@dataclass
class Policy:
    require_password: bool = True
    required_secondary: int = 2

    def evaluate(self, state: FactorState) -> dict:
        secondary = {
            "fingerprint": state.fingerprint,
            "phone": state.phone,
            "face": state.face,
        }
        proved = [name for name, ok in secondary.items() if ok]
        missing_password = self.require_password and not state.password
        satisfied = (not missing_password) and len(proved) >= self.required_secondary
        return {
            "satisfied": satisfied,
            "require_password": self.require_password,
            "required_secondary": self.required_secondary,
            "proved": proved,
            "missing": [n for n, ok in secondary.items() if not ok],
            "missing_password": missing_password,
        }

    def matrix(self) -> list[str]:
        """Human-readable list of the combinations that unlock."""
        out = []
        combos = [
            ("phone", "fingerprint"),
            ("phone", "face"),
            ("fingerprint", "face"),
            ("phone", "fingerprint", "face"),
        ]
        for combo in combos:
            if len(combo) >= self.required_secondary:
                prefix = "password + " if self.require_password else ""
                out.append(prefix + " + ".join(combo))
        return out
