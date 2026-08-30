export type PendingCompensationSubmit = {
  kind: "proposal" | "exception";
  idempotencyKey: string;
};

const PENDING_COMPENSATION_PREFIX = "support-workbench:pending-compensation:";

export function readPendingCompensationSubmit(ticketId: string): PendingCompensationSubmit | null {
  try {
    const raw = globalThis.sessionStorage.getItem(storageKey(ticketId));
    if (!raw) return null;
    const value = JSON.parse(raw) as unknown;
    if (
      !isRecord(value) ||
      (value.kind !== "proposal" && value.kind !== "exception") ||
      typeof value.idempotencyKey !== "string" ||
      value.idempotencyKey.trim().length === 0 ||
      value.idempotencyKey.length > 200
    )
      return null;
    return { kind: value.kind, idempotencyKey: value.idempotencyKey };
  } catch {
    return null;
  }
}

export function storePendingCompensationSubmit(
  ticketId: string,
  submit: PendingCompensationSubmit,
) {
  try {
    globalThis.sessionStorage.setItem(storageKey(ticketId), JSON.stringify(submit));
  } catch {
    // Query remains available during this render even if browser storage is unavailable.
  }
}

export function clearPendingCompensationSubmit(ticketId: string) {
  try {
    globalThis.sessionStorage.removeItem(storageKey(ticketId));
  } catch {
    // Storage failures must not change the authoritative compensation result.
  }
}

export function clearPendingCompensationSubmits() {
  try {
    const keys: string[] = [];
    for (let index = 0; index < globalThis.sessionStorage.length; index += 1) {
      const key = globalThis.sessionStorage.key(index);
      if (key?.startsWith(PENDING_COMPENSATION_PREFIX)) keys.push(key);
    }
    for (const key of keys) globalThis.sessionStorage.removeItem(key);
  } catch {
    // Session invalidation must still notify consumers when storage is unavailable.
  }
}

function storageKey(ticketId: string) {
  return `${PENDING_COMPENSATION_PREFIX}${ticketId}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
