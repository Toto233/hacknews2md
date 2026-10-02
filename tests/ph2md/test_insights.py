from __future__ import annotations

import json
from pathlib import Path

import pytest

from ph2md.insights import InsightPlanError, draft_plan_payload, load_insight_plan
from ph2md.models import Product


def _products() -> list[Product]:
    return [
        Product(
            year=2026,
            month=8,
            rank=index,
            name=f"Product {index}",
            producthunt_url=f"https://www.producthunt.com/products/product-{index}",
            tagline=f"Product-specific workflow {index}",
            votes=500 - index,
            comments=20 + index,
            categories=["Productivity"],
        )
        for index in range(1, 12)
    ]


def _valid_plan() -> dict[str, object]:
    products = _products()
    payload = draft_plan_payload(products, 2026, 8)
    observations = [
        "Product 1 把创始人日程协调前移到主动提醒，重点不在回答问题，而在减少会前准备和跟进遗漏。",
        "Product 2 面向本地视频素材建立检索入口，让剪辑代理能先定位片段，再进入后续编排和导出步骤。",
        "Product 3 将广告创意生成绑定到社交投放场景，价值取决于素材迭代是否能跟转化反馈形成闭环。",
        "Product 4 用创作者协作推动企业品牌传播，产品切入点是把内容生产、分发和效果跟踪放到同一流程。",
        "Product 5 关注会议记录中的细节保真，说明笔记工具的竞争正从转写速度转向信息是否可直接使用。",
        "Product 6 以开源方式提供语音代理基础设施，给需要自托管和深度定制的开发团队增加了一个选择。",
        "Product 7 把 AI 队友包装成可分派真实任务的工作单元，衡量标准会从聊天体验转向任务完成质量。",
        "Product 8 处理个人工作成果的持续记录，尝试把零散贡献转成晋升沟通时可调用的证据清单。",
        "Product 9 主张让软件自主处理维护任务，切中了工程团队希望减少重复排障和手工操作的需求。",
        "Product 10 让 CRM 自动建立客户上下文并推进动作，目标是减少销售人员维护字段和补录数据的负担。",
    ]
    risks = [
        "Product 1 需要谨慎处理日历、邮件等高权限数据；主动执行一旦判断错误，会直接打乱创始人的工作安排。",
        "Product 2 的效果受本地素材规模、索引速度和片段识别精度共同影响，超大视频库可能暴露性能瓶颈。",
        "Product 3 容易把短期点击率当成创意质量，还要防止生成内容同质化以及平台广告政策带来的限制。",
        "Product 4 依赖创作者供给和品牌调性匹配，若归因链路不清晰，企业很难判断传播是否带来业务结果。",
        "Product 5 必须区分说话人、上下文和行动项；细节一旦记错，用户会比面对普通转写错误更难察觉。",
        "Product 6 虽然开源降低了进入门槛，但部署、电话网络、延迟和合规责任仍会落到采用它的团队身上。",
        "Product 7 的授权范围越大，误操作成本越高；产品必须给出任务边界、审批节点和可追溯执行记录。",
        "Product 8 涉及敏感绩效信息，既要避免把可见度游戏化，也要确保记录不会脱离团队协作的真实语境。",
        "Product 9 所谓自主运行必须有明确回滚和人工接管机制，否则一次错误修复就可能放大成生产事故。",
        "Product 10 若自动补全依赖不准确的数据源，错误会沿销售流程传播；权限隔离和数据可解释性是关键。",
    ]
    for index, item in enumerate(payload["items"]):
        item["observation"] = observations[index]
        item["risk"] = risks[index]
    return payload


def test_load_insight_plan_accepts_complete_distinct_plan(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_valid_plan(), ensure_ascii=False), encoding="utf-8")

    insights = load_insight_plan(path, _products(), 2026, 8)

    assert len(insights) == 10
    assert insights[1].name == "Product 1"


def test_load_insight_plan_rejects_banned_fallback_phrase(tmp_path: Path) -> None:
    payload = _valid_plan()
    payload["items"][0]["observation"] = (
        "这个产品覆盖一个明确场景，排名靠前说明这个痛点在 PH 社区有明确需求，后续还要继续验证。"
    )
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(InsightPlanError, match="banned fallback phrase"):
        load_insight_plan(path, _products(), 2026, 8)


def test_load_insight_plan_rejects_missing_top10_item(tmp_path: Path) -> None:
    payload = _valid_plan()
    payload["items"].pop()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(InsightPlanError, match="missing Top 10 ranks"):
        load_insight_plan(path, _products(), 2026, 8)


def test_load_insight_plan_rejects_repeated_long_clause(tmp_path: Path) -> None:
    payload = _valid_plan()
    repeated = "需要验证它能否稳定进入目标用户每天真实使用的工作链路"
    payload["items"][0]["risk"] = f"Product 1 {repeated}，并控制数据权限与恢复成本。"
    payload["items"][1]["risk"] = f"Product 2 {repeated}，还要观察长期留存和付费表现。"
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(InsightPlanError, match="repeats a long phrase"):
        load_insight_plan(path, _products(), 2026, 8)
