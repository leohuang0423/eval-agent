"""具体工具集 —— 操作 Store,按风险分级注册。

平台无关的统一语义(适配器模式下,Shopify/抖店各自实现同名能力)。
此处用 mock Store 作为后端,既用于 benchmark,也作为真实适配器的参照接口。
"""
from __future__ import annotations

from .base import tool, RiskTier, ToolCtx, ToolResult
from ..env.store import Product, Refund


def _audit(ctx: ToolCtx, action: str, detail: dict):
    if ctx.audit is not None:
        ctx.audit.record(kind="tool", action=action, detail=detail,
                         tenant=ctx.tenant_id, dry_run=ctx.dry_run)


# ============ 🟢 READ ============

@tool("get_policy", RiskTier.READ, True, "读取本店策略(退款上限/最低毛利/预算等)")
def get_policy(ctx, args):
    return ToolResult(True, dict(ctx.store.policy))


@tool("get_orders", RiskTier.READ, True, "按条件查询订单。args: status?, risk_only?")
def get_orders(ctx, args):
    out = []
    for o in ctx.store.orders.values():
        if args.get("status") and o.status != args["status"]:
            continue
        if args.get("risk_only") and not o.risk_flag:
            continue
        out.append(vars(o))
    return ToolResult(True, out)


@tool("get_order", RiskTier.READ, True, "查询单个订单。args: order_id")
def get_order(ctx, args):
    o = ctx.store.orders.get(args["order_id"])
    return ToolResult(o is not None, vars(o) if o else None,
                      None if o else "order not found")


@tool("get_products", RiskTier.READ, True, "查询商品列表。args: status?")
def get_products(ctx, args):
    out = [vars(p) for p in ctx.store.products.values()
           if not args.get("status") or p.status == args["status"]]
    return ToolResult(True, out)


@tool("get_reviews", RiskTier.READ, True, "查询评价。args: max_rating?")
def get_reviews(ctx, args):
    out = [vars(r) for r in ctx.store.reviews.values()
           if r.rating <= args.get("max_rating", 5)]
    return ToolResult(True, out)


@tool("sales_report", RiskTier.READ, True, "汇总经营指标:GMV/订单数/退款率等")
def sales_report(ctx, args):
    orders = list(ctx.store.orders.values())
    gmv = sum(o.amount for o in orders if o.status in ("paid", "shipped", "closed"))
    refunded = sum(1 for o in orders if o.status == "refunded")
    report = {
        "orders": len(orders),
        "gmv": round(gmv, 2),
        "refund_rate": round(refunded / max(1, len(orders)), 4),
        "low_stock_skus": [p.id for p in ctx.store.products.values() if p.inventory < 5],
    }
    return ToolResult(True, report)


@tool("check_inventory_consistency", RiskTier.READ, True,
      "检测多平台库存不一致 / 超卖风险")
def check_inventory_consistency(ctx, args):
    issues = []
    for p in ctx.store.products.values():
        mirror = p.attrs.get("doudian_inventory")
        if mirror is not None and mirror != p.inventory:
            issues.append({"product_id": p.id, "shopify": p.inventory,
                           "doudian": mirror, "type": "mismatch"})
    return ToolResult(True, {"issues": issues})


# ============ 🟡 REVERSIBLE ============

@tool("create_product_draft", RiskTier.REVERSIBLE, True,
      "创建商品草稿(不直接上架)。args: title, category, cost, markup?, platform")
def create_product_draft(ctx, args):
    s = ctx.store
    pid = s._next("P")
    markup = args.get("markup", s.policy["markup"])
    cost = float(args["cost"])
    p = Product(id=pid, title=args["title"], status="draft",
                category=args["category"], cost=cost,
                price=round(cost * markup, 2), inventory=int(args.get("inventory", 0)),
                platform=args.get("platform", "shopify"), attrs=args.get("attrs", {}))
    s.products[pid] = p
    _audit(ctx, "create_product_draft", {"product_id": pid})
    return ToolResult(True, {"product_id": pid, "price": p.price, "status": "draft"})


@tool("update_price", RiskTier.REVERSIBLE, True,
      "改价(可逆)。args: product_id, new_price。低于成本×最低毛利会被拒")
def update_price(ctx, args):
    s = ctx.store
    p = s.products.get(args["product_id"])
    if not p:
        return ToolResult(False, error="product not found")
    floor = p.cost * (1 + s.policy["min_margin"])
    if float(args["new_price"]) < floor:
        return ToolResult(False, error=f"price below margin floor {floor:.2f}")
    old = p.price
    p.price = round(float(args["new_price"]), 2)
    _audit(ctx, "update_price", {"product_id": p.id, "old": old, "new": p.price})
    return ToolResult(True, {"product_id": p.id, "old_price": old, "new_price": p.price})


@tool("create_purchase_order_draft", RiskTier.REVERSIBLE, True,
      "创建采购单草稿。args: product_id, qty")
def create_po_draft(ctx, args):
    entry = {"product_id": args["product_id"], "qty": int(args["qty"]), "status": "draft"}
    ctx.store.po_drafts.append(entry)
    _audit(ctx, "create_po_draft", entry)
    return ToolResult(True, {"po": "draft", **entry})


# ============ 🔴 IRREVERSIBLE / 涉资金 ============

@tool("issue_refund", RiskTier.IRREVERSIBLE, False,
      "执行退款(不可逆,涉资金)。args: order_id, amount。超退款上限会被拒",
      cost_fn=lambda a: float(a.get("amount", 0)))
def issue_refund(ctx, args):
    s = ctx.store
    o = s.orders.get(args["order_id"])
    if not o:
        return ToolResult(False, error="order not found")
    cap = o.amount * s.policy["max_refund_ratio"]
    amount = round(float(args["amount"]), 2)
    if amount > cap + 1e-6:
        return ToolResult(False, error=f"refund {amount} exceeds cap {cap:.2f}")
    rid = s._next("RF")
    s.refunds[rid] = Refund(rid, o.id, amount, args.get("reason", ""), "approved")
    o.status = "refunded"
    s.ledger.append({"type": "refund", "order_id": o.id, "amount": -amount})
    _audit(ctx, "issue_refund", {"refund_id": rid, "order_id": o.id, "amount": amount})
    return ToolResult(True, {"refund_id": rid, "amount": amount}, money_cost=amount)


@tool("cancel_order", RiskTier.IRREVERSIBLE, False, "取消订单(不可逆)。args: order_id")
def cancel_order(ctx, args):
    o = ctx.store.orders.get(args["order_id"])
    if not o:
        return ToolResult(False, error="order not found")
    o.status = "cancelled"
    _audit(ctx, "cancel_order", {"order_id": o.id})
    return ToolResult(True, {"order_id": o.id, "status": "cancelled"})


@tool("set_inventory", RiskTier.IRREVERSIBLE, False,
      "强制设置库存(影响可售性,不可逆)。args: product_id, platform, qty")
def set_inventory(ctx, args):
    p = ctx.store.products.get(args["product_id"])
    if not p:
        return ToolResult(False, error="product not found")
    if args.get("platform") == "doudian":
        p.attrs["doudian_inventory"] = int(args["qty"])
    else:
        p.inventory = int(args["qty"])
    _audit(ctx, "set_inventory", {"product_id": p.id, "platform": args.get("platform"),
                                  "qty": int(args["qty"])})
    return ToolResult(True, {"product_id": p.id, "inventory": int(args["qty"])})


@tool("send_message", RiskTier.IRREVERSIBLE, False,
      "对外发送消息(客服/营销,不可逆)。args: to, channel, body",
      cost_fn=lambda a: 0.05)
def send_message(ctx, args):
    entry = dict(args)
    entry.setdefault("channel", "im")
    ctx.store.outbox.append(entry)   # 完整保存(含 comp_amount 等)便于审计/评分
    _audit(ctx, "send_message", {"to": args["to"], "channel": entry["channel"],
                                 "comp_amount": args.get("comp_amount", 0)})
    return ToolResult(True, {"sent": True}, money_cost=0.05)


@tool("create_coupon", RiskTier.IRREVERSIBLE, False,
      "创建优惠券/活动(不可逆,占用营销预算)。args: name, budget, face, threshold",
      cost_fn=lambda a: float(a.get("budget", 0)))
def create_coupon(ctx, args):
    budget = float(args["budget"])
    entry = {"name": args["name"], "budget": budget,
             "face": args.get("face"), "threshold": args.get("threshold")}
    ctx.store.coupons.append(entry)
    _audit(ctx, "create_coupon", entry)
    return ToolResult(True, {"coupon": args["name"], "budget": budget}, money_cost=budget)


@tool("reply_review", RiskTier.IRREVERSIBLE, False,
      "公开回复评价(不可逆)。args: review_id, reply")
def reply_review(ctx, args):
    r = ctx.store.reviews.get(args["review_id"])
    if not r:
        return ToolResult(False, error="review not found")
    r.reply = args["reply"]
    _audit(ctx, "reply_review", {"review_id": r.id})
    return ToolResult(True, {"review_id": r.id, "replied": True})
