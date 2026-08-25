import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast


class InvestigationCapability(StrEnum):
    CONFIRM_ORDER = "CONFIRM_ORDER"
    READ_LOGISTICS = "READ_LOGISTICS"
    READ_PAYMENT_AND_REFUNDS = "READ_PAYMENT_AND_REFUNDS"
    READ_COMPENSATION_AND_PENDING_ACTIONS = "READ_COMPENSATION_AND_PENDING_ACTIONS"
    READ_APPLICABLE_POLICY = "READ_APPLICABLE_POLICY"


CAPABILITY_PARAMETER_NAMES: dict[InvestigationCapability, tuple[str, ...]] = {
    InvestigationCapability.CONFIRM_ORDER: (),
    InvestigationCapability.READ_LOGISTICS: ("orderReference",),
    InvestigationCapability.READ_PAYMENT_AND_REFUNDS: ("orderReference",),
    InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS: ("orderReference",),
    InvestigationCapability.READ_APPLICABLE_POLICY: ("orderReference",),
}


class TerminalAction(StrEnum):
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
    SUBMIT_CONCLUSION = "SUBMIT_CONCLUSION"
    HANDOFF = "HANDOFF"


ActionKind = InvestigationCapability | TerminalAction


class ActionLoopFailureCode(StrEnum):
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
    REPEATED_NO_PROGRESS = "REPEATED_NO_PROGRESS"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    TOOL_FAILURE = "TOOL_FAILURE"
    INVALID_TOOL_RESPONSE = "INVALID_TOOL_RESPONSE"


@dataclass(frozen=True)
class ActionUsage:
    tokens: int = 0
    cost_micros: int = 0
    provider_attempts: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.tokens) is not int
            or self.tokens < 0
            or type(self.cost_micros) is not int
            or self.cost_micros < 0
            or type(self.provider_attempts) is not int
            or self.provider_attempts < 1
        ):
            raise ValueError("action usage must contain non-negative integer consumption")


@dataclass(frozen=True)
class InvestigationAction:
    kind: ActionKind
    parameters: tuple[tuple[str, str], ...] = ()

    @property
    def parameter_map(self) -> dict[str, str]:
        return dict(self.parameters)


@dataclass(frozen=True)
class ActionDecision:
    action: InvestigationAction
    usage: ActionUsage = ActionUsage()

    @classmethod
    def from_values(
        cls, kind: ActionKind | str, parameters: dict[str, str], usage: ActionUsage
    ) -> "ActionDecision":
        try:
            controlled_kind: ActionKind = InvestigationCapability(kind)
        except ValueError:
            try:
                controlled_kind = TerminalAction(kind)
            except ValueError as error:
                raise ActionLoopFailure(ActionLoopFailureCode.UNKNOWN_ACTION) from error
        expected = (
            set(CAPABILITY_PARAMETER_NAMES[controlled_kind])
            if isinstance(controlled_kind, InvestigationCapability)
            else set()
        )
        if set(parameters) != expected or not all(
            isinstance(value, str) and value for value in parameters.values()
        ):
            raise ActionLoopFailure(ActionLoopFailureCode.UNKNOWN_ACTION)
        return cls(InvestigationAction(controlled_kind, tuple(sorted(parameters.items()))), usage)


@dataclass(frozen=True)
class ActionBudget:
    max_actions: int = 8
    max_wall_clock_ms: int = 30_000
    max_tokens: int = 4_000
    max_cost_micros: int = 100_000
    max_provider_attempts: int = 8
    max_repeated_actions: int = 0

    @classmethod
    def configured(cls) -> "ActionBudget":
        return cls(
            max_actions=_bounded("AGENT_INVESTIGATION_MAX_ACTIONS", 8, 1, 32),
            max_wall_clock_ms=_bounded("AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS", 30_000, 1, 300_000),
            max_tokens=_bounded("AGENT_INVESTIGATION_MAX_TOKENS", 4_000, 0, 1_000_000),
            max_cost_micros=_bounded(
                "AGENT_INVESTIGATION_MAX_COST_MICROS", 100_000, 0, 100_000_000
            ),
            max_provider_attempts=_bounded("AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS", 8, 1, 32),
            max_repeated_actions=_bounded("AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS", 0, 0, 3),
        )


@dataclass(frozen=True)
class ActionRecord:
    action_type: str
    evidence_references: tuple[str, ...]
    result_code: str


@dataclass(frozen=True)
class ActionModelCallRecord:
    call_number: int
    selected_action: str
    provider_attempts: int
    tokens: int
    cost_micros: int


class ActionLoopFailure(Exception):
    def __init__(
        self,
        code: ActionLoopFailureCode,
        facts: dict | None = None,
        records: tuple[ActionRecord, ...] = (),
        provider_attempts: int = 0,
        model_calls: tuple[ActionModelCallRecord, ...] = (),
    ) -> None:
        self.code = code
        self.facts = dict(facts or {})
        self.records = records
        self.provider_attempts = provider_attempts
        self.model_calls = model_calls
        super().__init__(code.value)


@dataclass(frozen=True)
class ActionLoopResult:
    terminal_action: TerminalAction
    facts: dict
    records: tuple[ActionRecord, ...]
    tokens: int
    cost_micros: int
    provider_attempts: int
    model_calls: tuple[ActionModelCallRecord, ...]


@dataclass(frozen=True)
class ActionLoopContinuation:
    checkpoint: dict[str, object]


@dataclass
class _ActionLoopProgress:
    facts: dict
    records: list[ActionRecord]
    model_calls: list[ActionModelCallRecord]
    seen: dict[InvestigationAction, int]
    tokens: int
    cost_micros: int
    provider_attempts: int
    remaining_actions: int
    remaining_wall_clock_ms: int
    remaining_tokens: int
    remaining_cost_micros: int
    remaining_provider_attempts: int


class DeterministicActionModel:
    async def choose(self, facts: dict) -> ActionDecision:
        if "matchStatus" not in facts:
            return _decision(InvestigationCapability.CONFIRM_ORDER)
        if facts["matchStatus"] == "AMBIGUOUS":
            return _decision(TerminalAction.REQUEST_CLARIFICATION)
        reference = facts.get("orderReference")
        if not isinstance(reference, str) or not reference:
            return _decision(TerminalAction.HANDOFF)
        for field, kind in (
            ("delaySeconds", InvestigationCapability.READ_LOGISTICS),
            ("paid", InvestigationCapability.READ_PAYMENT_AND_REFUNDS),
            (
                "existingCompensation",
                InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS,
            ),
            ("policyVersion", InvestigationCapability.READ_APPLICABLE_POLICY),
        ):
            if field not in facts:
                return _decision(kind, {"orderReference": reference})
        return _decision(TerminalAction.SUBMIT_CONCLUSION)


class InvestigationActionModel(Protocol):
    async def choose(self, facts: dict) -> ActionDecision: ...


class ActionLoop:
    def __init__(
        self,
        choose: Callable[[dict], Awaitable[ActionDecision]],
        budget: ActionBudget,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._choose = choose
        self._budget = budget
        self._clock = clock

    async def run(
        self, execute: Callable[[InvestigationAction], Awaitable[dict]]
    ) -> ActionLoopResult:
        checkpoint: dict[str, object] | None = None
        while True:
            advanced = await self.advance(checkpoint, execute)
            if isinstance(advanced, ActionLoopResult):
                return advanced
            checkpoint = advanced.checkpoint

    async def advance(
        self,
        checkpoint: dict[str, object] | None,
        execute: Callable[[InvestigationAction], Awaitable[dict]],
    ) -> ActionLoopContinuation | ActionLoopResult:
        progress = _load_progress(checkpoint, self._budget)
        if progress.remaining_actions <= 0 or progress.remaining_provider_attempts <= 0:
            raise self._progress_failure(ActionLoopFailureCode.BUDGET_EXHAUSTED, progress)
        step_started = self._clock()
        try:
            async with asyncio.timeout(progress.remaining_wall_clock_ms / 1000):
                decision = await self._choose(dict(progress.facts))
        except TimeoutError as error:
            raise self._progress_failure(
                ActionLoopFailureCode.BUDGET_EXHAUSTED, progress
            ) from error
        except ActionLoopFailure as error:
            failed_calls = list(progress.model_calls)
            if error.provider_attempts > 0:
                failed_calls.append(
                    ActionModelCallRecord(
                        call_number=len(failed_calls) + 1,
                        selected_action="",
                        provider_attempts=error.provider_attempts,
                        tokens=0,
                        cost_micros=0,
                    )
                )
            progress.model_calls = failed_calls
            progress.provider_attempts += error.provider_attempts
            raise self._progress_failure(error.code, progress) from error
        except Exception as error:
            raise self._progress_failure(ActionLoopFailureCode.UNKNOWN_ACTION, progress) from error
        if not isinstance(decision, ActionDecision):
            raise self._progress_failure(ActionLoopFailureCode.UNKNOWN_ACTION, progress)

        progress.remaining_actions -= 1
        progress.tokens += decision.usage.tokens
        progress.cost_micros += decision.usage.cost_micros
        progress.provider_attempts += decision.usage.provider_attempts
        progress.remaining_tokens -= decision.usage.tokens
        progress.remaining_cost_micros -= decision.usage.cost_micros
        progress.remaining_provider_attempts -= decision.usage.provider_attempts
        progress.model_calls.append(
            ActionModelCallRecord(
                call_number=len(progress.model_calls) + 1,
                selected_action=decision.action.kind.value,
                provider_attempts=decision.usage.provider_attempts,
                tokens=decision.usage.tokens,
                cost_micros=decision.usage.cost_micros,
            )
        )
        if (
            progress.remaining_tokens < 0
            or progress.remaining_cost_micros < 0
            or progress.remaining_provider_attempts < 0
        ):
            raise self._progress_failure(ActionLoopFailureCode.BUDGET_EXHAUSTED, progress)
        repeats = progress.seen.get(decision.action, 0)
        if repeats > self._budget.max_repeated_actions:
            raise self._progress_failure(ActionLoopFailureCode.REPEATED_NO_PROGRESS, progress)
        progress.seen[decision.action] = repeats + 1
        progress.remaining_wall_clock_ms -= round((self._clock() - step_started) * 1000)
        if progress.remaining_wall_clock_ms <= 0:
            raise self._progress_failure(ActionLoopFailureCode.BUDGET_EXHAUSTED, progress)
        if isinstance(decision.action.kind, TerminalAction):
            progress.records.append(ActionRecord(decision.action.kind.value, (), "SELECTED"))
            return ActionLoopResult(
                decision.action.kind,
                progress.facts,
                tuple(progress.records),
                progress.tokens,
                progress.cost_micros,
                progress.provider_attempts,
                tuple(progress.model_calls),
            )
        try:
            tool_started = self._clock()
            async with asyncio.timeout(progress.remaining_wall_clock_ms / 1000):
                result = await execute(decision.action)
        except TimeoutError as error:
            raise self._progress_failure(
                ActionLoopFailureCode.BUDGET_EXHAUSTED, progress
            ) from error
        except ActionLoopFailure as error:
            raise self._progress_failure(error.code, progress) from error
        except Exception as error:
            raise self._progress_failure(ActionLoopFailureCode.TOOL_FAILURE, progress) from error
        progress.remaining_wall_clock_ms -= round((self._clock() - tool_started) * 1000)
        if progress.remaining_wall_clock_ms <= 0:
            raise self._progress_failure(ActionLoopFailureCode.BUDGET_EXHAUSTED, progress)
        if not isinstance(result, dict):
            raise self._progress_failure(ActionLoopFailureCode.TOOL_FAILURE, progress)
        before = dict(progress.facts)
        progress.facts.update(
            {
                key: value
                for key, value in result.items()
                if key not in {"capability", "evidenceRefs"}
            }
        )
        evidence = result.get("evidenceRefs", [])
        controlled_evidence = (
            tuple(evidence)
            if isinstance(evidence, list) and all(isinstance(value, str) for value in evidence)
            else ()
        )
        progress.records.append(
            ActionRecord(
                decision.action.kind.value,
                controlled_evidence,
                "PROGRESSED" if progress.facts != before else "NO_PROGRESS",
            )
        )
        return ActionLoopContinuation(_dump_progress(progress))

    @staticmethod
    def _progress_failure(
        code: ActionLoopFailureCode, progress: _ActionLoopProgress
    ) -> ActionLoopFailure:
        return ActionLoopFailure(
            code,
            progress.facts,
            tuple(progress.records),
            provider_attempts=progress.provider_attempts,
            model_calls=tuple(progress.model_calls),
        )


_CHECKPOINT_FIELDS = {
    "facts",
    "records",
    "modelCalls",
    "seenActions",
    "tokens",
    "costMicros",
    "providerAttempts",
    "remainingActions",
    "remainingWallClockMs",
    "remainingTokens",
    "remainingCostMicros",
    "remainingProviderAttempts",
}


def _load_progress(
    checkpoint: dict[str, object] | None, budget: ActionBudget
) -> _ActionLoopProgress:
    if checkpoint is None:
        return _ActionLoopProgress(
            facts={},
            records=[],
            model_calls=[],
            seen={},
            tokens=0,
            cost_micros=0,
            provider_attempts=0,
            remaining_actions=budget.max_actions,
            remaining_wall_clock_ms=budget.max_wall_clock_ms,
            remaining_tokens=budget.max_tokens,
            remaining_cost_micros=budget.max_cost_micros,
            remaining_provider_attempts=budget.max_provider_attempts,
        )
    try:
        if set(checkpoint) != _CHECKPOINT_FIELDS:
            raise ValueError
        facts = checkpoint["facts"]
        record_values = checkpoint["records"]
        call_values = checkpoint["modelCalls"]
        seen_values = checkpoint["seenActions"]
        if (
            not isinstance(facts, dict)
            or not isinstance(record_values, list)
            or not isinstance(call_values, list)
            or not isinstance(seen_values, list)
        ):
            raise ValueError
        records = [_record_from_checkpoint(value) for value in record_values]
        model_calls = [_call_from_checkpoint(value) for value in call_values]
        seen = dict(_seen_from_checkpoint(value) for value in seen_values)
        numeric = {
            name: checkpoint[name]
            for name in (
                "tokens",
                "costMicros",
                "providerAttempts",
                "remainingActions",
                "remainingWallClockMs",
                "remainingTokens",
                "remainingCostMicros",
                "remainingProviderAttempts",
            )
        }
        if not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in numeric.values()
        ):
            raise ValueError
        checked_numeric = cast(dict[str, int], numeric)
        if (
            len(records) != len(model_calls)
            or sum(seen.values()) != len(model_calls)
            or checked_numeric["remainingActions"] + len(model_calls) != budget.max_actions
            or checked_numeric["remainingTokens"] + checked_numeric["tokens"] != budget.max_tokens
            or checked_numeric["remainingCostMicros"] + checked_numeric["costMicros"]
            != budget.max_cost_micros
            or checked_numeric["remainingProviderAttempts"] + checked_numeric["providerAttempts"]
            != budget.max_provider_attempts
            or checked_numeric["remainingWallClockMs"] > budget.max_wall_clock_ms
        ):
            raise ValueError
        return _ActionLoopProgress(
            facts=dict(facts),
            records=records,
            model_calls=model_calls,
            seen=seen,
            tokens=checked_numeric["tokens"],
            cost_micros=checked_numeric["costMicros"],
            provider_attempts=checked_numeric["providerAttempts"],
            remaining_actions=checked_numeric["remainingActions"],
            remaining_wall_clock_ms=checked_numeric["remainingWallClockMs"],
            remaining_tokens=checked_numeric["remainingTokens"],
            remaining_cost_micros=checked_numeric["remainingCostMicros"],
            remaining_provider_attempts=checked_numeric["remainingProviderAttempts"],
        )
    except (KeyError, TypeError, ValueError, ActionLoopFailure) as error:
        raise ActionLoopFailure(ActionLoopFailureCode.INVALID_TOOL_RESPONSE) from error


def _dump_progress(progress: _ActionLoopProgress) -> dict[str, object]:
    return {
        "facts": dict(progress.facts),
        "records": [
            {
                "actionType": record.action_type,
                "evidenceReferences": list(record.evidence_references),
                "resultCode": record.result_code,
            }
            for record in progress.records
        ],
        "modelCalls": [
            {
                "callNumber": call.call_number,
                "selectedAction": call.selected_action,
                "providerAttempts": call.provider_attempts,
                "tokens": call.tokens,
                "costMicros": call.cost_micros,
            }
            for call in progress.model_calls
        ],
        "seenActions": [
            {
                "actionType": action.kind.value,
                "parameters": action.parameter_map,
                "count": count,
            }
            for action, count in progress.seen.items()
        ],
        "tokens": progress.tokens,
        "costMicros": progress.cost_micros,
        "providerAttempts": progress.provider_attempts,
        "remainingActions": progress.remaining_actions,
        "remainingWallClockMs": progress.remaining_wall_clock_ms,
        "remainingTokens": progress.remaining_tokens,
        "remainingCostMicros": progress.remaining_cost_micros,
        "remainingProviderAttempts": progress.remaining_provider_attempts,
    }


def _record_from_checkpoint(value: object) -> ActionRecord:
    if not isinstance(value, dict) or set(value) != {
        "actionType",
        "evidenceReferences",
        "resultCode",
    }:
        raise ValueError
    evidence = value["evidenceReferences"]
    if (
        not isinstance(value["actionType"], str)
        or not isinstance(evidence, list)
        or not all(isinstance(item, str) for item in evidence)
        or value["resultCode"] not in {"PROGRESSED", "NO_PROGRESS"}
    ):
        raise ValueError
    InvestigationCapability(value["actionType"])
    return ActionRecord(value["actionType"], tuple(evidence), value["resultCode"])


def _call_from_checkpoint(value: object) -> ActionModelCallRecord:
    if not isinstance(value, dict) or set(value) != {
        "callNumber",
        "selectedAction",
        "providerAttempts",
        "tokens",
        "costMicros",
    }:
        raise ValueError
    for name in ("callNumber", "providerAttempts", "tokens", "costMicros"):
        if not isinstance(value[name], int) or isinstance(value[name], bool) or value[name] < 0:
            raise ValueError
    if not isinstance(value["selectedAction"], str):
        raise ValueError
    InvestigationCapability(value["selectedAction"])
    return ActionModelCallRecord(
        value["callNumber"],
        value["selectedAction"],
        value["providerAttempts"],
        value["tokens"],
        value["costMicros"],
    )


def _seen_from_checkpoint(value: object) -> tuple[InvestigationAction, int]:
    if not isinstance(value, dict) or set(value) != {"actionType", "parameters", "count"}:
        raise ValueError
    if (
        not isinstance(value["actionType"], str)
        or not isinstance(value["parameters"], dict)
        or not isinstance(value["count"], int)
        or isinstance(value["count"], bool)
        or value["count"] < 1
    ):
        raise ValueError
    decision = ActionDecision.from_values(value["actionType"], value["parameters"], ActionUsage())
    return decision.action, value["count"]


def _decision(kind: ActionKind, parameters: dict[str, str] | None = None) -> ActionDecision:
    return ActionDecision.from_values(kind, parameters or {}, ActionUsage())


def _bounded(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)
