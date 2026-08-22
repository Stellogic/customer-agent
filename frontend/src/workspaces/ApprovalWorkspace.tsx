import { ApprovalWorkbench } from "../ApprovalWorkbench";
import { LegacyBusinessIdentity } from "./LegacyBusinessIdentity";

const APPROVER_IDS = ["approver-demo", "approver-other-demo"] as const;

export default function ApprovalWorkspace() {
  return (
    <LegacyBusinessIdentity
      role="APPROVER"
      allowedIds={APPROVER_IDS}
      deniedTitle="无权访问审批工作台"
    >
      {(approverId) => <ApprovalWorkbench approverId={approverId} />}
    </LegacyBusinessIdentity>
  );
}
