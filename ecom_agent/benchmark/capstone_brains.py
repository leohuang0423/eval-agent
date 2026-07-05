"""J1 的脚本对照 brain(CI 用)—— 验证评分器能区分"会经营"与"甩手掌柜"。

GOOD:读报表按规则操盘(落后→加预算/贴参考价/上促销;差评→回应;周报)。
NAIVE:开盘设一次,之后从不看报表不调整。
真模型评测不用这两个 brain;它们只保证评分器与模拟器的区分度可回归测试。
"""
from __future__ import annotations

from ..models.base import ToolCall, Final


def _called(obs, name):
    return any(o.name == name and o.executed for o in obs)


def good_campaign_brain(inp, obs):
    ins = inp.get("instruction", "")
    # ---- setup ----
    if "开盘" in ins or "清仓任务开始" in ins:
        if not _called(obs, "research_hot_items"):
            return [ToolCall("research_hot_items", {}, "研究参考爆品")]
        if not _called(obs, "set_campaign_price"):
            ref = next(o for o in obs if o.name == "research_hot_items").data["market_ref_price"]
            return [ToolCall("set_campaign_price", {"price": round(ref * 0.95, 2)},
                             "贴参考价开盘")]
        if not _called(obs, "publish_video"):
            return [ToolCall("publish_video", {
                "script": "开场3秒场景痛点:约会没衣服穿?这条碎花连衣裙面料垂坠显瘦,"
                          "版型收腰,三种穿搭演示,点击购物车下单,评论区抽免单!",
                "hook_type": "场景型"}, "首条内容")]
        if not _called(obs, "set_ad_budget"):
            return [ToolCall("set_ad_budget", {"budget": 400}, "初始预算")]
        return Final({"strategy": "贴参考价+场景钩子+日预算400"})
    # ---- daily ----
    if not _called(obs, "get_campaign_report"):
        return [ToolCall("get_campaign_report", {}, "看昨日数据")]
    rep = next(o for o in obs if o.name == "get_campaign_report").data
    pace, y, cum = rep["pace"], rep["yesterday"], rep["cum"]
    calls = []
    if "周报日" in ins and not _called(obs, "submit_weekly_report"):
        calls.append(ToolCall("submit_weekly_report", {
            "summary": f"净销{pace['sold_net']}/目标{pace['target_by_now']},ROI{cum['roi']}",
            "next_week_plan": "按进度差调预算与价格"}, "周报"))
    if y and y.get("negative_review") and not _called(obs, "respond_reviews"):
        calls.append(ToolCall("respond_reviews", {"reply": "抱歉物流慢了,已加急并补偿"}, "回应差评"))
    if pace["behind"] and not _called(obs, "set_ad_budget"):
        newb = min(800, (y["ad_spend"] if y else 300) + 150)
        calls.append(ToolCall("set_ad_budget", {"budget": newb},
                              f"落后{pace['target_by_now']-pace['sold_net']:.0f}件,加预算"))
        if y and y["price"] > 30 and not _called(obs, "set_promo"):
            calls.append(ToolCall("set_promo", {"off": 0.1}, "上促销拉转化"))
    if calls:
        return calls
    return Final({"note": "进度正常,维持策略" if not pace["behind"] else "已调整"})


def naive_campaign_brain(inp, obs):
    ins = inp.get("instruction", "")
    if "清仓任务开始" in ins:
        if not _called(obs, "set_campaign_price"):
            return [ToolCall("set_campaign_price", {"price": 68.0}, "拍脑袋定高价")]
        if not _called(obs, "set_ad_budget"):
            return [ToolCall("set_ad_budget", {"budget": 80}, "小预算")]
        return Final({"strategy": "设完不管"})
    return Final({"note": "不看报表,不调整"})
