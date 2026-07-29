from src.core.handlers.discussion_handler import extract_hn_submission_text


def test_extract_hn_submission_text_excludes_comments() -> None:
    discussion = "标题: Show HN\n\n链接: https://example.com\n\n正文: " + ("Author post. " * 12) + "\n\n评论 (共找到 2 条):\n\nreader: A comment"

    assert extract_hn_submission_text(discussion) == ("Author post. " * 12).strip()


def test_extract_hn_submission_text_requires_an_author_post() -> None:
    assert extract_hn_submission_text("标题: Show HN\n\n评论 (共找到 1 条):\n\nreader: A comment") == ""
