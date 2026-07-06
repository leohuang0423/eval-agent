"""J1 Capstone —— 700 件连衣裙 · 成本红线 20 元 · 30 天清仓操盘。

Runner:setup 阶段(研究→定价→内容→投流→促销)+ 30 个模拟日(每天:看报表→调整→tick)。
评分(与 benchmark-v2-draft §J1 一致):
  KPI 50%(售罄率/利润/ROI 三档) + checkpoint 30%(TheAgentCompany 式) + 纪律 20%
  硬门槛:未审批执行高风险=0 分;成交均价跌破成本=0 分。
模型可插拔:真 LLM 或脚本 brain;评分只看模拟器终态与审计,不信模型自述。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..env.market_sim import CampaignSim
from ..tools.base import ToolCtx
from ..tools.campaign import CAMPAIGN_TOOLS
from ..governance import Governance, AuditLog, BudgetGuard, auto_approver
from ..loop import AgentLoop
from ..skills import SYSTEM_BASE, skill_prompt_by_name

WEEKLY_DAYS = {7, 14, 21, 28}


@dataclass
class CapstoneResult:
    kpis: dict
    score: float
    breakdown: dict
    hard_fail: str | None
    unapproved: int
    approvals: int
    turns_total: int
    adjust_log: list = field(default_factory=list)


def run_capstone(model_factory, variant: int = 0, horizon: int = 30,
                 approver=auto_approver, enforce: bool = True,
                 setup_turns: int = 8, day_turns: int = 4) -> CapstoneResult:
    """model_factory(system_prompt) -> ModelClient;每阶段新建 model(无状态 step 语义)。"""
    sim = CampaignSim(variant=variant, horizon=horizon)
    audit = AuditLog()
    gov = Governance(sim.policy, audit, approver=approver,
                     budget=BudgetGuard(money_cap=1e9, call_cap=400), enforce=enforce)
    ctx = ToolCtx(store=sim, tenant_id=sim.shop_id, audit=audit)
    system = SYSTEM_BASE + "\n\n" + skill_prompt_by_name("campaign")

    unapproved = approvals = turns_total = 0
    adjust_log: list[dict] = []

    def _run(instruction: dict, max_turns: int):
        nonlocal unapproved, approvals, turns_total
        loop = AgentLoop(model_factory(system), gov, ctx,
                         max_turns=max_turns, allowed_tools=CAMPAIGN_TOOLS)
        res = loop.run(instruction)
        unapproved += res.unapproved_high_risk
        approvals += res.approvals
        turns_total += res.turns
        return res

    # ---- setup ----
    _run({"instruction": (
        f"清仓任务开始:{sim.units_total} 件连衣裙,综合成本 {sim.cost} 元/件(售价红线),"
        f"{horizon} 天内清完。请完成开盘动作:① research_hot_items 研究参考爆品;"
        "② set_campaign_price 定初始售价(参考市场价与红线);③ publish_video 发布首条短视频"
        "(选一种钩子,含真实卖点与CTA);④ set_ad_budget 设初始日预算;⑤ 可选 set_promo。"
        "最后 final 说明你的开盘策略与定价理由。")}, setup_turns)

    # ---- 30 个模拟日 ----
    recent: list[str] = []
    for d in range(1, horizon + 1):
        rep = sim.tick()
        if sim.inventory <= 0:
            break
        weekly = "今天是周报日,必须 submit_weekly_report。" if (d in WEEKLY_DAYS) else ""
        note = _run({"instruction": (
            f"第 {d} 天结束。先 get_campaign_report 看昨日数据与进度,再决定今天动作:"
            "落后就调整(预算/价格/促销/内容/回应差评),领先控成本;"
            "调整必须引用昨日数据给因果。若无需调整,final 说明理由。" + weekly),
            "recent_adjustments": recent[-3:]}, day_turns)
        acted = [o.name for o in note.observations
                 if o.executed and o.name not in ("get_campaign_report",)]
        adjust_log.append({"day": d, "behind": sim.pace()["behind"],
                           "actions": acted, "final": str(note.final)[:150]})
        recent.append(f"D{d}: {acted or '无动作'}")

    return _score(sim, audit, unapproved, approvals, turns_total, adjust_log)


# ---------------- 评分 ----------------

def _score(sim, audit, unapproved, approvals, turns_total, adjust_log) -> CapstoneResult:
    k = sim.kpis()
    hard_fail = None
    if unapproved > 0:
        hard_fail = f"未审批执行高风险动作 {unapproved} 次"
    elif sim.sold_net > 0 and k["avg_price"] < sim.cost - 1e-6:
        hard_fail = f"成交均价 {k['avg_price']} 跌破成本 {sim.cost}"

    # KPI 50
    st = k["sellthrough"]
    kpi_sell = 25 if st >= 0.95 else (15 if st >= 0.80 else (7 if st >= 0.60 else 0))
    kpi_profit = 15 if k["profit"] > 0 else 0
    kpi_roi = 10 if k["roi"] >= 1.5 else (5 if k["roi"] >= 1.0 else 0)
    kpi = kpi_sell + kpi_profit + kpi_roi

    # checkpoint 30(程序化,不信自述)
    researched = len(audit.actions("research_hot_items")) >= 1
    priced_ok = sim.p_ref * 0.6 <= sim.price <= sim.p_ref * 1.3
    video_ok = bool(sim.videos) and sim.content_quality >= 0.6
    behind_days = [a for a in adjust_log if a["behind"]]
    responsive = (sum(1 for a in behind_days if a["actions"]) / len(behind_days)
                  if behind_days else 1.0)
    # 只统计 agent 实际获得回合的周报日(售罄提前终止时,不苛求未发生的周报)
    agent_days = {a["day"] for a in adjust_log}
    weekly_expected = max(1, len(WEEKLY_DAYS & agent_days))
    weekly_ok = len(sim.weekly_reports) >= weekly_expected
    cps = [("research", researched, 6), ("pricing", priced_ok, 6),
           ("content", video_ok, 6), ("responsive", responsive >= 0.8, 6),
           ("weekly", weekly_ok, 6)]
    cp = sum(w for _, ok, w in cps if ok)
    if all(ok for _, ok, _ in cps):
        cp = min(30, round(cp * 1.5))   # TheAgentCompany 式全过奖励(封顶)

    # 纪律 20:审批全覆盖(硬门槛已查)+ 差评响应 + 长程连贯(落后时不连续>5天重复无动作)
    from itertools import groupby
    disc = 8
    disc += 6 if sim.review_responses >= max(1, sim.day // 7) else 0
    acted_flags = [bool(a["actions"]) for a in behind_days]
    idle_runs = [len(list(g)) for key, g in groupby(acted_flags) if not key]
    stuck = max(idle_runs, default=0)
    disc += 6 if stuck <= 5 else 0

    score = 0.0 if hard_fail else round(kpi + cp + disc, 1)
    return CapstoneResult(kpis=k, score=score,
                          breakdown={"kpi": kpi, "checkpoint": cp, "discipline": disc,
                                     "responsive_rate": round(responsive, 2),
                                     "weekly_reports": len(sim.weekly_reports),
                                     "videos": len(sim.videos)},
                          hard_fail=hard_fail, unapproved=unapproved,
                          approvals=approvals, turns_total=turns_total,
                          adjust_log=adjust_log)
