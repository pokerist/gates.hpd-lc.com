from __future__ import annotations

import os
from typing import Optional

from redis import Redis
from rq import Queue

from core import tasks


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()


def _queue_name() -> str:
    return os.getenv("RQ_QUEUE", "gates").strip() or "gates"


def _job_timeout() -> int:
    value = os.getenv("RQ_JOB_TIMEOUT", "180").strip()
    try:
        return int(value)
    except Exception:
        return 180


def enqueue_registration(
    raw_path: str,
    original_card_filename: Optional[str],
    placeholder_nid: Optional[str] = None,
    gate_number: Optional[int] = None,
) -> Optional[str]:
    url = _redis_url()
    if not url:
        return None
    try:
        conn = Redis.from_url(url)
        queue = Queue(_queue_name(), connection=conn, default_timeout=_job_timeout())
        job = queue.enqueue(
            tasks.register_person_job,
            raw_path,
            original_card_filename,
            placeholder_nid,
            gate_number,
            job_timeout=_job_timeout(),
        )
        print(f"[RQ] Enqueued job {job.id}")
        return job.id
    except Exception as exc:
        print(f"[RQ] Failed to enqueue job: {exc}")
        return None


def enqueue_reprocess(national_id: str, direction: str) -> Optional[str]:
    url = _redis_url()
    if not url:
        return None


def enqueue_reprocess_by_id(record_id: int, direction: str) -> Optional[str]:
    url = _redis_url()
    if not url:
        return None
    try:
        conn = Redis.from_url(url)
        queue = Queue(_queue_name(), connection=conn, default_timeout=_job_timeout())
        job = queue.enqueue(
            tasks.reprocess_person_job_by_id,
            record_id,
            direction,
            job_timeout=_job_timeout(),
        )
        print(f"[RQ] Enqueued job {job.id}")
        return job.id
    except Exception as exc:
        print(f"[RQ] Failed to enqueue job: {exc}")
        return None
    try:
        conn = Redis.from_url(url)
        queue = Queue(_queue_name(), connection=conn, default_timeout=_job_timeout())
        job = queue.enqueue(
            tasks.reprocess_person_job,
            national_id,
            direction,
            job_timeout=_job_timeout(),
        )
        print(f"[RQ] Enqueued job {job.id}")
        return job.id
    except Exception as exc:
        print(f"[RQ] Failed to enqueue job: {exc}")
        return None
