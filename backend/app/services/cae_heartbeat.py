import json
import threading
from datetime import UTC, datetime
from typing import Any

from app.repositories.artifacts import ArtifactRepository
from app.services.cae_resume import RESUME_ATTEMPT_PATTERN


RESUME_HEARTBEAT_FILENAME = "resume-heartbeat.json"


def write_resume_heartbeat(
    repository: ArtifactRepository,
    resume_attempt_id: str,
    *,
    stage: str,
    active: bool = True,
    **details: Any,
) -> dict[str, Any]:
    if not RESUME_ATTEMPT_PATTERN.fullmatch(resume_attempt_id):
        raise ValueError("Invalid resume attempt ID")
    heartbeat = {
        "resume_attempt_id": resume_attempt_id,
        "stage": stage,
        "active": active,
        "heartbeat_at": datetime.now(UTC).isoformat(),
        **details,
    }
    repository.replace_cae_artifact(
        resume_attempt_id,
        RESUME_HEARTBEAT_FILENAME,
        json.dumps(heartbeat, indent=2, sort_keys=True),
    )
    return heartbeat


def load_resume_heartbeat(
    repository: ArtifactRepository, resume_attempt_id: str
) -> dict[str, Any] | None:
    if not RESUME_ATTEMPT_PATTERN.fullmatch(resume_attempt_id):
        return None
    try:
        path = repository.cae_artifact_path(
            resume_attempt_id, RESUME_HEARTBEAT_FILENAME
        )
        heartbeat = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(heartbeat, dict)
        or heartbeat.get("resume_attempt_id") != resume_attempt_id
        or not isinstance(heartbeat.get("heartbeat_at"), str)
    ):
        return None
    return heartbeat


class ResumeAttemptHeartbeat:
    def __init__(
        self,
        repository: ArtifactRepository,
        resume_attempt_id: str,
        *,
        interval_seconds: float = 30.0,
        job_id: str | None = None,
    ):
        if interval_seconds <= 0:
            raise ValueError("Heartbeat interval must be positive")
        self.repository = repository
        self.resume_attempt_id = resume_attempt_id
        self.interval_seconds = interval_seconds
        self.job_id = job_id
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._state: dict[str, Any] = {"stage": "starting", "active": True}
        self._thread: threading.Thread | None = None

    def _write(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        with self._write_lock:
            return write_resume_heartbeat(
                self.repository,
                self.resume_attempt_id,
                job_id=self.job_id,
                heartbeat_interval_seconds=self.interval_seconds,
                **state,
            )

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._write()

    def start(self, stage: str = "starting", **details: Any) -> None:
        if self._thread is not None:
            return
        self.update(stage, **details)
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self.resume_attempt_id}",
            daemon=True,
        )
        self._thread.start()

    def update(self, stage: str, *, active: bool = True, **details: Any) -> None:
        with self._lock:
            self._state = {"stage": stage, "active": active, **details}
        self._write()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 1.0))
            self._thread = None
