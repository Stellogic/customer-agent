// 与现有 node:fs / child_process 声明一致，仅覆盖离线回归所用的 Node 标准库接口。
declare module "node:http" {
  export interface IncomingMessage extends AsyncIterable<string> {
    method?: string;
    url?: string;
    setEncoding(encoding: "utf8"): void;
  }
  export interface ServerResponse {
    writeHead(status: number, headers?: Record<string, string>): void;
    end(body?: string): void;
  }
  interface Server {
    once(event: "error", listener: (error: Error) => void): void;
    listen(port: number, host: string, listener: () => void): void;
    closeAllConnections(): void;
    close(listener: (error?: Error) => void): void;
  }
  export function createServer(
    listener: (request: IncomingMessage, response: ServerResponse) => void,
  ): Server;
}
