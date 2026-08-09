import pytest

from baseline_agent.graph import probe_spring


@pytest.mark.asyncio
async def test_non_spring_callers_cannot_start_the_baseline_graph() -> None:
    with pytest.raises(ValueError, match="Spring-owned"):
        await probe_spring({"requested_by": "browser"})

