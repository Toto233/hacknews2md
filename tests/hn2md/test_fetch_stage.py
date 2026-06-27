from datetime import datetime

from hn2md.constants import Stage
from hn2md.state import JobStateMachine, PublishJob
from hn2md.stages.fetch import FetchStage


def test_fetch_stage_records_saved_story_metadata_in_ledger(tmp_path, monkeypatch) -> None:
    now = datetime.now().isoformat()
    job = PublishJob(date="20260627", status=Stage.FETCHING.value, created_at=now, updated_at=now)
    machine = JobStateMachine(job, tmp_path / "publish_job_20260627.json")
    items = [
        {"id": 1, "title": "One", "url": "https://example.com/1"},
        {"id": 2, "title": "Two", "url": "https://example.com/2"},
    ]

    monkeypatch.setattr("src.utils.db_utils.init_database", lambda: None)
    monkeypatch.setattr("src.core.archive_news.archive_old_news", lambda: None)
    monkeypatch.setattr("src.core.fetch_news.fetch_news", lambda: items)
    monkeypatch.setattr("src.core.fetch_news.save_to_database", lambda fetched: len(fetched))

    result = FetchStage().execute(object(), machine)

    assert result == {"fetched": 2, "saved": 2}
    assert machine.job.stories == [
        {"id": 1, "title": "One", "url": "https://example.com/1"},
        {"id": 2, "title": "Two", "url": "https://example.com/2"},
    ]
