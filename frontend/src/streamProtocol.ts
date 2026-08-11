export type SseEvent = { id: string; type: string; data: string };

export function parseSseEvent(block: string): SseEvent | null {
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

export async function consumeSseEvents(
  body: ReadableStream<Uint8Array> | null,
  apply: (event: SseEvent) => boolean | Promise<boolean>,
) {
  if (!body) throw new Error("event stream body missing");
  const reader = body.getReader();
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
      const event = parseSseEvent(block);
      if (event && !(await apply(event))) return false;
      boundary = buffer.search(/\r?\n\r?\n/);
    }
    if (done) return true;
  }
}

export function parseViewCursor(cursor: string, expectedEpoch: string) {
  const separator = cursor.lastIndexOf(":");
  if (separator < 1 || cursor.slice(0, separator) !== expectedEpoch) return null;
  const sequence = cursor.slice(separator + 1);
  return /^(0|[1-9]\d*)$/.test(sequence) && Number.isSafeInteger(Number(sequence))
    ? { epoch: expectedEpoch, sequence: Number(sequence) }
    : null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function hasOnlyKeys(value: Record<string, unknown>, keys: string[]) {
  return Object.keys(value).every((key) => keys.includes(key));
}
