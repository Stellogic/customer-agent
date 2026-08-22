import { SupportWorkbench } from "../SupportWorkbench";
import { CurrentSessionContext } from "../session";

export default function SupportWorkspace() {
  const session = CurrentSessionContext.use();
  return <SupportWorkbench supportId={session.id} />;
}
