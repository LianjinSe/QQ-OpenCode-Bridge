"""Shared task states and legal runtime transitions."""

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    SUBMITTING = "submitting"
    RUNNING = "running"
    WAITING = "waiting"
    CANCELLING = "cancelling"
    REPLY_READY = "reply_ready"
    DELIVERING = "delivering"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SEND_UNCERTAIN = "send_uncertain"
    SEND_FAILED = "send_failed"
    STEERING = "steering"
    STEERED = "steered"


TERMINAL_STATUSES = frozenset(
    {
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.SEND_UNCERTAIN,
        JobStatus.SEND_FAILED,
    }
)
ACTIVE_TOOL_STATUSES = (JobStatus.SUBMITTING, JobStatus.RUNNING, JobStatus.WAITING)
PREPARATION_STATUSES = (JobStatus.QUEUED, JobStatus.PREPARING)
RUNNABLE_STATUSES = (
    JobStatus.QUEUED,
    JobStatus.PREPARING,
    JobStatus.SUBMITTING,
    JobStatus.RUNNING,
    JobStatus.WAITING,
    JobStatus.CANCELLING,
)

TRANSITIONS = {
    JobStatus.QUEUED: frozenset(
        {JobStatus.PREPARING, JobStatus.CANCELLING, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.PREPARING: frozenset(
        {
            JobStatus.PREPARING,
            JobStatus.SUBMITTING,
            JobStatus.WAITING,
            JobStatus.CANCELLING,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.SUBMITTING: frozenset(
        {
            JobStatus.SUBMITTING,
            JobStatus.RUNNING,
            JobStatus.WAITING,
            JobStatus.CANCELLING,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.RUNNING,
            JobStatus.WAITING,
            JobStatus.CANCELLING,
            JobStatus.REPLY_READY,
            JobStatus.DELIVERING,
            JobStatus.DONE,
            JobStatus.FAILED,
        }
    ),
    JobStatus.WAITING: frozenset(
        {
            JobStatus.WAITING,
            JobStatus.RUNNING,
            JobStatus.CANCELLING,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.CANCELLING: frozenset({JobStatus.CANCELLING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.REPLY_READY: frozenset(
        {
            JobStatus.DELIVERING,
            JobStatus.DONE,
            JobStatus.CANCELLED,
            JobStatus.SEND_UNCERTAIN,
            JobStatus.SEND_FAILED,
        }
    ),
    JobStatus.DELIVERING: frozenset(
        {
            JobStatus.DELIVERING,
            JobStatus.DONE,
            JobStatus.CANCELLED,
            JobStatus.SEND_UNCERTAIN,
            JobStatus.SEND_FAILED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.STEERING: frozenset({JobStatus.STEERED, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.STEERED: TERMINAL_STATUSES,
    JobStatus.DONE: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.SEND_UNCERTAIN: frozenset(),
    JobStatus.SEND_FAILED: frozenset(),
}


def validate_transition(current: str, target: str) -> None:
    try:
        source_state, target_state = JobStatus(current), JobStatus(target)
    except ValueError as exc:
        raise ValueError(f"Unknown job status transition: {current} -> {target}") from exc
    if target_state not in TRANSITIONS[source_state]:
        raise ValueError(f"Illegal job status transition: {source_state} -> {target_state}")
