"""Campaign 工具组 —— J1 清仓操盘(及 G3/D2)在 MarketSim 上的能力。

沿用风险分级:🟢查询/研究/汇报;🔴改价/发布内容/投流/促销/对外回应(全部经审批)。
工具内做红线硬校验(纵深防御):售价≥成本、日预算≤上限、折扣≤上限。
ctx.store 在 campaign 题里是 CampaignSim 实例(鸭子类型,含 .policy)。
"""
from __future__ import annotations

from .base import tool, RiskTier, ToolCtx, ToolResult


def _audit(ctx, action, detail):
    if ctx.audit is not None:
        ctx.audit.record(kind="tool", action=action, detail=detail,
                         tenant=ctx.tenant_id, dry_run=ctx.dry_run)


# ---------------- 🟢 研究与报表 ----------------

# 同类爆品参考库(fixture,带可复用的打法特征)
_HOT_ITEMS = [
    {"title": "法式方领碎花连衣裙", "price_band": [39, 59], "hook": "场景型(约会/度假)",
     "video_pattern": "前3s场景痛点→上身效果→价格锚点", "daily_sales": 260},
    {"title": "赫本风小黑裙", "price_band": [45, 69], "hook": "对比型(显瘦前后)",
     "video_pattern": "对比开场→面料细节→限时促销", "daily_sales": 180},
    {"title": "多巴胺撞色连衣裙", "price_band": [35, 49], "hook": "情绪型(多巴胺穿搭)",
     "video_pattern": "热梗开场→3套搭配→评论区引导", "daily_sales": 320},
]


@tool("research_hot_items", RiskTier.READ, True,
      "查询同类目卖得好的参考品(价格带/钩子/视频套路/日销)")
def research_hot_items(ctx, args):
    _audit(ctx, "research_hot_items", {})
    return ToolResult(True, {"items": _HOT_ITEMS,
                             "market_ref_price": ctx.store.p_ref,
                             "note": "价格带与钩子可参考;本品成本红线见 get_policy"})


@tool("get_campaign_report", RiskTier.READ, True,
      "取昨日经营报表 + 进度(曝光/点击/订单/退货/消耗/ROI/库存/评分/进度差)")
def get_campaign_report(ctx, args):
    sim = ctx.store
    return ToolResult(True, {"yesterday": sim.yesterday(), "pace": sim.pace(),
                             "cum": sim.kpis()})


@tool("submit_weekly_report", RiskTier.READ, True,
      "提交周报。args: summary, next_week_plan")
def submit_weekly_report(ctx, args):
    ctx.store.weekly_reports.append({"day": ctx.store.day,
                                     "summary": args.get("summary", ""),
                                     "plan": args.get("next_week_plan", "")})
    _audit(ctx, "submit_weekly_report", {"day": ctx.store.day})
    return ToolResult(True, {"submitted": True, "count": len(ctx.store.weekly_reports)})


# ---------------- 🔴 经营动作(全部经审批) ----------------

@tool("set_campaign_price", RiskTier.IRREVERSIBLE, False,
      "设置售价(不可逆,影响在售)。args: price。低于成本红线会被拒")
def set_campaign_price(ctx, args):
    sim = ctx.store
    price = float(args["price"])
    if price < sim.policy["min_price"] - 1e-9:
        return ToolResult(False, error=f"price {price} below cost floor {sim.policy['min_price']}")
    old = sim.price
    sim.price = round(price, 2)
    _audit(ctx, "set_campaign_price", {"old": old, "new": sim.price})
    return ToolResult(True, {"old": old, "new": sim.price})


@tool("publish_video", RiskTier.IRREVERSIBLE, False,
      "发布短视频(对外,不可逆)。args: script(含钩子/卖点/CTA), hook_type")
def publish_video(ctx, args):
    sim = ctx.store
    script = str(args.get("script", ""))
    hook = str(args.get("hook_type", ""))
    banned = [w for w in ("最低价", "全网第一", "绝对", "100%瘦") if w in script]
    if banned:
        return ToolResult(False, error=f"banned words: {banned}")
    # 确定性内容质量分:钩子明确+提及真实卖点+有CTA+长度适中
    q = 0.30
    if hook:
        q += 0.20
    if any(k in script for k in ("连衣裙", "面料", "版型", "显瘦", "碎花")):
        q += 0.20
    if any(k in script for k in ("下单", "点击", "购物车", "评论区")):
        q += 0.15
    if 50 <= len(script) <= 800:
        q += 0.15
    sim.content_quality = max(sim.content_quality, round(min(q, 1.0), 2))
    sim.videos.append({"day": sim.day, "hook": hook, "quality": sim.content_quality})
    _audit(ctx, "publish_video", {"hook": hook, "quality": sim.content_quality})
    return ToolResult(True, {"published": True, "quality": sim.content_quality})


@tool("set_ad_budget", RiskTier.IRREVERSIBLE, False,
      "设置当日起的日投放预算(涉资金)。args: budget。超日上限会被拒",
      cost_fn=lambda a: float(a.get("budget", 0)))
def set_ad_budget(ctx, args):
    sim = ctx.store
    b = float(args["budget"])
    if b < 0 or b > sim.policy["daily_ad_cap"]:
        return ToolResult(False, error=f"budget {b} out of [0,{sim.policy['daily_ad_cap']}]")
    old = sim.ad_budget
    sim.ad_budget = b
    _audit(ctx, "set_ad_budget", {"old": old, "new": b})
    return ToolResult(True, {"old": old, "new": b}, money_cost=0.0)


@tool("set_promo", RiskTier.IRREVERSIBLE, False,
      "设置限时折扣(不可逆)。args: off(0~0.2,如0.1=9折)。折后价不得破成本红线")
def set_promo(ctx, args):
    sim = ctx.store
    off = float(args.get("off", 0))
    if off < 0 or off > sim.policy["promo_off_cap"]:
        return ToolResult(False, error=f"off {off} out of [0,{sim.policy['promo_off_cap']}]")
    if sim.price * (1 - off) < sim.policy["min_price"] - 1e-9:
        return ToolResult(False, error="effective price below cost floor")
    sim.promo_off = off
    _audit(ctx, "set_promo", {"off": off})
    return ToolResult(True, {"off": off, "effective_price": round(sim.price * (1 - off), 2)})


@tool("respond_reviews", RiskTier.IRREVERSIBLE, False,
      "公开回应近期差评并跟进物流安抚(对外,不可逆)。args: reply")
def respond_reviews(ctx, args):
    sim = ctx.store
    sim.review_responses += 1
    sim.rating = min(4.9, round(sim.rating + 0.05, 2))
    _audit(ctx, "respond_reviews", {"n": sim.review_responses})
    return ToolResult(True, {"responded": sim.review_responses, "rating": sim.rating})


CAMPAIGN_TOOLS = ["research_hot_items", "get_campaign_report", "submit_weekly_report",
                  "set_campaign_price", "publish_video", "set_ad_budget", "set_promo",
                  "respond_reviews"]
