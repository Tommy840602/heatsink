from fastapi import APIRouter, Depends, status

from app.domain.agent import EngineeringAgentRequest
from app.domain.jobs import JobSnapshot
from app.services.jobs import JobQueue, get_job_queue


router = APIRouter(prefix="/api/v1", tags=["engineering-agent"])
@router.post("/agent/execute", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def execute_agent(request: EngineeringAgentRequest, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    return JobSnapshot(**queue.enqueue("agent", request.model_dump(mode="json")))
