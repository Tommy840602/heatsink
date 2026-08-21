from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError

from app.domain.jobs import JobCreateRequest, JobSnapshot
from app.services.jobs import JobQueue, get_job_queue


router = APIRouter(prefix="/api/v1")


@router.post("/jobs", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobCreateRequest, queue: JobQueue = Depends(get_job_queue)
) -> JobSnapshot:
    try:
        return JobSnapshot(**queue.enqueue(request.task, request.payload))
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Job queue is unavailable") from exc


@router.get("/jobs/{job_id}", response_model=JobSnapshot)
def get_job(job_id: str, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    try:
        return JobSnapshot(**queue.get(job_id))
    except NoSuchJobError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Job queue is unavailable") from exc


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobSnapshot,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_job(job_id: str, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    try:
        return JobSnapshot(**queue.cancel(job_id))
    except NoSuchJobError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Job queue is unavailable") from exc
