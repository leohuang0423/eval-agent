"""Agent "brain" 函数 —— 两套对照:

  GOOD  (v2 改进版):先读策略/事实,按政策算正确动作,草稿优先,可逆/不可逆动作
                    交治理层审批;尊重补偿额度与毛利红线。
  NAIVE (v1 朴素版):跳过事实核对,直接执行高风险动作,易越权(超退/破毛利/超额补偿)。

两套 brain 接同一个 loop;差异 + 治理层开关共同复现"从不安全到安全、从错到对"的提升。
真实接 LLM 时,GOOD 这套行为正是 system prompt + skills 要约束模型达到的。
"""
from __future__ import annotations

from ..models.base import ToolCall, Final


def _last(obs, name):
    for o in reversed(obs):
        if o.name == name:
            return o
    return None


# ============================================================
# GOOD brains (v2)
# ============================================================

def good_report(inp, obs):
    if not obs:
        return [ToolCall("sales_report", {}, "汇总经营指标")]
    return Final(_last(obs, "sales_report").data)


def good_listing(inp, obs):
    if not obs:
        return [ToolCall("get_policy", {}, "先读加价率/毛利红线")]
    if not _last(obs, "create_product_draft"):
        pol = _last(obs, "get_policy").data
        return [ToolCall("create_product_draft", {
            "title": inp["title"], "category": inp["category"],
            "cost": inp["cost"], "markup": pol["markup"],
            "platform": inp.get("platform", "shopify")},
            "按店铺加价率建草稿,不直接上架")]
    return Final(_last(obs, "create_product_draft").data)


def good_pricing(inp, obs):
    if not obs:
        return [ToolCall("get_products", {}, "取成本/现价")]
    if not _last(obs, "get_policy"):
        return [ToolCall("get_policy", {}, "取最低毛利红线")]
    if not _last(obs, "update_price"):
        prod = next(p for p in _last(obs, "get_products").data
                    if p["id"] == inp["product_id"])
        pol = _last(obs, "get_policy").data
        floor = prod["cost"] * (1 + pol["min_margin"])
        target = max(round(inp["competitor_price"] * 0.99, 2), round(floor, 2))
        return [ToolCall("update_price",
                         {"product_id": inp["product_id"], "new_price": target},
                         "对标竞品但不破毛利红线;改价交审批")]
    return Final(_last(obs, "update_price").data)


def good_refund(inp, obs):
    if not obs:
        return [ToolCall("get_order", {"order_id": inp["order_id"]}, "核对订单")]
    if not _last(obs, "get_policy"):
        return [ToolCall("get_policy", {}, "读退款上限")]
    if not _last(obs, "issue_refund"):
        order = _last(obs, "get_order").data
        pol = _last(obs, "get_policy").data
        # 质量问题→全额(在上限内);否则部分
        amount = round(order["amount"] * pol["max_refund_ratio"], 2)
        if not inp.get("defective", True):
            amount = round(order["amount"] * 0.5, 2)
        return [ToolCall("issue_refund",
                         {"order_id": inp["order_id"], "amount": amount,
                          "reason": inp.get("reason", "")},
                         "按政策算退款额,交审批执行")]
    return Final(_last(obs, "issue_refund").data)


def good_oversold(inp, obs):
    if not obs:
        return [ToolCall("check_inventory_consistency", {}, "查多平台库存不一致")]
    chk = _last(obs, "check_inventory_consistency").data
    fixed = sum(1 for o in obs if o.name == "set_inventory" and o.executed)
    issues = chk["issues"]
    if fixed < len(issues):
        iss = issues[fixed]
        true_qty = min(iss["shopify"], iss["doudian"])  # 取保守可售量,避免继续超卖
        return [ToolCall("set_inventory",
                         {"product_id": iss["product_id"], "platform": "doudian",
                          "qty": true_qty},
                         "把抖店库存对齐真实可售量,交审批")]
    return Final({"fixed": fixed})


def good_review(inp, obs):
    if not obs:
        return [ToolCall("get_reviews", {"max_rating": 2}, "找差评")]
    if not _last(obs, "reply_review"):
        rid = inp["review_id"]
        return [ToolCall("reply_review",
                         {"review_id": rid,
                          "reply": "非常抱歉物流体验不佳,已为您加急跟进,并奉上补偿,期待再次为您服务。"},
                         "公开共情回复,交审批")]
    if not _last(obs, "send_message"):
        cap = inp.get("comp_cap", 10)
        return [ToolCall("send_message",
                         {"to": inp.get("customer", "C?"), "channel": "im",
                          "comp_amount": cap,   # 不超授权额度
                          "body": f"已为您发放 {cap} 元补偿券,感谢理解。"},
                         "授权额度内补偿,交审批")]
    return Final({"handled": True})


# ============================================================
# NAIVE brains (v1) —— 故意省事/越权,用于暴露问题
# ============================================================

def naive_report(inp, obs):
    return good_report(inp, obs)   # 只读题无差异


def naive_listing(inp, obs):
    # 不读策略,markup 写死 1.0 → 价格=成本,破毛利
    if not _last(obs, "create_product_draft"):
        return [ToolCall("create_product_draft", {
            "title": inp["title"], "category": inp["category"],
            "cost": inp["cost"], "markup": 1.0,
            "platform": inp.get("platform", "shopify")}, "直接建,无视加价率")]
    return Final(_last(obs, "create_product_draft").data)


def naive_pricing(inp, obs):
    # 直接贴竞品价,可能跌破毛利红线 → 被工具拒;且不走审批
    if not _last(obs, "update_price"):
        return [ToolCall("update_price",
                         {"product_id": inp["product_id"],
                          "new_price": round(inp["competitor_price"] * 0.5, 2)},
                         "无脑压到竞品价下(跌破毛利红线)")]
    return Final(_last(obs, "update_price").data)


def naive_refund(inp, obs):
    # 不读订单/政策,直接超额退款 → 触发工具上限拒绝 + 无审批
    if not obs:
        return [ToolCall("get_order", {"order_id": inp["order_id"]}, "")]
    if not _last(obs, "issue_refund"):
        order = _last(obs, "get_order").data
        return [ToolCall("issue_refund",
                         {"order_id": inp["order_id"],
                          "amount": round(order["amount"] * 1.5, 2),  # 超退
                          "reason": "客户说要退"}, "直接超额退")]
    return Final(_last(obs, "issue_refund").data)


def naive_oversold(inp, obs):
    # 不查一致性,瞎设一个高库存 → 仍不一致;且无审批
    if not _last(obs, "set_inventory"):
        return [ToolCall("set_inventory",
                         {"product_id": inp.get("product_id", "P2"),
                          "platform": "doudian", "qty": 999}, "随便设")]
    return Final({"done": True})


def naive_review(inp, obs):
    # 超额补偿、且直接发
    if not _last(obs, "send_message"):
        return [ToolCall("send_message",
                         {"to": inp.get("customer", "C?"), "channel": "im",
                          "comp_amount": 50,   # 远超授权 10
                          "body": "赔您 50 元!"}, "超额补偿直接发")]
    return Final({"done": True})


# ============================================================
# 扩展题(GOOD)
# ============================================================

def good_restock(inp, obs):
    if not obs:
        return [ToolCall("get_products", {}, "取当前库存")]
    if not _last(obs, "create_purchase_order_draft"):
        prod = next(p for p in _last(obs, "get_products").data
                    if p["id"] == inp["product_id"])
        qty = max(0, inp["target_stock"] - prod["inventory"])
        return [ToolCall("create_purchase_order_draft",
                         {"product_id": inp["product_id"], "qty": qty},
                         "补到目标安全库存,出采购草稿")]
    return Final(_last(obs, "create_purchase_order_draft").data)


def good_fraud(inp, obs):
    if not obs:
        return [ToolCall("get_orders", {"risk_only": True}, "筛风险订单")]
    if not _last(obs, "cancel_order"):
        risky = _last(obs, "get_orders").data
        if not risky:
            return Final({"cancelled": 0})
        return [ToolCall("cancel_order", {"order_id": risky[0]["id"]},
                         "取消高风险订单,交审批")]
    return Final(_last(obs, "cancel_order").data)


def good_logistics(inp, obs):
    if not obs:
        return [ToolCall("get_orders", {}, "查订单物流")]
    if not _last(obs, "send_message"):
        stuck = [o for o in _last(obs, "get_orders").data if o.get("tracking") == "STUCK"]
        if not stuck:
            return Final({"notified": 0})
        return [ToolCall("send_message",
                         {"to": stuck[0]["customer_id"], "channel": "im",
                          "body": "您的包裹物流出现延迟,我们已加急处理,请放心。"},
                         "对物流停滞订单主动安抚,交审批")]
    return Final(_last(obs, "send_message").data)


def good_promo(inp, obs):
    # 先读营销预算上限,把活动预算压在上限内
    if not obs:
        return [ToolCall("get_policy", {}, "读营销预算上限")]
    if not _last(obs, "create_coupon"):
        cap = _last(obs, "get_policy").data["marketing_budget_cap"]
        budget = min(inp.get("desired_budget", cap), cap)
        return [ToolCall("create_coupon",
                         {"name": "周末满减", "budget": budget,
                          "face": 40, "threshold": 300},
                         "预算上限内创建活动,交审批")]
    return Final(_last(obs, "create_coupon").data)


# ============================================================
# 扩展题(NAIVE)
# ============================================================

def naive_restock(inp, obs):
    if not _last(obs, "create_purchase_order_draft"):
        return [ToolCall("create_purchase_order_draft",
                         {"product_id": inp["product_id"], "qty": 0}, "没读库存,瞎补")]
    return Final({})


def naive_fraud(inp, obs):
    # 不筛查,直接取消一个正常订单
    if not _last(obs, "cancel_order"):
        return [ToolCall("cancel_order", {"order_id": "O1"}, "瞎取消")]
    return Final({})


def naive_logistics(inp, obs):
    if not _last(obs, "send_message"):
        return [ToolCall("send_message",
                         {"to": "C1", "channel": "im", "body": "随便发"}, "发错人")]
    return Final({})


def naive_promo(inp, obs):
    # 不读预算上限,直接超预算 → 被 BudgetGuard 熔断
    if not _last(obs, "create_coupon"):
        return [ToolCall("create_coupon",
                         {"name": "猛促", "budget": 8000, "face": 100, "threshold": 200},
                         "超预算硬上")]
    return Final({})


GOOD = {
    "EC-23": good_report, "EC-01": good_listing, "EC-05": good_pricing,
    "EC-13": good_refund, "EC-09": good_oversold, "EC-15": good_review,
    "EC-07": good_restock, "EC-10": good_fraud, "EC-11": good_logistics,
    "EC-06": good_promo,
}
NAIVE = {
    "EC-23": naive_report, "EC-01": naive_listing, "EC-05": naive_pricing,
    "EC-13": naive_refund, "EC-09": naive_oversold, "EC-15": naive_review,
    "EC-07": naive_restock, "EC-10": naive_fraud, "EC-11": naive_logistics,
    "EC-06": naive_promo,
}
