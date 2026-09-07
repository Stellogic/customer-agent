"""冻结核心诊断的人民币预留账本;不接管历史实验账本或供应商结算。"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from baseline_agent.deepseek_investigation_model import ModelCallAttemptRecord

_SESSION = str(uuid.uuid4())
_SCHEMA = "issue230-core-budget-v1"
_MODEL = "deepseek-v4-flash"
_PRICES = {
    _MODEL: {"inputMicrosPerToken": 3, "outputMicrosPerToken": 9},
    "deepseek-v4-pro": {"inputMicrosPerToken": 9, "outputMicrosPerToken": 27},
}
_ROLES = {"intake", "action", "judgment", "communication"}
_OWNER: ContextVar[tuple[str, str] | None] = ContextVar("core_provider_owner", default=None)


@contextmanager
def provider_owner(ticket_id: str, generation_id: str) -> Iterator[None]:
    token = _OWNER.set((ticket_id, generation_id))
    try:
        yield
    finally:
        _OWNER.reset(token)


class CoreBudgetStopped(RuntimeError):
    pass


def configured_core_budget(environment: Mapping[str, str]) -> CoreValidationBudget | None:
    path = environment.get("CORE_VALIDATION_BUDGET_PATH", "").strip()
    authorization_id = environment.get("CORE_VALIDATION_AUTHORIZATION_ID", "").strip()
    if not path and not authorization_id:
        return None
    if not path or not authorization_id:
        raise ValueError("core validation budget path and authorization id are required together")
    return CoreValidationBudget.open(Path(path), authorization_id=authorization_id)


@asynccontextmanager
async def model_attempt_budget(
    budget: CoreValidationBudget | None,
    records: list[ModelCallAttemptRecord],
    *,
    attempt_id: str,
    internal_call_id: str,
    role: str,
    request: Mapping[str, object],
) -> AsyncIterator[None]:
    if budget is None:
        yield
        return
    offset = len(records)
    reservation = asyncio.create_task(
        asyncio.to_thread(
            budget.reserve,
            attempt_id,
            internal_call_id=internal_call_id,
            role=role,
            request=request,
        )
    )
    try:
        await asyncio.shield(reservation)
    except asyncio.CancelledError:
        # 线程不会随协程取消;先确认预留完成,避免留下无人结算的同进程 IN_FLIGHT。
        await reservation
        await _settle_attempt(budget, attempt_id, None)
        raise
    try:
        yield
    finally:
        record = next((item for item in records[offset:] if item.attempt_id == attempt_id), None)
        await _settle_attempt(budget, attempt_id, record)


async def _settle_attempt(
    budget: CoreValidationBudget, attempt_id: str, record: ModelCallAttemptRecord | None
) -> None:
    from baseline_agent.model_call_evidence import serialize_model_attempt

    settlement = asyncio.create_task(
        asyncio.to_thread(
            budget.settle,
            attempt_id,
            input_tokens=record.input_tokens if record is not None else None,
            output_tokens=record.output_tokens if record is not None else None,
            attempt=serialize_model_attempt(record) if record is not None else None,
        )
    )
    try:
        await asyncio.shield(settlement)
    except asyncio.CancelledError:
        await settlement
        raise


class CoreValidationBudget:
    def __init__(self, path: Path, authorization_id: str) -> None:
        self.path = path
        self.authorization_id = authorization_id

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        authorization_id: str,
        limit_micros: int,
        max_attempts: int,
        max_tokens: int,
        deadline: datetime,
        communication_model: str = _MODEL,
    ) -> CoreValidationBudget:
        if not 0 < limit_micros <= 3_000_000 or max_attempts < 1 or max_tokens < 1:
            raise ValueError("invalid frozen core budget")
        if communication_model not in _PRICES:
            raise ValueError("unsupported core communication model")
        path.parent.mkdir(parents=True, exist_ok=True)
        budget = cls(path, authorization_id)
        with budget._lock():
            if path.exists():
                raise FileExistsError("core budget already exists; open without resetting it")
            budget._write(
                {
                    "schemaVersion": _SCHEMA,
                    "authorizationId": authorization_id,
                    "currency": "CNY",
                    "model": _MODEL,
                    "communicationModel": communication_model,
                    "limitMicros": limit_micros,
                    "maxAttempts": max_attempts,
                    "maxTokens": max_tokens,
                    "deadline": deadline.astimezone(UTC).isoformat(),
                    "price": _PRICES[_MODEL],
                    "pricesByModel": {
                        _MODEL: _PRICES[_MODEL],
                        communication_model: _PRICES[communication_model],
                    },
                    "entries": [],
                }
            )
        return budget

    @classmethod
    def open(cls, path: Path, *, authorization_id: str) -> CoreValidationBudget:
        budget = cls(path, authorization_id)
        with budget._lock():
            budget._read()
        return budget

    @contextmanager
    def _lock(self) -> Iterator[None]:
        # 锁固定旁路文件;账本本身会被原子替换,不能锁它的旧 inode。
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            state["schemaVersion"] != _SCHEMA
            or state["authorizationId"] != self.authorization_id
            or state["currency"] != "CNY"
            or state["model"] != _MODEL
        ):
            raise CoreBudgetStopped("CORE_BUDGET_IDENTITY_MISMATCH")
        return state

    def _write(self, state: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".pending-write")
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(state, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)

    def stop(self, reason: str) -> None:
        with self._lock():
            state = self._read()
            if not state.get("stopReason"):
                state["stopReason"] = reason
                state["stoppedAt"] = datetime.now(UTC).isoformat()
                self._write(state)

    def reserve(
        self,
        attempt_id: str,
        *,
        role: str,
        request: Mapping[str, object],
        internal_call_id: str | None = None,
    ) -> None:
        if role not in _ROLES:
            raise CoreBudgetStopped("CORE_BUDGET_REQUEST_MISMATCH")
        output_tokens = request["max_output_tokens"]
        if not isinstance(request.get("input"), str) or type(output_tokens) is not int:
            raise CoreBudgetStopped("CORE_BUDGET_REQUIRES_TEXT_REQUEST")
        if output_tokens < 1:
            raise CoreBudgetStopped("CORE_BUDGET_REQUIRES_OUTPUT_LIMIT")
        # 仅是保守工程预留,不是供应商内部组装的精确 tokenizer 或数学上界。
        input_tokens = 2 * len(json.dumps(dict(request), ensure_ascii=False).encode("utf-8")) + 1024
        reserved_tokens = input_tokens + output_tokens
        with self._lock():
            state = self._read()
            model = state.get("communicationModel", _MODEL) if role == "communication" else _MODEL
            if request.get("model") != model:
                raise CoreBudgetStopped("CORE_BUDGET_REQUEST_MISMATCH")
            price = state.get("pricesByModel", {_MODEL: state["price"]})[model]
            reserved_micros = (
                input_tokens * price["inputMicrosPerToken"]
                + output_tokens * price["outputMicrosPerToken"]
            )
            entries = state["entries"]
            if state.get("stopReason"):
                raise CoreBudgetStopped("CORE_BUDGET_STOPPED")
            if any(
                entry["status"] == "PENDING"
                or (entry["status"] == "IN_FLIGHT" and entry["session"] != _SESSION)
                for entry in entries
            ):
                raise CoreBudgetStopped("CORE_BUDGET_UNSETTLED")
            if datetime.now(UTC) >= datetime.fromisoformat(state["deadline"]):
                raise CoreBudgetStopped("CORE_BUDGET_DEADLINE")
            if any(entry["attemptId"] == attempt_id for entry in entries):
                raise CoreBudgetStopped("CORE_BUDGET_DUPLICATE_ATTEMPT")
            consumed_micros = sum(
                entry["estimatedCostMicros"]
                if entry["status"] == "SETTLED"
                else entry["reservedMicros"]
                for entry in entries
            )
            consumed_tokens = sum(
                entry["inputTokens"] + entry["outputTokens"]
                if entry["status"] == "SETTLED"
                else entry["reservedInputTokens"] + entry["reservedOutputTokens"]
                for entry in entries
            )
            if (
                consumed_micros + reserved_micros > state["limitMicros"]
                or consumed_tokens + reserved_tokens > state["maxTokens"]
                or len(entries) >= state["maxAttempts"]
            ):
                raise CoreBudgetStopped("CORE_BUDGET_LIMIT")
            owner = _OWNER.get()
            entries.append(
                {
                    "attemptId": attempt_id,
                    "internalCallId": internal_call_id,
                    "ticketId": owner[0] if owner is not None else None,
                    "generationId": owner[1] if owner is not None else None,
                    "role": role,
                    "model": model,
                    "price": price,
                    "session": _SESSION,
                    "status": "IN_FLIGHT",
                    "startedAt": datetime.now(UTC).isoformat(),
                    "reservedInputTokens": input_tokens,
                    "reservedOutputTokens": output_tokens,
                    "reservedMicros": reserved_micros,
                    "inputTokens": None,
                    "outputTokens": None,
                    "estimatedCostMicros": None,
                    "supplierChargeMicros": None,
                }
            )
            self._write(state)

    def settle(
        self,
        attempt_id: str,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        attempt: dict[str, object] | None = None,
    ) -> None:
        with self._lock():
            state = self._read()
            entry = next(entry for entry in state["entries"] if entry["attemptId"] == attempt_id)
            price = entry.get("price", state["price"])
            if entry["status"] != "IN_FLIGHT":
                raise CoreBudgetStopped("CORE_BUDGET_ALREADY_RECORDED")
            known = input_tokens is not None and output_tokens is not None
            overrun = (
                input_tokens is not None
                and output_tokens is not None
                and (
                    input_tokens > entry["reservedInputTokens"]
                    or output_tokens > entry["reservedOutputTokens"]
                )
            )
            entry.update(
                inputTokens=input_tokens,
                outputTokens=output_tokens,
                estimatedCostMicros=(
                    input_tokens * price["inputMicrosPerToken"]
                    + output_tokens * price["outputMicrosPerToken"]
                    if input_tokens is not None and output_tokens is not None
                    else None
                ),
                status="SETTLED" if known and not overrun else "PENDING",
                completedAt=datetime.now(UTC).isoformat(),
            )
            if attempt is not None:
                entry["attempt"] = attempt
            self._write(state)
            if overrun:
                raise CoreBudgetStopped("CORE_BUDGET_RESERVATION_EXCEEDED")
