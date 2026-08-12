FROM python:3.13.14-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.8.22
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY langgraph.json ./
COPY src ./src
COPY tests ./tests

FROM base AS test
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
