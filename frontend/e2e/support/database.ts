import { execFileSync } from "node:child_process";

declare const process: { env: Record<string, string | undefined> };

export function executeFixtureSql(sql: string) {
  execFileSync("psql", ["-v", "ON_ERROR_STOP=1", "-c", sql], {
    encoding: "utf8",
    env: {
      ...process.env,
      PGHOST: process.env.ISSUE80_DATABASE_HOST ?? "postgres",
      PGPORT: "5432",
      PGDATABASE: "customer_agent",
      PGUSER: "postgres",
      PGPASSWORD: process.env.ISSUE80_DATABASE_PASSWORD ?? "local-postgres-superuser",
    },
  });
}
