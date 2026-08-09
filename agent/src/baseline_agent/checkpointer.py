import contextlib
import os
from collections.abc import AsyncIterator

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


@contextlib.asynccontextmanager
async def generate_checkpointer() -> AsyncIterator[BaseCheckpointSaver]:
    async with AsyncPostgresSaver.from_conn_string(os.environ["AGENT_DATABASE_URI"]) as saver:
        yield saver

