from __future__ import annotations

from hn2md.headline import RECAP_HEADLINE_LIMIT
from hn2md.stages.post_publish_audit import _check_keyword_warnings
from hn2md.stages.publish import _keyword_locations, _sentence_for_keyword


def test_sentence_for_keyword_preserves_decimal_numbers() -> None:
    line = "此前发生风波，涉中国背景争议导致股价较收盘价 186.64 美元一度暴跌近 33%。次日反弹。"
    sentence = _sentence_for_keyword(line, "中国")
    assert sentence == "此前发生风波，涉中国背景争议导致股价较收盘价 186.64 美元一度暴跌近 33%。"


def test_sentence_for_keyword_still_splits_on_real_english_period() -> None:
    line = "First sentence ends here. Second sentence mentions keyword中国 and 1.5x growth. Third sentence."
    sentence = _sentence_for_keyword(line, "中国")
    assert sentence == "Second sentence mentions keyword中国 and 1.5x growth."


def test_rendered_heading_reuses_checked_chinese_title_keyword_decision() -> None:
    md = "## 1. 丰田、日产与本田联合推进零部件标准化，抱团降本应对中国车企竞争 (Toyota, Nissan, and Honda to standardize parts to lower costs)\n"
    warnings = _keyword_locations(md, ["中国"], "summary.md")
    assert len(warnings) == 1
    assert "丰田、日产与本田联合推进零部件标准化，抱团降本应对中国车企竞争" in warnings[0].get("legacy_sentences", [])

    decisions = [
        {
            "keyword": "中国",
            "sentence": "丰田、日产与本田联合推进零部件标准化，抱团降本应对中国车企竞争",
            "classification": "positive",
            "decision": "approved",
        }
    ]
    findings = _check_keyword_warnings({"keyword_warnings": warnings}, "20261124", decisions)
    assert len(findings) == 1
    assert findings[0]["severity"] == "info"
    assert "All 1 keyword context(s) have recorded decisions" in findings[0]["message"]


def test_rendered_heading_still_flags_changed_chinese_title() -> None:
    md = "## 1. 修改后的中国车企竞争标题 (Original English Title)\n"
    warnings = _keyword_locations(md, ["中国"], "summary.md")
    decisions = [
        {
            "keyword": "中国",
            "sentence": "旧的中国车企竞争标题",
            "classification": "positive",
            "decision": "approved",
        }
    ]
    findings = _check_keyword_warnings({"keyword_warnings": warnings}, "20261124", decisions)
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"


def test_recap_headline_boundary_constant_matches_story_status_contract() -> None:
    assert RECAP_HEADLINE_LIMIT == 34
    assert len("a" * 34) <= RECAP_HEADLINE_LIMIT
    assert len("a" * 35) > RECAP_HEADLINE_LIMIT
