import os
from datetime import datetime
from typing import Any, Protocol

from redis import Redis
from rq import Queue
from rq.job import Job

from app.services.job_tasks import execute_job


QUEUE_NAME = "thermoform"


class JobQueue(Protocol):
    def enqueue(self, task: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def get(self, job_id: str) -> dict[str, Any]: ...


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class RqJobQueue:
    def __init__(self, redis_url: str | None = None):
        self.connection = Redis.from_url(
            redis_url or os.getenv("THERMOFORM_REDIS_URL", "redis://localhost:6379/0")
        )
        self.queue = Queue(QUEUE_NAME, connection=self.connection, default_timeout=7200)

    def enqueue(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.queue.enqueue_call(
            func=execute_job,
            args=(task, payload),
            meta={"task": task},
            result_ttl=86400,
            failure_ttl=604800,
        )
        return self._snapshot(job)

    def get(self, job_id: str) -> dict[str, Any]:
        job = Job.fetch(job_id, connection=self.connection)
        return self._snapshot(job, refresh=True)

    @staticmethod
    def _snapshot(job: Job, refresh: bool = False) -> dict[str, Any]:
        status = job.get_status(refresh=refresh)
        return {
            "job_id": job.id,
            "task": job.meta.get("task", "unknown"),
            "status": status,
            "created_at": _timestamp(job.created_at),
            "started_at": _timestamp(job.started_at),
            "ended_at": _timestamp(job.ended_at),
            "result": job.result if status == "finished" else None,
            "error": job.exc_info.splitlines()[-1] if status == "failed" and job.exc_info else None,
        }


def get_job_queue() -> JobQueue:
    return RqJobQueue()
