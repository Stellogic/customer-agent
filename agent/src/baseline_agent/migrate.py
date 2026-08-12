import asyncio
import os

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection


async def migrate() -> None:
    uri = os.environ["AGENT_MIGRATION_DATABASE_URI"]
    async with AsyncPostgresSaver.from_conn_string(uri) as saver:
        await saver.setup()

    async with await AsyncConnection.connect(uri, autocommit=True) as connection:
        await connection.execute("GRANT USAGE ON SCHEMA public TO agent_runtime")
        await connection.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agent_runtime"
        )
        await connection.execute(
            "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO agent_runtime"
        )
        await connection.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agent_runtime"
        )


if __name__ == "__main__":
    asyncio.run(migrate())
