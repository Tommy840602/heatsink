import os
from datetime import datetime
from typing import Any, Protocol

from redis import Redis
from rq import Queue
from rq.job import Job

from app.services.job_tasks import execute_job


DEFAULT_QUEUE_NAME = "thermoform"
CAE_QUEUE_NAME = "thermoform-cae"


def queue_name_for_task(task: str) -> str:
    return (
        CAE_QUEUE_NAME
        if task in {"cae", "cae_mesh", "cae_smoke", "cae_solve", "cae_campaign", "cae_mesh_study", "cae_benchmark"}
        else DEFAULT_QUEUE_NAME
    )


class JobQueue(Protocol):
    def enqueue(self, task: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def get(self, job_id: str) -> dict[str, Any]: ...
    def cancel(self, job_id: str) -> dict[str, Any]: ...


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class RqJobQueue:
    def __init__(self, redis_url: str | None = None):
        self.connection = Redis.from_url(
            redis_url or os.getenv("THERMOFORM_REDIS_URL", "redis://localhost:6379/0")
        )
        self.queues = {
            DEFAULT_QUEUE_NAME: Queue(DEFAULT_QUEUE_NAME, connection=self.connection, default_timeout=7200),
            CAE_QUEUE_NAME: Queue(CAE_QUEUE_NAME, connection=self.connection, default_timeout=21600),
        }

    def enqueue(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        queue_name = queue_name_for_task(task)
        job = self.queues[queue_name].enqueue_call(
            func=execute_job,
            args=(task, payload),
            meta={"task": task, "progress": 0, "stage": "queued", "queue": queue_name},
            result_ttl=86400,
            failure_ttl=604800,
        )
        return self._snapshot(job)

    def get(self, job_id: str) -> dict[str, Any]:
        job = Job.fetch(job_id, connection=self.connection)
        return self._snapshot(job, refresh=True)

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = Job.fetch(job_id, connection=self.connection)
        current_status = job.get_status(refresh=True)
        if current_status in {"queued", "deferred", "scheduled"}:
            job.cancel()
        elif current_status == "started":
            job.meta.update({"cancel_requested": True, "stage": "cancel_requested"})
            job.save_meta()
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
            "progress": job.meta.get("progress", 0),
            "stage": job.meta.get("stage", status),
            "queue": job.meta.get("queue", job.origin),
            "cancel_requested": bool(job.meta.get("cancel_requested", False)),
        }


def get_job_queue() -> JobQueue:
    return RqJobQueue()
