import { ApprovalWorkbench } from "../ApprovalWorkbench";
import { CurrentSessionContext } from "../session";

export default function ApprovalWorkspace() {
  const session = CurrentSessionContext.use();
  return <ApprovalWorkbench approverId={session.id} />;
}
