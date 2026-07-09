from celery import Celery

from app.core.config import get_settings

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
