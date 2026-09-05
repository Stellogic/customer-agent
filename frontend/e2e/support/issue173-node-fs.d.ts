// 与 e2e/node.d.ts 一致，只声明本票使用的 Node API，不引入全局 Node 类型依赖。
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf8"): string;
  export function writeFileSync(path: string, data: string): void;
  export function mkdirSync(path: string, options: { recursive: true }): string | undefined;
}
