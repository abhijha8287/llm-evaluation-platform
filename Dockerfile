# Phase 10: one image, two roles — the API (uvicorn) and the Celery worker
# both run this same image with a different `command:` override in
# docker-compose.yml, rather than maintaining two near-identical Dockerfiles
# that would drift out of sync with each other's dependency set.
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

FROM base AS builder
# gcc only exists in the builder stage — asyncpg/other deps that need a C
# build step get it here; the runtime stage below never installs it, kept
# out of the final image entirely.
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
# Found by actually running the built image, not just building it: DeepEval
# writes a `.deepeval/` directory relative to CWD at import time
# (deepeval/telemetry.py's os.makedirs(HIDDEN_DIR)) — /app must be writable
# by the non-root user or every import of app.evaluation.scoring_service
# (and therefore app.main, since routes/regression.py imports it transitively)
# crashes with PermissionError before the server ever starts.
RUN chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
