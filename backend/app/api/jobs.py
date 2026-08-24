import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError

from app.domain.jobs import JobCreateRequest, JobSnapshot
from app.services.jobs import JobQueue, get_job_queue


router = APIRouter(prefix="/api/v1")
ws_router = APIRouter()


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


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str, queue: JobQueue = Depends(get_job_queue)) -> dict:
    try:
        snapshot = queue.get(job_id)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Job queue is unavailable") from exc
    if snapshot["status"] == "failed":
        raise HTTPException(
            status_code=422,
            detail={"job_id": job_id, "status": "failed", "error": snapshot.get("error")},
        )
    if snapshot["status"] != "finished":
        raise HTTPException(
            status_code=409,
            detail={"job_id": job_id, "status": snapshot["status"], "stage": snapshot.get("stage")},
        )
    return {
        "job_id": job_id,
        "status": "completed",
        "result": snapshot.get("result"),
        "error": None,
    }


@router.websocket("/ws/jobs/{job_id}")
@ws_router.websocket("/ws/jobs/{job_id}")
async def stream_job(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    queue = get_job_queue()
    try:
        while True:
            try:
                snapshot = queue.get(job_id)
            except NoSuchJobError:
                await websocket.send_json({"job_id": job_id, "status": "not_found"})
                await websocket.close(code=4404)
                return
            except RedisError:
                await websocket.send_json({"job_id": job_id, "status": "queue_unavailable"})
                await websocket.close(code=1013)
                return
            await websocket.send_json(JobSnapshot(**snapshot).model_dump(mode="json"))
            if snapshot["status"] in {"finished", "failed", "stopped", "canceled"}:
                await websocket.close(code=1000)
                return
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


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
