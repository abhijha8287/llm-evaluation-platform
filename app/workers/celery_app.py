import time

from celery import Celery
from celery.signals import task_postrun, task_prerun, worker_process_init
from prometheus_client import start_http_server

from app.core.config import get_settings
from app.monitoring.metrics import CELERY_TASK_DURATION_SECONDS, CELERY_TASKS_TOTAL

settings = get_settings()

celery_app = Celery(
    "llm_eval_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.eval_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    # eng-review D12: chord result tracking (mark_run_completed only fires
    # once every run_pair task in the group has finished) needs the result
    # backend to persist chord state — Redis supports this natively.
    result_extended=True,
)

# Phase 9: one shared hook point covering all five task types (D8-style —
# instrument once here, not duplicated in every task body in eval_tasks.py).
# task_id-keyed dict, not a single module-level float: a worker with
# --concurrency > 1 (prefork) can have multiple tasks in flight per process,
# and task_prerun/task_postrun for different tasks can interleave.
_task_started_at: dict[str, float] = {}


@task_prerun.connect
def _record_task_start(task_id: str, **_kwargs) -> None:
    _task_started_at[task_id] = time.monotonic()


@task_postrun.connect
def _record_task_end(task_id: str, task, state: str, **_kwargs) -> None:
    started = _task_started_at.pop(task_id, None)
    elapsed_seconds = time.monotonic() - started if started is not None else 0.0
    task_name = task.name if task is not None else "unknown"
    CELERY_TASKS_TOTAL.labels(task_name=task_name, status=state).inc()
    CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name, status=state).observe(elapsed_seconds)


@worker_process_init.connect
def _start_metrics_server(**_kwargs) -> None:
    """Verified (Phase 9) against Celery's own source: this signal fires
    exactly once for the solo pool (celery/concurrency/solo.py's
    TaskPool.__init__) and once per forked child for the prefork pool
    (celery/concurrency/prefork.py). This app's documented deployment target
    is a single-concurrency worker process (--pool=solo / --concurrency=1,
    see app/monitoring/metrics.py's module docstring), so exactly one
    process ever calls this in practice. The try/except is a guard against
    a prefork worker started with concurrency > 1 (outside the documented
    scope): every child after the first would otherwise crash the whole
    worker trying to bind the same port — better to have only the first
    child's metrics exposed than no worker running at all.
    """
    try:
        start_http_server(settings.celery_metrics_port)
    except OSError:
        pass
