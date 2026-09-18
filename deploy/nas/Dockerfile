# My NotebookLM (PKA) — production image for the NAS/OMV stack.
# Build context must be the repo root: docker build -f deploy/nas/Dockerfile ..
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    PATH="/root/.local/bin:${PATH}"

# uv CLI (fast, reproducible installs)
RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependencies first (layer caching): sync the frozen production lock.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-cache

# Application source + migrations.
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

EXPOSE 8000

# The FastAPI application is a factory; uvicorn runs it with --factory.
CMD ["uv", "run", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]