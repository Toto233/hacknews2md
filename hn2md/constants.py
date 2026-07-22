"""Constants used across the hn2md CLI."""

from enum import Enum


class Stage(str, Enum):
    IDLE = "IDLE"
    FETCHING = "FETCHING"
    COLLECTING = "COLLECTING"
    CAPTURING = "CAPTURING"
    PLANNING = "PLANNING"
    APPLYING = "APPLYING"
    RENDERING = "RENDERING"
    COVERING = "COVERING"
    PUBLISHING = "PUBLISHING"
    DONE = "DONE"
    FAILED = "FAILED"


STAGE_ORDER = [
    Stage.FETCHING,
    Stage.COLLECTING,
    Stage.CAPTURING,
    Stage.PLANNING,
    Stage.APPLYING,
    Stage.RENDERING,
    Stage.COVERING,
    Stage.PUBLISHING,
]

RETRY_BUDGETS = {
    Stage.FETCHING: 3,
    Stage.COLLECTING: 2,
    Stage.CAPTURING: 0,
    Stage.PLANNING: 2,
    Stage.APPLYING: 1,
    Stage.RENDERING: 1,
    Stage.COVERING: 2,
    Stage.PUBLISHING: 2,
}

LOCK_STALE_SECONDS = 3600  # 1 hour
