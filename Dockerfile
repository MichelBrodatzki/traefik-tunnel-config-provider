FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Unbuffered stdout for clean logs, no .pyc writes (keeps a read-only rootfs
# happy), and the venv's bin on PATH so we can run fastapi directly without
# `uv run` re-validating the lockfile on every container start.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the app itself. It's run as a plain script (`fastapi run main.py`), so
# there's no need to install the project as a package.
COPY main.py ./

# Drop root: the app only reads its own files and talks to the API server.
RUN useradd --system --uid 65532 --no-create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness from the container's perspective; mirrors the k8s probe.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"

# Bind to all interfaces so the Service can reach it.
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
