"""A rejected /front request must not consume the publisher's retry budget."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest
import requests

from hn2md.constants import Stage
from hn2md.stages.base import NonRetryableStageError
from hn2md.state import JobStateMachine, PublishJob
from publisher.sources.hackernews import BrowserFrontFetchStage


def test_publisher_419_fails_fast_with_browser_recovery(tmp_path, monkeypatch) -> None:
    now = datetime.now().isoformat()
    job = PublishJob(date="20261003", status=Stage.FETCHING.value, created_at=now, updated_at=now)
    machine = JobStateMachine(job, tmp_path / "publish_job_20261003.json")
    fetch = Mock(side_effect=requests.HTTPError("HN /front returned 419", response=Mock(status_code=419)))

    monkeypatch.setattr("src.utils.db_utils.init_database", lambda: None)
    monkeypatch.setattr("src.core.archive_news.archive_old_news", lambda: None)
    monkeypatch.setattr("src.core.fetch_news.fetch_news", fetch)
    monkeypatch.setattr("time.sleep", lambda _seconds: pytest.fail("419 must not sleep before retry"))

    with pytest.raises(NonRetryableStageError, match="--front-ids"):
        BrowserFrontFetchStage().run(object(), machine)

    fetch.assert_called_once()
