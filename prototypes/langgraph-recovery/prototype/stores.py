from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .model import (
    PrototypeInvariantError,
    SimulatedResponseLoss,
    StaleGenerationRejected,
    payload_hash,
    stable_thread_id,
)


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


class SpringAuthority:
    """A tiny stand-in for Spring's transactional business authority."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        connection = _connect(self.path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _setup(self) -> None:
        with self.tx() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    current_generation_id TEXT,
                    generation_seq INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS generations (
                    generation_id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    generation_seq INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    thread_id TEXT,
                    UNIQUE(ticket_id, generation_seq)
                );
                CREATE TABLE IF NOT EXISTS submission_outbox (
                    generation_id TEXT PRIMARY KEY,
                    requested_thread_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS resume_requests (
                    request_id TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL,
                    answer_hash TEXT NOT NULL,
                    run_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS effects (
                    idempotency_key TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS faults (
                    name TEXT PRIMARY KEY,
                    remaining INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    generation_id TEXT,
                    details_json TEXT NOT NULL
                );
                """
            )

    def reset(self) -> None:
        with self.tx() as db:
            for table in (
                "audit",
                "faults",
                "effects",
                "resume_requests",
                "submission_outbox",
                "generations",
                "tickets",
            ):
                db.execute(f"DELETE FROM {table}")

    def create_generation(self, ticket_id: str) -> dict[str, Any]:
        with self.tx() as db:
            ticket = db.execute(
                "SELECT generation_seq FROM tickets WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
            next_seq = (ticket["generation_seq"] if ticket else 0) + 1
            generation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ticket_id}:{next_seq}"))
            requested_thread_id = stable_thread_id(generation_id)
            db.execute(
                "INSERT INTO tickets(ticket_id, current_generation_id, generation_seq) VALUES (?, ?, ?) "
                "ON CONFLICT(ticket_id) DO UPDATE SET current_generation_id=excluded.current_generation_id, generation_seq=excluded.generation_seq",
                (ticket_id, generation_id, next_seq),
            )
            db.execute(
                "INSERT INTO generations(generation_id, ticket_id, generation_seq, status) VALUES (?, ?, ?, 'PENDING_SUBMISSION')",
                (generation_id, ticket_id, next_seq),
            )
            db.execute(
                "INSERT INTO submission_outbox(generation_id, requested_thread_id, status) VALUES (?, ?, 'PENDING')",
                (generation_id, requested_thread_id),
            )
            self._audit(db, "GENERATION_CREATED", generation_id, {"thread_id": requested_thread_id})
        return {"generation_id": generation_id, "thread_id": requested_thread_id, "seq": next_seq}

    def pending_submission(self, generation_id: str) -> dict[str, Any]:
        with _connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM submission_outbox WHERE generation_id = ?", (generation_id,)
            ).fetchone()
            if not row:
                raise PrototypeInvariantError(f"missing submission for {generation_id}")
            return dict(row)

    def mark_submission_attempt(self, generation_id: str) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE submission_outbox SET attempts=attempts+1 WHERE generation_id=?",
                (generation_id,),
            )

    def confirm_thread(self, generation_id: str, thread_id: str) -> None:
        expected = stable_thread_id(generation_id)
        if thread_id != expected:
            raise PrototypeInvariantError("agent returned a thread not derived from the generation")
        with self.tx() as db:
            row = db.execute(
                "SELECT requested_thread_id FROM submission_outbox WHERE generation_id=?",
                (generation_id,),
            ).fetchone()
            if not row or row["requested_thread_id"] != thread_id:
                raise PrototypeInvariantError("submission/thread mismatch")
            db.execute(
                "UPDATE submission_outbox SET status='CONFIRMED' WHERE generation_id=?",
                (generation_id,),
            )
            db.execute(
                "UPDATE generations SET status='ACTIVE', thread_id=? WHERE generation_id=?",
                (thread_id, generation_id),
            )
            self._audit(db, "THREAD_CONFIRMED", generation_id, {"thread_id": thread_id})

    def register_resume(self, generation_id: str, request_id: str, answer: str) -> tuple[str, bool]:
        answer_digest = payload_hash({"answer": answer})
        with self.tx() as db:
            current = db.execute(
                "SELECT request_id, answer_hash, run_id FROM resume_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if current:
                if current["answer_hash"] != answer_digest:
                    raise PrototypeInvariantError("same resume request id used with different answer")
                return current["run_id"], False
            run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"resume:{request_id}"))
            db.execute(
                "INSERT INTO resume_requests(request_id, generation_id, answer_hash, run_id) VALUES (?, ?, ?, ?)",
                (request_id, generation_id, answer_digest, run_id),
            )
            self._audit(db, "RESUME_ACCEPTED", generation_id, {"request_id": request_id, "run_id": run_id})
            return run_id, True

    def arm_fault(self, name: str, count: int = 1) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO faults(name, remaining) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET remaining=excluded.remaining",
                (name, count),
            )

    def _consume_fault(self, name: str) -> bool:
        with self.tx() as db:
            row = db.execute("SELECT remaining FROM faults WHERE name=?", (name,)).fetchone()
            if not row or row["remaining"] <= 0:
                return False
            db.execute("UPDATE faults SET remaining=remaining-1 WHERE name=?", (name,))
            return True

    def execute_business_tool(
        self,
        generation_id: str,
        ticket_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        digest = payload_hash(payload)
        created = False
        stale = False
        result: dict[str, Any] | None = None
        with self.tx() as db:
            ticket = db.execute(
                "SELECT current_generation_id FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
            if not ticket or ticket["current_generation_id"] != generation_id:
                self._audit(
                    db,
                    "STALE_RESULT_REJECTED",
                    generation_id,
                    {"ticket_id": ticket_id, "idempotency_key": idempotency_key},
                )
                stale = True
            else:
                existing = db.execute(
                    "SELECT payload_hash, result_json FROM effects WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    if existing["payload_hash"] != digest:
                        raise PrototypeInvariantError("same idempotency key used with different payload")
                    result = json.loads(existing["result_json"])
                    self._audit(db, "EFFECT_REPLAYED", generation_id, {"idempotency_key": idempotency_key})
                else:
                    result = {"proposal_revision": f"proposal-{generation_id[:8]}-r1", "status": "PROPOSED"}
                    db.execute(
                        "INSERT INTO effects(idempotency_key, generation_id, payload_hash, result_json) VALUES (?, ?, ?, ?)",
                        (idempotency_key, generation_id, digest, json.dumps(result, sort_keys=True)),
                    )
                    self._audit(db, "EFFECT_COMMITTED", generation_id, {"idempotency_key": idempotency_key})
                    created = True
        if stale:
            raise StaleGenerationRejected(generation_id)
        if created and self._consume_fault("tool_response_loss"):
            raise SimulatedResponseLoss("Spring committed the effect; Agent did not receive the response")
        if result is None:
            raise PrototypeInvariantError("tool execution produced no result")
        return result

    def counts(self) -> dict[str, int]:
        with _connect(self.path) as db:
            return {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("tickets", "generations", "submission_outbox", "resume_requests", "effects", "audit")
            }

    def snapshot(self) -> dict[str, Any]:
        with _connect(self.path) as db:
            result: dict[str, Any] = {}
            for table in ("tickets", "generations", "submission_outbox", "resume_requests", "effects", "faults", "audit"):
                result[table] = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            return result

    @staticmethod
    def _audit(db: sqlite3.Connection, event_type: str, generation_id: str | None, details: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO audit(event_type, generation_id, details_json) VALUES (?, ?, ?)",
            (event_type, generation_id, json.dumps(details, ensure_ascii=False, sort_keys=True)),
        )


class AgentDirectory:
    """A minimal remote thread/run directory; not an Agent Server reimplementation."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    request_id TEXT UNIQUE
                );
                """
            )

    def reset(self) -> None:
        with _connect(self.path) as db:
            db.execute("DELETE FROM runs")
            db.execute("DELETE FROM threads")

    def create_thread(self, generation_id: str, thread_id: str) -> dict[str, str]:
        with _connect(self.path) as db:
            row = db.execute("SELECT generation_id FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
            if row and row["generation_id"] != generation_id:
                raise PrototypeInvariantError("thread already belongs to another generation")
            db.execute(
                "INSERT INTO threads(thread_id, generation_id) VALUES (?, ?) ON CONFLICT(thread_id) DO NOTHING",
                (thread_id, generation_id),
            )
        return {"thread_id": thread_id, "generation_id": generation_id}

    def get_thread(self, thread_id: str) -> dict[str, str] | None:
        with _connect(self.path) as db:
            row = db.execute("SELECT * FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
            return dict(row) if row else None

    def create_run(self, thread_id: str, kind: str, request_id: str | None = None) -> tuple[str, bool]:
        with _connect(self.path) as db:
            if request_id:
                current = db.execute("SELECT run_id FROM runs WHERE request_id=?", (request_id,)).fetchone()
                if current:
                    return current["run_id"], False
            index = db.execute("SELECT COUNT(*) FROM runs WHERE thread_id=?", (thread_id,)).fetchone()[0] + 1
            run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{thread_id}:run:{index}"))
            db.execute(
                "INSERT INTO runs(run_id, thread_id, kind, request_id) VALUES (?, ?, ?, ?)",
                (run_id, thread_id, kind, request_id),
            )
            return run_id, True

    def snapshot(self) -> dict[str, Any]:
        with _connect(self.path) as db:
            return {
                "threads": [dict(row) for row in db.execute("SELECT * FROM threads ORDER BY rowid")],
                "runs": [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY rowid")],
            }
