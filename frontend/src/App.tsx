import { FormEvent, useEffect, useRef, useState } from "react";

type Snapshot = {
  view: "CUSTOMER_PUBLIC";
  cursor: string;
  ticket: { id: string; lifecycleState: string; handlingMode: string; firstRespondedAt: string };
  messages: Array<{ author: string; body: string; sentAt: string }>;
};

type PublicEvent = { id: string; type: string; data: string };

const customerHeaders = { "X-Synthetic-Customer-Id": "customer-demo" };

export function App() {
  const [orderReference, setOrderReference] = useState("");
  const [description, setDescription] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(globalThis.crypto.randomUUID());
  const streamController = useRef<AbortController | null>(null);

  useEffect(() => {
    const ticketId = new URLSearchParams(globalThis.location.search).get("ticket");
    if (ticketId && /^[0-9a-f-]{36}$/i.test(ticketId)) void loadTicket(ticketId);
    return () => streamController.current?.abort();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const created = await fetch("/api/customer/tickets", {
        method: "POST",
        credentials: "same-origin",
        headers: { ...customerHeaders, "Content-Type": "application/json", "Idempotency-Key": requestId.current },
        body: JSON.stringify({ orderReference, description }),
      });
      if (!created.ok) throw new Error("ticket creation failed");
      const { ticketId } = await created.json() as { ticketId: string };
      await loadTicket(ticketId);
    } catch {
      setError("提交未完成，请保留本页并重试。相同请求不会创建第二张工单。");
    } finally {
      setSubmitting(false);
    }
  }

  async function loadTicket(ticketId: string) {
    const loaded = await fetch(`/api/customer/tickets/${ticketId}`, { headers: customerHeaders, credentials: "same-origin" });
    if (!loaded.ok) throw new Error("snapshot request failed");
    const authoritative = await loaded.json() as Snapshot;
    setSnapshot(authoritative);
    globalThis.history.replaceState(null, "", `?ticket=${ticketId}`);
    void consumeEvents(ticketId, authoritative.cursor);
  }

  async function consumeEvents(ticketId: string, cursor: string) {
    streamController.current?.abort();
    const controller = new AbortController();
    streamController.current = controller;
    const markDisconnected = () => {
      if (!controller.signal.aborted) setError("实时更新已断开；当前内容可能过期，刷新后将从权威快照恢复。");
    };
    try {
      const response = await fetch(`/api/customer/tickets/${ticketId}/events`, {
        headers: { ...customerHeaders, "Last-Event-ID": cursor, Accept: "text/event-stream" },
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("event stream failed");
      const reader = response.body?.getReader();
      if (reader) {
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          let boundary = buffer.search(/\r?\n\r?\n/);
          while (boundary >= 0) {
            const block = buffer.slice(0, boundary);
            const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)?.[0].length ?? 2;
            buffer = buffer.slice(boundary + separator);
            const event = parsePublicEvent(block);
            if (event) applyPublicEvent(event);
            boundary = buffer.search(/\r?\n\r?\n/);
          }
          if (done) break;
        }
      }
    } catch {
      // The authoritative snapshot remains committed and readable after a stream failure.
    }
    markDisconnected();
  }

  function applyPublicEvent(event: PublicEvent) {
    setSnapshot((current) => {
      if (!current) return current;
      if (event.type === "PUBLIC_MESSAGE_APPENDED") {
        const message = JSON.parse(event.data) as Snapshot["messages"][number];
        const duplicate = current.messages.some((existing) =>
          existing.author === message.author && existing.body === message.body && existing.sentAt === message.sentAt);
        return { ...current, cursor: event.id, messages: duplicate ? current.messages : [...current.messages, message] };
      }
      if (event.type === "TICKET_ACCEPTED") {
        const accepted = JSON.parse(event.data) as { lifecycleState: string; handlingMode: string };
        return { ...current, cursor: event.id, ticket: { ...current.ticket, ...accepted } };
      }
      return current;
    });
  }

  return (
    <main className="help-center">
      <header>
        <p className="eyebrow">STELLOGIC 帮助中心</p>
        <h1>物流遇到问题？<br />我们从这里开始处理。</h1>
        <p className="lede">提交后，你会得到一张可查询的客服工单。当前票只确认受理，不会启动 Agent 调查。</p>
      </header>

      {!snapshot ? (
        <form className="ticket-form" onSubmit={submit}>
          <label>订单编号<input aria-label="订单编号" value={orderReference} onChange={(event) => setOrderReference(event.target.value)} required /></label>
          <label>问题描述<textarea aria-label="问题描述" value={description} onChange={(event) => setDescription(event.target.value)} required rows={5} /></label>
          <button disabled={submitting}>{submitting ? "正在提交…" : "提交物流延迟问题"}</button>
          {error && <p className="error" role="alert">{error}</p>}
        </form>
      ) : (
        <section className="ticket-card" aria-live="polite">
          <div className="ticket-heading">
            <div><p className="eyebrow">客服工单</p><h2>{snapshot.ticket.id}</h2></div>
            <span className="status">{snapshot.ticket.lifecycleState === "INVESTIGATING" ? "调查中" : snapshot.ticket.lifecycleState}</span>
          </div>
          <ol className="conversation">
            {snapshot.messages.map((message, index) => (
              <li key={`${message.sentAt}-${index}`} className={message.author.toLowerCase()}>
                <span>{message.author === "CUSTOMER" ? "你" : "客服"}</span>
                <p>{message.body}</p>
              </li>
            ))}
          </ol>
          <p className="recovery-note">刷新页面时，公开沟通会从 Spring 权威快照恢复。</p>
          {error && <p className="error" role="alert">{error}</p>}
        </section>
      )}
    </main>
  );
}

function parsePublicEvent(block: string): PublicEvent | null {
  let id = "";
  let type = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("id:")) id = line.slice(3).trimStart();
    else if (line.startsWith("event:")) type = line.slice(6).trimStart();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return id && data.length ? { id, type, data: data.join("\n") } : null;
}
