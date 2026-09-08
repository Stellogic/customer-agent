export type CoreCaseBudget = {
  stopReason?: string;
  deadline: string;
  maxAttempts: number;
  maxTokens: number;
  limitMicros: number;
  entries: {
    status: string;
    inputTokens: number | null;
    outputTokens: number | null;
    estimatedCostMicros: number | null;
  }[];
};

export function coreCaseBudgetStopReason(ledger: CoreCaseBudget, now: number): string | null {
  if (ledger.stopReason) return "CORE_BUDGET_STOPPED";
  if (ledger.entries.some(({ status }) => status !== "SETTLED")) return "CORE_BUDGET_UNSETTLED";
  const deadline = Date.parse(ledger.deadline);
  if (!Number.isFinite(deadline)) return "CORE_BUDGET_INVALID";
  if (now >= deadline) return "CORE_BUDGET_DEADLINE";
  if (
    [ledger.maxAttempts, ledger.maxTokens, ledger.limitMicros].some(
      (limit) => !Number.isFinite(limit) || limit <= 0,
    )
  )
    return "CORE_BUDGET_INVALID";
  let tokens = 0;
  let costMicros = 0;
  for (const entry of ledger.entries) {
    if (
      entry.inputTokens === null ||
      entry.outputTokens === null ||
      entry.estimatedCostMicros === null ||
      !Number.isFinite(entry.inputTokens) ||
      !Number.isFinite(entry.outputTokens) ||
      !Number.isFinite(entry.estimatedCostMicros)
    )
      return "CORE_BUDGET_UNKNOWN_USAGE";
    tokens += entry.inputTokens + entry.outputTokens;
    costMicros += entry.estimatedCostMicros;
  }
  if (ledger.entries.length >= ledger.maxAttempts) return "CORE_BUDGET_ATTEMPT_LIMIT";
  if (tokens >= ledger.maxTokens) return "CORE_BUDGET_TOKEN_LIMIT";
  if (costMicros >= ledger.limitMicros) return "CORE_BUDGET_COST_LIMIT";
  return null;
}
