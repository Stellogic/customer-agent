import { describe, expect, it } from "vitest";
import { coreCaseBudgetStopReason, type CoreCaseBudget } from "./test-support/issue230-case-budget";

const now = Date.parse("2026-09-08T00:00:00Z");
const ledger: CoreCaseBudget = {
  deadline: "2026-09-08T00:30:00Z",
  maxAttempts: 2,
  maxTokens: 100,
  limitMicros: 1000,
  entries: [{ status: "SETTLED", inputTokens: 10, outputTokens: 5, estimatedCostMicros: 50 }],
};

describe("整批收集的用例前预算检查", () => {
  it("已知消耗在所有边界内时允许下一例,不修改账本", () => {
    const before = structuredClone(ledger);
    expect(coreCaseBudgetStopReason(ledger, now)).toBeNull();
    expect(ledger).toEqual(before);
  });

  it.each([
    [{ stopReason: "CORE_MATRIX_FINISHED" }, "CORE_BUDGET_STOPPED"],
    [{ deadline: "2026-09-08T00:00:00Z" }, "CORE_BUDGET_DEADLINE"],
    [{ maxAttempts: 1 }, "CORE_BUDGET_ATTEMPT_LIMIT"],
    [{ maxTokens: 15 }, "CORE_BUDGET_TOKEN_LIMIT"],
    [{ limitMicros: 50 }, "CORE_BUDGET_COST_LIMIT"],
  ] as const)("冻结停止条件 %j", (change, reason) => {
    expect(coreCaseBudgetStopReason({ ...ledger, ...change }, now)).toBe(reason);
  });

  it.each(["PENDING", "IN_FLIGHT"])("%s 预留尚未结算时停止后续用例", (status) => {
    const entries = [{ ...ledger.entries[0], status }];
    expect(coreCaseBudgetStopReason({ ...ledger, entries }, now)).toBe("CORE_BUDGET_UNSETTLED");
  });

  it("未知用量不能按零放行", () => {
    const entries = [{ ...ledger.entries[0], inputTokens: null }];
    expect(coreCaseBudgetStopReason({ ...ledger, entries }, now)).toBe("CORE_BUDGET_UNKNOWN_USAGE");
  });
});
