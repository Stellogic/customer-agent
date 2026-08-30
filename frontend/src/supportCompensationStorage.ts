export type PendingCompensationBody =
  | {
      schema: "support-workbench-v2";
      planCode: string;
      reasonCode: string;
    }
  | {
      schema: "support-workbench-v2";
      reasonCode: "STANDARD_PLAN_INSUFFICIENT";
      justification: string;
    };

export type PendingCompensationSubmit = {
  kind: "proposal" | "exception";
  idempotencyKey: string;
  body?: PendingCompensationBody;
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
    const body = isPendingCompensationBody(value.body, value.kind) ? value.body : undefined;
    return { kind: value.kind, idempotencyKey: value.idempotencyKey, body };
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

function isPendingCompensationBody(
  value: unknown,
  kind: "proposal" | "exception",
): value is PendingCompensationBody {
  if (!isRecord(value) || value.schema !== "support-workbench-v2") return false;
  if (kind === "proposal") {
    return (
      hasOnlyKeys(value, ["schema", "planCode", "reasonCode"]) &&
      nonEmptyText(value.planCode, 200) &&
      nonEmptyText(value.reasonCode, 200)
    );
  }
  return (
    hasOnlyKeys(value, ["schema", "reasonCode", "justification"]) &&
    value.reasonCode === "STANDARD_PLAN_INSUFFICIENT" &&
    typeof value.justification === "string" &&
    value.justification.trim().length > 0 &&
    value.justification.length <= 2000
  );
}

function nonEmptyText(value: unknown, maximumLength: number) {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maximumLength;
}

function hasOnlyKeys(value: Record<string, unknown>, keys: string[]) {
  const actual = Object.keys(value);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}
