from __future__ import annotations

from enum import Enum


class GenericStage(str, Enum):
    FETCHING = "FETCHING"
    COLLECTING = "COLLECTING"
    CAPTURING = "CAPTURING"
    ENRICHING = "ENRICHING"
    PLANNING = "PLANNING"
    APPLYING = "APPLYING"
    RENDERING = "RENDERING"
    COVERING = "COVERING"
    PUBLISHING = "PUBLISHING"
