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
