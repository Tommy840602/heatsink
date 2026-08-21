import os

from rq import cron

from app.services.cae_reconciliation import run_resume_watchdog
from app.services.jobs import DEFAULT_QUEUE_NAME


def _watchdog_interval_seconds() -> int:
    try:
        value = int(os.getenv("THERMOFORM_WATCHDOG_INTERVAL_SECONDS", "60"))
    except ValueError:
        return 60
    return min(3600, max(30, value))


cron.register(
    run_resume_watchdog,
    DEFAULT_QUEUE_NAME,
    interval=_watchdog_interval_seconds(),
    job_timeout=120,
    result_ttl=86400,
    failure_ttl=604800,
    name="cae-resume-watchdog",
)
