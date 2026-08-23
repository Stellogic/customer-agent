declare module "node:child_process" {
  export function execFileSync(
    file: string,
    args: string[],
    options: { encoding: "utf8"; env: Record<string, string | undefined> },
  ): string;
}
