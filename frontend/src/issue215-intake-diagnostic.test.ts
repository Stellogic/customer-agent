import { describe, expect, it } from "vitest";
import {
  assessIntakeProgress,
  type IntakeObservation,
} from "./test-support/issue215-intake-diagnostic";

const initial: IntakeObservation = {
  httpStatus: 201,
  status: "NEEDS_CLARIFICATION",
  candidateMatches: true,
  responseIssueKinds: [],
  issueKinds: [],
  pendingKinds: ["PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"],
  assistanceCount: 0,
  ticketCount: 0,
};
const advanced: IntakeObservation = {
  ...initial,
  responseIssueKinds: ["PACKAGE_NOT_RECEIVED"],
  issueKinds: ["PACKAGE_NOT_RECEIVED"],
  pendingKinds: ["DUPLICATE_CHARGE"],
};

describe("#215 单次澄清诊断判据", () => {
  it("首次已完整识别两个问题时可直接等待最终确认", () => {
    expect(
      assessIntakeProgress({
        ...initial,
        status: "READY_TO_CONFIRM",
        issueKinds: ["PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"],
        responseIssueKinds: ["PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"],
        pendingKinds: [],
      }),
    ).toBe("READY_TO_CONFIRM");
  });
  it("诊断04的201和澄清状态不能掩盖数据库人工协助", () => {
    expect(assessIntakeProgress(initial, { ...initial, assistanceCount: 1 })).toBe("ASSISTED");
  });
  it("正确推进一个问题即可通过，不要求提前形成两个问题", () => {
    expect(assessIntakeProgress(initial, advanced)).toBe("HEAD_ADVANCED");
  });
  it("诊断01的一项已确定、一项待澄清也是合法起点", () => {
    expect(assessIntakeProgress(advanced)).toBe("READY_TO_REPLY");
    expect(
      assessIntakeProgress(advanced, {
        ...advanced,
        status: "READY_TO_CONFIRM",
        responseIssueKinds: ["PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"],
        issueKinds: ["PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"],
        pendingKinds: [],
      }),
    ).toBe("HEAD_ADVANCED");
  });
  it("推进待澄清问题时不能丢掉已有问题", () => {
    expect(
      assessIntakeProgress(advanced, {
        ...advanced,
        status: "READY_TO_CONFIRM",
        responseIssueKinds: ["DUPLICATE_CHARGE"],
        issueKinds: ["DUPLICATE_CHARGE"],
        pendingKinds: [],
      }),
    ).toBe("PROGRESS_MISMATCH");
  });
  it("仍在原问题澄清时必须失败", () => {
    expect(assessIntakeProgress(initial, initial)).toBe("PROGRESS_MISMATCH");
  });
  it("不能丢弃队列尾部或未经确认建单", () => {
    expect(assessIntakeProgress(initial, { ...advanced, pendingKinds: [] })).toBe(
      "PROGRESS_MISMATCH",
    );
    expect(assessIntakeProgress(initial, { ...advanced, ticketCount: 1 })).toBe("PREMATURE_TICKET");
  });
  it("首次已转人工时停止，不发送追加请求", () => {
    expect(assessIntakeProgress({ ...initial, assistanceCount: 1 })).toBe(
      "INITIAL_PRECONDITION_FAILED",
    );
  });
});
