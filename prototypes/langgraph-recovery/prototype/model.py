from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any


THREAD_NAMESPACE = uuid.UUID("f0a2796d-5080-48de-b7bf-1cd4513bfcd8")


class PrototypeInvariantError(RuntimeError):
    """Raised when an accepted boundary invariant is violated."""


class SimulatedResponseLoss(RuntimeError):
    """The remote side committed, but its response did not arrive."""


class StaleGenerationRejected(RuntimeError):
    """A non-current generation attempted a business side effect."""


def stable_thread_id(generation_id: str) -> str:
    return str(uuid.uuid5(THREAD_NAMESPACE, generation_id))


def stable_effect_key(generation_id: str) -> str:
    return f"investigation-result:{generation_id}"


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ScenarioResult:
    scenario: str
    passed: bool
    evidence: dict[str, Any]
