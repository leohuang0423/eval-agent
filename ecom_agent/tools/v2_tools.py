"""v2 新增工具 —— 通用数据查询 + 结构化提交 + 少量新动作。

设计:query_data 一个 🟢 工具服务全部只读数据集(趋势/竞品/漏斗/价格历史/广告报表/
结算/评价语料/直播品池…);submit_answer 一个 🟢 工具承接各题的结构化结论
(τ-bench 式:评分只看提交与终态,不解析自由文本)。动作类新增 4 个,沿用风险分级。
"""
from __future__ import annotations

from .base import tool, RiskTier, ToolCtx, ToolResult


def _audit(ctx, action, detail):
    if ctx.audit is not None:
        ctx.audit.record(kind="tool", action=action, detail=detail,
                         tenant=ctx.tenant_id, dry_run=ctx.dry_run)


# ---------------- 🟢 通用 ----------------

@tool("query_data", RiskTier.READ, True,
      "查询数据集。args: dataset(名称)。可用数据集见任务说明")
def query_data(ctx, args):
    ds = getattr(ctx.store, "datasets", {})
    name = args.get("dataset")
    if name not in ds:
        return ToolResult(False, error=f"unknown dataset '{name}'; available: {list(ds)}")
    return ToolResult(True, ds[name])


@tool("submit_answer", RiskTier.READ, True,
      "提交本题的结构化结论(字段见任务说明)。可多次提交,后提交覆盖同名字段")
def submit_answer(ctx, args):
    sub = getattr(ctx.store, "submission", None)
    if sub is None:
        ctx.store.submission = {}
    ctx.store.submission.update(args)
    _audit(ctx, "submit_answer", {"keys": list(args.keys())})
    return ToolResult(True, {"submitted_keys": list(ctx.store.submission.keys())})


# ---------------- 🟡 可逆写 ----------------

@tool("update_title", RiskTier.REVERSIBLE, True,
      "更新商品标题(草稿,可回滚)。args: product_id, new_title")
def update_title(ctx, args):
    st = ctx.store
    if not hasattr(st, "pending_titles"):
        st.pending_titles = {}
    p = st.products.get(args["product_id"])
    if not p:
        return ToolResult(False, error="product not found")
    st.pending_titles[p.id] = {"old": p.title, "new": str(args["new_title"])}
    _audit(ctx, "update_title", {"product_id": p.id})
    return ToolResult(True, {"product_id": p.id, "status": "draft"})


@tool("update_listing", RiskTier.REVERSIBLE, True,
      "更新详情页模块(草稿)。args: section(如 尺码表/色差说明/FAQ), content")
def update_listing(ctx, args):
    st = ctx.store
    if not hasattr(st, "listing_updates"):
        st.listing_updates = []
    st.listing_updates.append({"section": str(args.get("section", "")),
                               "content": str(args.get("content", ""))})
    _audit(ctx, "update_listing", {"section": args.get("section")})
    return ToolResult(True, {"sections": [u["section"] for u in st.listing_updates]})


# ---------------- 🔴 不可逆 ----------------

@tool("update_ad_plan", RiskTier.IRREVERSIBLE, False,
      "操作广告计划(涉资金)。args: plan_id, action(pause|set_budget), value?",
      cost_fn=lambda a: float(a.get("value", 0)) if a.get("action") == "set_budget" else 0.0)
def update_ad_plan(ctx, args):
    st = ctx.store
    if not hasattr(st, "ad_actions"):
        st.ad_actions = []
    plans = {p["id"] for p in st.datasets.get("ad_plans", {}).get("plans", [])}
    if args.get("plan_id") not in plans:
        return ToolResult(False, error=f"unknown plan {args.get('plan_id')}")
    act = {"plan_id": args["plan_id"], "action": args.get("action"),
           "value": args.get("value")}
    st.ad_actions.append(act)
    _audit(ctx, "update_ad_plan", act)
    return ToolResult(True, act)


@tool("update_order", RiskTier.IRREVERSIBLE, False,
      "修改订单(不可逆)。args: order_id, address?, new_sku_variant?")
def update_order(ctx, args):
    st = ctx.store
    o = st.orders.get(args["order_id"])
    if not o:
        return ToolResult(False, error="order not found")
    if o.status not in ("paid",):
        return ToolResult(False, error=f"order status {o.status} not modifiable")
    changes = {}
    if args.get("address"):
        changes["address"] = str(args["address"])
    if args.get("new_sku_variant"):
        changes["variant"] = str(args["new_sku_variant"])
    if not changes:
        return ToolResult(False, error="nothing to change")
    if not hasattr(st, "order_changes"):
        st.order_changes = {}
    st.order_changes.setdefault(o.id, {}).update(changes)
    _audit(ctx, "update_order", {"order_id": o.id, **changes})
    return ToolResult(True, {"order_id": o.id, "applied": changes})
