from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_JOB_ID = "metafin_incremental_scan"


def start(schedule: str, scan_fn) -> None:
    global _scheduler
    tz = os.environ.get("TZ", "UTC") or "UTC"
    _scheduler = BackgroundScheduler(timezone=tz)
    if schedule:
        _scheduler.add_job(
            scan_fn,
            CronTrigger.from_crontab(schedule),
            id=_JOB_ID,
            replace_existing=True,
        )
        log.info("Scheduled incremental scan: %s", schedule)
    _scheduler.start()


def reschedule(schedule: str, scan_fn) -> None:
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(_JOB_ID)
    except Exception:  # noqa: S110
        pass
    if schedule:
        _scheduler.add_job(
            scan_fn,
            CronTrigger.from_crontab(schedule),
            id=_JOB_ID,
            replace_existing=True,
        )
        log.info("Rescheduled incremental scan: %s", schedule)


def next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_JOB_ID)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def stop() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
