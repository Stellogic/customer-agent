FROM python:3.13.14-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.8.22
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY langgraph.json ./
COPY src ./src

FROM base AS test
COPY tests ./tests
COPY tests/fixtures/knowledge-history /docs/implementation/evidence
COPY smoke.py ./
COPY approval_queue_time_smoke.py ./
COPY auto_resolution_smoke.py ./
COPY order_allowance_smoke.py ./
RUN uv run ruff format --check . \
    && uv run ruff check . \
    && uv run pyright \
    && uv run pytest

FROM base AS runtime
RUN uv sync --frozen --no-dev
RUN useradd --system --uid 10002 --create-home agent && chown -R agent:agent /app
USER agent
ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 2024
ENTRYPOINT ["langgraph", "dev", "--host", "0.0.0.0", "--port", "2024", "--no-browser", "--no-reload"]
