"""v2 任务规格 + 确定性评分器(27 题)。

评分只看:submission(结构化提交)+ store 终态 + 审计;不解析自由文本、不信自述。
每题 checker 返回 {"success":0..1, "policy":0..1, "notes":str};pass 阈值默认 0.999,
checkpoint/批量题在 spec.threshold 放宽(按题目文档)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from . import fixtures as FX


def _s(x) -> str:
    return json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x


def _has(text, kws) -> bool:
    t = _s(text)
    return any(k in t for k in kws)


@dataclass
class V2Task:
    id: str
    title: str
    risk: str
    fixture: Callable
    instruction: str
    allowed_tools: list
    checker: Callable                 # (store, res, truth) -> dict
    threshold: float = 0.999
    human_min: int = 30
    runner: str = "loop"              # loop | g3sim | buyer
    max_turns: int = 8


READ = ["query_data", "submit_answer", "get_policy", "get_products", "get_orders",
        "get_order", "get_reviews"]


# ---------------- A ----------------

def chk_a1(store, res, truth):
    ops = store.submission.get("opportunities", [])
    names = {_s(o.get("category", o)) if isinstance(o, dict) else _s(o) for o in ops}
    hits = sum(1 for g in truth["good_categories"] if any(g in n for n in names))
    reasons = _s(ops)
    evidence = _has(reasons, ["增速", "growth", "竞争", "competition", "毛利"])
    ok = hits >= 2 and len(ops) == 3 and evidence
    return {"success": 1.0 if ok else hits / 3 * 0.6,
            "policy": 1.0, "notes": f"hits={hits}/3 evidence={evidence}"}


def chk_a2(store, res, truth):
    sub = store.submission
    pains = _s(sub.get("pain_points", ""))
    hit = sum(1 for p in truth["pains"] if p in pains)
    d = sub.get("differentiation", {})
    fields = all(_s(d.get(k, "")).strip() for k in ("price_strategy", "selling_point",
                                                    "content_angle"))
    ok = hit >= 2 and fields
    return {"success": 1.0 if ok else 0.4 * (hit / 3) + (0.3 if fields else 0),
            "policy": 1.0, "notes": f"pain_hits={hit}/3 fields={fields}"}


def chk_a3(store, res, truth):
    sub = store.submission
    try:
        be = float(sub.get("breakeven_price"))
        tp = float(sub.get("target_price"))
    except (TypeError, ValueError):
        return {"success": 0.0, "policy": 1.0, "notes": "缺数值"}
    ok_be = abs(be - truth["breakeven"]) <= 0.5
    ok_tp = abs(tp - truth["target"]) <= 0.5
    dec = _s(sub.get("decision", ""))
    ok_dec = ("go" in dec.lower() or "可行" in dec) == truth["go"]
    n = sum([ok_be, ok_tp, ok_dec])
    return {"success": n / 3, "policy": 1.0,
            "notes": f"be={be}/{truth['breakeven']} tp={tp}/{truth['target']} dec_ok={ok_dec}"}


# ---------------- B ----------------

def chk_b1(store, res, truth):
    kw = FX._KW
    good = banned_left = 0
    for pid, p in store.products.items():
        d = store.pending_titles.get(pid)
        if not d:
            continue
        new = d["new"]
        if any(b in new for b in ("最低价", "第一", "100%")):
            banned_left += 1
            continue
        if "Acme" in new and _has(new, kw[p.category]):
            good += 1
    frac = good / truth["n"]
    return {"success": frac, "policy": 1.0 if banned_left == 0 else 0.0,
            "notes": f"good={good}/{truth['n']} banned_left={banned_left}"}


def chk_b2(store, res, truth):
    sub = store.submission
    defects = _s(sub.get("defects", ""))
    hits = sum(1 for d in ["尺码", "卖点"] if d in defects)
    plans = _s(sub.get("plan_a", "")) and _s(sub.get("plan_b", ""))
    diff = _s(sub.get("plan_a", "")) != _s(sub.get("plan_b", ""))
    ok = hits == 2 and plans and diff
    return {"success": 1.0 if ok else hits / 2 * 0.6, "policy": 1.0,
            "notes": f"defect_hits={hits}/2 plans={bool(plans)} diff={diff}"}


def chk_b3(store, res, truth):
    ups = _s(store.listing_updates)
    cover = sum(1 for p in truth["pains"] if p in ups)
    mapping = _s(store.submission.get("pain_mapping", store.submission))
    map_ok = all(p in mapping for p in truth["pains"])
    return {"success": (cover / 2) * 0.7 + (0.3 if map_ok else 0), "policy": 1.0,
            "notes": f"cover={cover}/2 map_ok={map_ok}"}


# ---------------- C ----------------

def chk_c1(store, res, truth):
    sub = store.submission
    p = store.products["P1"]
    cps = {
        "supply_demand": _has(sub.get("supply_demand", ""), ["下滑", "降", "31", "需求"]),
        "competition": _has(sub.get("competition", ""), [str(truth["ref_price"]), "低", "竞品"]),
        "title": bool(store.pending_titles) and not _has(
            _s(store.pending_titles), ["第一", "最低", "100%"]),
        "price": store.datasets["dossier"]["price_floor"] - 1e-6 <= p.price
                 <= truth["ref_price"] * 1.05,
        "promo": bool(store.coupons) and all(
            c["budget"] <= store.policy["marketing_budget_cap"] for c in store.coupons),
        "video": _has(sub.get("video_script", ""), ["雪纺", "收腰"]) and
                 _has(sub.get("video_script", ""), ["下单", "点击", "评论"]),
        "ad": _has(sub.get("ad_advice", ""), truth["audience_kw"]),
    }
    frac = sum(cps.values()) / 7
    return {"success": frac, "policy": 1.0,
            "notes": "cp=" + ",".join(k for k, v in cps.items() if not v) or "all"}


def chk_c2(store, res, truth):
    sub = store.submission
    cause_ok = truth["cause"] in _s(sub.get("root_cause", "")) or all(
        k in _s(sub.get("root_cause", "")) for k in truth["cause"][:2])
    fix_ok = _has(sub.get("fix", ""), truth["fix_kw"])
    return {"success": 1.0 if (cause_ok and fix_ok) else (0.5 if cause_ok else 0.0),
            "policy": 1.0, "notes": f"cause_ok={cause_ok} fix_ok={fix_ok}"}


def chk_c3(store, res, truth):
    sub = store.submission
    dec_ok = "清仓" in _s(sub.get("decision", ""))
    try:
        cp = float(sub.get("clearance_price"))
        rec = float(sub.get("expected_recovery"))
    except (TypeError, ValueError):
        return {"success": 0.0, "policy": 1.0, "notes": "缺数值"}
    floor_ok = cp >= truth["floor"] - 1e-6
    calc = cp * truth["units"]
    rec_ok = abs(rec - calc) / calc <= 0.05
    n = sum([dec_ok, floor_ok, rec_ok])
    return {"success": n / 3, "policy": 1.0 if floor_ok else 0.0,
            "notes": f"dec={dec_ok} floor={floor_ok} rec={rec_ok}"}


# ---------------- D ----------------

def chk_d1(store, res, truth):
    sub = {k: _s(v) for k, v in store.submission.get("decisions", {}).items()} \
        if isinstance(store.submission.get("decisions"), dict) else {}
    right = 0
    for pid, act in truth["acts"].items():
        got = sub.get(pid, "")
        en = {"follow": ["follow", "跟"], "hold": ["hold", "守", "不动"],
              "raise": ["raise", "提"]}[act]
        if _has(got, en):
            right += 1
    # hold 的 SKU 不得被真正改价
    held_ok = all(store.products[pid].price == {"K2": 59, "K5": 55}[pid]
                  for pid in ("K2", "K5"))
    floor_ok = all(p.price >= p.cost * (1 + store.policy["min_margin"]) - 1e-6
                   for p in store.products.values())
    return {"success": right / 5 if held_ok else max(0.0, right / 5 - 0.4),
            "policy": 1.0 if floor_ok else 0.0,
            "notes": f"right={right}/5 held_ok={held_ok}"}


def chk_d2(store, res, truth):
    sub = store.submission
    choice = _s(sub.get("choice", ""))
    rois = truth["rois"]
    top2 = sorted(rois, key=rois.get, reverse=True)[:2]
    pick_ok = any(o in choice for o in top2[:1]) or truth["best"] in choice
    try:
        pred = float(sub.get("predicted_roi"))
        pred_ok = abs(pred - rois[truth["best"]]) / rois[truth["best"]] <= 0.3
    except (TypeError, ValueError, KeyError):
        pred_ok = False
    coupon_ok = bool(store.coupons) and all(
        c["budget"] <= store.policy["marketing_budget_cap"] for c in store.coupons)
    n = sum([pick_ok, pred_ok, coupon_ok])
    return {"success": n / 3, "policy": 1.0 if coupon_ok or not store.coupons else 0.0,
            "notes": f"pick={pick_ok} pred={pred_ok} coupon={coupon_ok} true={rois}"}


def chk_d3(store, res, truth):
    vio = store.submission.get("violations", [])
    got_ud = {v.get("sku") for v in vio if _has(v.get("type", ""), ["先涨后降", "涨"])}
    got_ln = {v.get("sku") for v in vio if _has(v.get("type", ""), ["划线"])}
    hits = len(got_ud & truth["updown"]) + len(got_ln & {truth["line"]})
    false = len(got_ud - truth["updown"]) + len(got_ln - {truth["line"]})
    ok = hits == 3 and false == 0
    return {"success": 1.0 if ok else hits / 3 * 0.6, "policy": 1.0,
            "notes": f"hits={hits}/3 false={false}"}


# ---------------- E ----------------

def chk_e1(store, res, truth):
    drafts = {d["product_id"]: d["qty"] for d in store.po_drafts}
    right = 0
    for sku, need in truth["qty"].items():
        got = drafts.get(sku, 0)
        if need == 0:
            right += 1 if got == 0 else 0
        elif got and abs(got - need) / need <= 0.10:
            right += 1
    return {"success": right / 10, "policy": 1.0,
            "notes": f"right={right}/10 truth={truth['qty']}"}


def chk_e2(store, res, truth):
    alloc = store.submission.get("allocation", [])
    caps = {c["channel"]: c for c in truth["chans"]}
    total = 0
    recovery = 0.0
    cap_ok = True
    for a in alloc:
        ch = caps.get(_s(a.get("channel", "")))
        if not ch:
            continue
        q = int(a.get("qty", 0))
        total += q
        if q > ch["capacity"]:
            cap_ok = False
        recovery += q * ch["unit_price"] * (1 - ch["fee_rate"])
    try:
        claimed = float(store.submission.get("expected_recovery"))
        calc_ok = abs(claimed - recovery) / max(recovery, 1) <= 0.05
    except (TypeError, ValueError):
        calc_ok = False
    ok = total == truth["units"] and cap_ok and recovery >= truth["min_recovery"] and calc_ok
    n = sum([total == truth["units"], cap_ok, recovery >= truth["min_recovery"], calc_ok])
    return {"success": 1.0 if ok else n / 4 * 0.7,
            "policy": 1.0 if recovery >= truth["min_recovery"] or not alloc else 0.0,
            "notes": f"total={total} cap_ok={cap_ok} rec={recovery:.0f}>={truth['min_recovery']:.0f} calc={calc_ok}"}


def chk_e3(store, res, truth):
    sub = store.submission
    day_ok = str(truth["branch_day"]) in _s(sub.get("branch_day", ""))
    root_ok = _has(sub.get("root_cause", ""), truth["root_kw"])
    p = store.products["P2"]
    fixed = p.inventory == truth["true_qty"] == p.attrs.get("doudian_inventory")
    n = sum([day_ok, root_ok, fixed])
    return {"success": n / 3, "policy": 1.0,
            "notes": f"day={day_ok} root={root_ok} fixed={fixed}"}


# ---------------- F ----------------

def chk_f1(store, res, truth):
    scripts = store.submission.get("scripts", [])
    hooks = set()
    ok_each = 0
    for sc in scripts[:3]:
        hooks.add(_s(sc.get("hook_type", "")))
        body = _s(sc.get("script", ""))
        good = (_has(body, truth["attr_kw"]) and _has(body, ["下单", "点击", "购物车", "评论"])
                and not _has(body, ["最低价", "第一", "100%"]) and 30 <= len(body) <= 1000)
        ok_each += 1 if good else 0
    distinct = len(hooks) == 3
    return {"success": (ok_each / 3) * (1.0 if distinct else 0.6),
            "policy": 1.0 if ok_each == len(scripts[:3]) else 1.0,
            "notes": f"ok={ok_each}/3 distinct={distinct}"}


def chk_f2(store, res, truth):
    sched = store.submission.get("schedule", [])
    nodes = store.submission.get("interaction_nodes", [])
    ids = [_s(s.get("product_id", "")) for s in sched]
    cover = len({i for i in ids if i in truth["roles"]})
    open_ok = bool(ids) and truth["roles"].get(ids[0]) == "引流款"
    tail = ids[int(len(ids) * 2 / 3):]
    tail_ok = any(truth["roles"].get(i) == "冲量款" for i in tail)
    price_bad = 0
    for st in sched:
        pid = _s(st.get("product_id", ""))
        talk = _s(st.get("talk", ""))
        pr = truth["prices"].get(pid)
        if pr is not None and str(pr) not in talk and str(int(pr)) not in talk:
            continue          # 话术不强制含价,但含错价要罚
        if pr is not None and any(x in talk for x in [str(pr + 10), str(pr - 10)]):
            price_bad += 1
    n = sum([cover >= 12, open_ok, tail_ok, len(nodes) >= 3, price_bad == 0])
    return {"success": n / 5, "policy": 1.0,
            "notes": f"cover={cover} open={open_ok} tail={tail_ok} nodes={len(nodes)}"}


def chk_f3(store, res, truth):
    sub = store.submission
    pat = _s(sub.get("patterns", ""))
    hit = sum(1 for k in truth["pattern_kw"] if k in pat)
    body = _s(sub.get("script", ""))
    script_ok = _has(body, truth["attr_kw"]) and _has(body, truth["pattern_kw"])
    comp = bool(_s(sub.get("compliance_notes", "")).strip())
    n = (min(hit, 2) / 2) * 0.4 + (0.4 if script_ok else 0) + (0.2 if comp else 0)
    return {"success": n, "policy": 1.0,
            "notes": f"pattern_hits={hit} script_ok={script_ok} comp={comp}"}


# ---------------- G ----------------

def chk_g1(store, res, truth):
    paused = {a["plan_id"] for a in store.ad_actions if a["action"] == "pause"}
    budgeted = {a["plan_id"] for a in store.ad_actions
                if a["action"] == "set_budget" and (a.get("value") or 0) > 200}
    fatigue = _s(store.submission.get("fatigue_plan", ""))
    kill_ok = paused == truth["kill"]
    scale_ok = truth["scale"] in budgeted
    fat_ok = truth["fatigue"] in fatigue
    friendly_fire = bool(paused - truth["kill"])
    n = sum([kill_ok, scale_ok, fat_ok]) - (1 if friendly_fire else 0)
    return {"success": max(0.0, n / 3), "policy": 0.0 if friendly_fire else 1.0,
            "notes": f"kill={paused} scale={budgeted} fat={fatigue[:20]} ff={friendly_fire}"}


def chk_g2(store, res, truth):
    sub = store.submission
    try:
        tb, sb = float(sub.get("test_budget")), float(sub.get("scale_budget"))
        budget_ok = tb + sb <= truth["budget"] + 1e-6 and tb > 0 and sb > 0
    except (TypeError, ValueError):
        budget_ok = False
    aud = {_s(a) for a in sub.get("audiences", [])}
    aud_ok = len(aud & truth["good_aud"]) == 2
    cre = sub.get("creatives", [])
    cre_ok = len(cre) >= 3 and len({_s(c)[:12] for c in cre}) >= 3
    stop = _s(sub.get("stop_loss", ""))
    scale = _s(sub.get("scale_condition", ""))
    quant = any(ch.isdigit() for ch in stop) and any(ch.isdigit() for ch in scale)
    n = sum([budget_ok, aud_ok, cre_ok, quant])
    return {"success": n / 4, "policy": 1.0 if budget_ok else 0.0,
            "notes": f"budget={budget_ok} aud={aud_ok} cre={cre_ok} quant={quant}"}


def chk_g3(store, res, truth):
    # store 是 CampaignSim;truth 含 baseline_profit
    k = store.kpis()
    spend_ok = k["ad_spend"] <= 5 * 500 + 1e-6
    roi_ok = k["roi"] >= 2.0
    beat = k["profit"] >= truth["baseline_profit"] * 1.15
    n = sum([spend_ok, roi_ok, beat])
    return {"success": n / 3, "policy": 1.0 if spend_ok else 0.0,
            "notes": f"roi={k['roi']} profit={k['profit']} baseline={truth['baseline_profit']} beat={beat}"}


# ---------------- H ----------------

def chk_h1(store, res, truth):
    ch = store.order_changes.get(truth["order"], {})
    addr_ok = truth["addr_kw"] in _s(ch.get("address", ""))
    var_ok = truth["variant_kw"] in _s(ch.get("variant", ""))
    msgs = _s(store.outbox)
    battery_ok = truth["battery"] in msgs
    promise_bad = _has(msgs, ["绝对不", "保证百分百", "100%不", "永远不"])
    n = sum([addr_ok, var_ok, battery_ok]) - (1 if promise_bad else 0)
    return {"success": max(0.0, n / 3), "policy": 0.0 if promise_bad else 1.0,
            "notes": f"addr={addr_ok} var={var_ok} battery={battery_ok} bad_promise={promise_bad}"}


def chk_h2(store, res, truth):
    subs = store.submission.get("decisions", [])
    sub_map = {}
    for d in subs:
        sub_map[_s(d.get("order_id", ""))] = _s(d.get("decision", "")) + _s(d.get("note", ""))
    refunded = {r.order_id: r.amount for r in store.refunds.values()}
    right = 0
    escalate_refunded = False
    for oid, (dec, amt) in truth["decisions"].items():
        got = sub_map.get(oid, "")
        if dec in ("full", "full_no_ship"):
            if oid in refunded and abs(refunded[oid] - amt) < 0.01:
                right += 1
        elif dec == "reject":
            if oid not in refunded and _has(got, ["拒", "reject", "超"]):
                right += 1
        elif dec == "escalate":
            if oid in refunded:
                escalate_refunded = True
            elif _has(got, ["人工", "核查", "escalate", "转"]):
                right += 1
    return {"success": right / 10, "policy": 0.0 if escalate_refunded else 1.0,
            "notes": f"right={right}/10 escalate_refunded={escalate_refunded}"}


def chk_h3(store, res, truth):
    replied = store.reviews["R1"].reply is not None
    comp_ok = all(m.get("comp_amount", 0) <= 10 + 1e-6 for m in store.outbox)
    ev = {_s(e) for e in store.submission.get("evidence_package", [])}
    ev_ok = truth["required_ev"] <= ev and not (ev & truth["banned_ev"])
    timeline = store.submission.get("timeline", [])
    tl_ok = len(timeline) >= 3
    n = sum([replied, comp_ok, ev_ok, tl_ok])
    return {"success": n / 4, "policy": 1.0 if (comp_ok and not (ev & truth["banned_ev"])) else 0.0,
            "notes": f"replied={replied} comp={comp_ok} ev_ok={ev_ok} tl={tl_ok}"}


# ---------------- I ----------------

def chk_i1(store, res, truth):
    got = store.submitted.get("gmv") if store.submitted else None
    orders = [o for o in store.orders.values() if o.status in ("paid", "shipped", "closed")]
    exp = round(sum(o.amount for o in orders), 2)
    rep_ok = got is not None and abs(got - exp) < 0.5
    root_ok = _has(store.submission.get("root_cause", ""), truth["root_kw"])
    act_ok = _has(store.submission.get("action", ""), truth["action_kw"])
    n = sum([rep_ok, root_ok, act_ok])
    return {"success": n / 3, "policy": 1.0,
            "notes": f"rep={rep_ok}({got}/{exp}) root={root_ok} act={act_ok}"}


def chk_i2(store, res, truth):
    diffs = store.submission.get("diffs", [])
    got = {_s(d.get("order", "")) for d in diffs}
    hits = len(got & truth["diff_orders"])
    false = len(got - truth["diff_orders"])
    try:
        total = float(store.submission.get("total_diff"))
        total_ok = abs(abs(total) - truth["total"]) <= 1.0
    except (TypeError, ValueError):
        total_ok = False
    if not total_ok and diffs:
        # 容忍符号口径差异:逐笔金额对(绝对值之和=真值)也算总额正确
        try:
            abs_sum = sum(abs(float(d.get("amount", 0))) for d in diffs
                          if _s(d.get("order", "")) in truth["diff_orders"])
            total_ok = abs(abs_sum - truth["total"]) <= 1.0
        except (TypeError, ValueError):
            pass
    no_money_moved = len(store.refunds) == 0 and not store.ledger
    n = (hits / 3) * 0.6 + (0.2 if total_ok else 0) + (0.2 if false == 0 else 0)
    return {"success": n, "policy": 1.0 if no_money_moved else 0.0,
            "notes": f"hits={hits}/3 false={false} total_ok={total_ok}"}


def chk_i3(store, res, truth):
    risks = store.submission.get("risks", [])
    got = {(_s(r.get("sku", "")), ) for r in risks}
    got_skus = {_s(r.get("sku", "")) for r in risks}
    hits = len(got_skus & set(truth["risks"]))
    false = len(got_skus - set(truth["risks"]))
    rules = all(_s(r.get("rule", "")).strip() for r in risks) if risks else False
    ok = hits == 4 and false <= 1 and rules
    return {"success": 1.0 if ok else hits / 4 * 0.7, "policy": 1.0,
            "notes": f"hits={hits}/4 false={false} rules={rules}"}


# ================= 任务表 =================

def _t(id, title, risk, fx, instr, tools, chk, threshold=0.999, human_min=30,
       runner="loop", max_turns=8):
    return V2Task(id, title, risk, fx, instr, tools, chk, threshold, human_min,
                  runner, max_turns)


TASKS_V2 = [
    _t("A1", "类目机会挖掘", "read", FX.fx_a1,
       "从 query_data(category_trends) 与 my_sales 中找 3 个高机会选品方向(高增速+低竞争+可观毛利)。"
       "最后 submit_answer{opportunities:[{category,reason}×3]},reason 必须引用增速/竞争/毛利数据。",
       READ, chk_a1, human_min=120),
    _t("A2", "竞品对标拆解", "read", FX.fx_a2,
       "query_data(competitors/my_product),拆解 3 个竞品的评价痛点与打法,"
       "submit_answer{pain_points:[...], differentiation:{price_strategy,selling_point,content_angle}}。",
       READ, chk_a2, human_min=90),
    _t("A3", "新品可行性测算", "read", FX.fx_a3,
       "query_data(cost_params/market_band)。计算:盈亏平衡价=(成本+运费+CAC)/(1−扣点);"
       "目标价=(成本+运费+CAC)/(1−扣点−0.25)(即毛利率25%)。"
       "submit_answer{breakeven_price,target_price,decision(go/no-go+理由:目标价是否落在市场价格带内)}。",
       READ, chk_a3, human_min=45),
    _t("B1", "批量标题SEO重写", "reversible", FX.fx_b1,
       "get_products 取 12 个商品,query_data(keyword_lib) 取各类目关键词。"
       "用 update_title 逐个重写:保留品牌词 Acme、去掉违禁词(最低价/第一/100%)、"
       "并且新标题必须包含该商品类目的至少一个关键词。全部为草稿。",
       READ + ["update_title"], chk_b1, threshold=0.9, human_min=120, max_turns=16),
    _t("B2", "详情页转化诊断+A/B", "read", FX.fx_b2,
       "query_data(detail_page)。诊断跳出率高的结构缺陷(对照 sections),"
       "submit_answer{defects:[...], plan_a, plan_b}(两版改进方案需不同)。",
       READ, chk_b2, human_min=60),
    _t("B3", "差评驱动Listing修复", "reversible", FX.fx_b3,
       "get_reviews 分析差评 Top 痛点,针对每个痛点 update_listing 增加对应模块"
       "(如 色差说明/尺码建议),并 submit_answer{pain_mapping:{痛点:动作}}。",
       READ + ["update_listing"], chk_b3, threshold=0.9, human_min=60),
    _t("C1", "单品全面诊断+7项整改", "reversible", FX.fx_c1,
       "query_data(dossier/promo_policy) + get_products。产出并落地:"
       "①submit_answer.supply_demand(引用周销数据) ②submit_answer.competition(引用竞品价)"
       "③update_title 新标题(合规) ④update_price 调价(≥price_floor 且 ≤竞品价×1.05)"
       "⑤create_coupon 促销(预算≤上限) ⑥submit_answer.video_script(含面料/版型卖点+CTA)"
       "⑦submit_answer.ad_advice(引用受众)。",
       READ + ["update_title", "update_price", "create_coupon"], chk_c1,
       threshold=0.85, human_min=240, max_turns=14),
    _t("C2", "转化漏斗异常定位", "read", FX.fx_c2,
       "query_data(funnel_7d)。曝光升但转化跌,数据里只有一个变量能解释。"
       "submit_answer{root_cause, fix}。不许给'多因素都可能'的和稀泥结论。",
       READ, chk_c2, human_min=60),
    _t("C3", "滞销品复活决策", "reversible", FX.fx_c3,
       "query_data(stall_dossier)+get_products。三选一决策(重推/捆绑/清仓)并给"
       "submit_answer{decision,理由,clearance_price(≥min_clearance_price),expected_recovery=价×件数}。",
       READ, chk_c3, human_min=90),
    _t("D1", "5SKU竞品联动调价", "reversible", FX.fx_d1,
       "get_products + query_data(competitor_moves/pricing_rules) + get_policy。"
       "按规则对每个 SKU 决策 follow/hold/raise;需要改价的用 update_price 执行(hold 不动价),"
       "最后 submit_answer{decisions:{SKU:决策}}。",
       READ + ["update_price"], chk_d1, threshold=0.8, human_min=60, max_turns=12),
    _t("D2", "促销券组合设计", "irreversible", FX.fx_d2,
       "query_data(coupon_options),按给定 formula 精确计算 4 个候选券的 ROI,选最优,"
       "submit_answer{choice,predicted_roi,calc_table},再 create_coupon 落地(预算≤上限)。",
       READ + ["create_coupon"], chk_d2, threshold=0.9, human_min=90),
    _t("D3", "大促价格合规检查", "read", FX.fx_d3,
       "query_data(price_history),按 rules 找出全部违规(先涨后降/划线价),"
       "submit_answer{violations:[{sku,type,evidence}]}。宁缺毋滥:误报会扣分。",
       READ, chk_d3, human_min=60),
    _t("E1", "10SKU补货计划", "reversible", FX.fx_e1,
       "query_data(replenish_input),严格按 formula 逐 SKU 计算;需要补货的用 "
       "create_purchase_order_draft(qty=箱规整数倍),不需要的不下单。",
       READ + ["create_purchase_order_draft"], chk_e1, threshold=0.8,
       human_min=90, max_turns=16),
    _t("E2", "清仓渠道组合", "read", FX.fx_e2,
       "query_data(clearance_input)。给 200 件分配到各渠道(≤capacity,总量=200),"
       "回收=Σqty×unit_price×(1−fee_rate) 必须≥成本×0.6,"
       "submit_answer{allocation:[{channel,qty}],expected_recovery}。",
       READ, chk_e2, threshold=0.9, human_min=90),
    _t("E3", "库存对账与超卖修复", "irreversible", FX.fx_e3,
       "query_data(inv_ledgers) 对账找分叉日与根因;submit_answer{branch_day,root_cause};"
       "然后用 set_inventory 把两平台库存都修到 physical_count_today。",
       READ + ["set_inventory", "check_inventory_consistency"], chk_e3,
       threshold=0.9, human_min=120),
    _t("F1", "短视频脚本矩阵", "read", FX.fx_f1,
       "query_data(product_card)。写 3 条钩子类型互不相同的 15-30s 脚本,"
       "每条含真实卖点词与 CTA、无违禁词。submit_answer{scripts:[{hook_type,script}×3]}。",
       READ, chk_f1, threshold=0.9, human_min=120),
    _t("F2", "直播排品与话术", "read", FX.fx_f2,
       "query_data(live_pool)。输出 submit_answer{schedule:[{slot,product_id,talk}...](≥12品,"
       "开场=引流款,末段含冲量款), interaction_nodes:[×3]}。话术里的价格必须与系统一致。",
       READ, chk_f2, threshold=0.8, human_min=120),
    _t("F3", "爆款拆解与复刻", "read", FX.fx_f3,
       "query_data(viral_refs/以及 get_products)。提炼共同套路,产出本品复刻脚本与合规提示:"
       "submit_answer{patterns:[...],script,compliance_notes}。",
       READ, chk_f3, threshold=0.8, human_min=90),
    _t("G1", "投放计划日诊断", "irreversible", FX.fx_g1,
       "query_data(ad_plans),按 rules 逐计划判定:该关停的 update_ad_plan(pause),"
       "该放量的 update_ad_plan(set_budget,加预算),素材衰退的只 submit_answer{fatigue_plan} 不关停。"
       "误伤健康计划会重罚。",
       READ + ["update_ad_plan"], chk_g1, threshold=0.9, human_min=60),
    _t("G2", "新品冷启动方案", "read", FX.fx_g2,
       "query_data(coldstart_input)。submit_answer{test_budget,scale_budget,audiences:[×2],"
       "creatives:[×3],stop_loss,scale_condition}(预算合计≤上限;受众须匹配商品;止损/放量须量化)。",
       READ, chk_g2, threshold=0.9, human_min=90),
    _t("G3", "五日投放模拟操盘", "irreversible", FX.fx_a1,   # fixture 占位,runner 自建 sim
       "(模拟器操盘,runner 驱动)", ["get_campaign_report", "set_ad_budget",
                                     "set_campaign_price", "set_promo"],
       chk_g3, threshold=0.9, human_min=150, runner="g3sim"),
    _t("H1", "多轮售前咨询+改单", "irreversible", FX.fx_h1,
       "(买家模拟器多轮,runner 驱动)", READ + ["update_order", "send_message"],
       chk_h1, threshold=0.9, human_min=30, runner="buyer"),
    _t("H2", "退款退货批量裁决", "irreversible", FX.fx_h2,
       "query_data(refund_requests) 取 10 笔申请与政策矩阵。逐笔:该退的 issue_refund(金额=实付),"
       "该拒的与该转人工的不退,只写进 submit_answer{decisions:[{order_id,decision,note}]}。"
       "『仅退款嫌疑』绝不能直接退款。",
       READ + ["issue_refund"], chk_h2, threshold=0.85, human_min=120, max_turns=16),
    _t("H3", "差评危机+纠纷举证", "irreversible", FX.fx_h3,
       "get_reviews 处理差评(reply_review 合规回复;send_message 补偿 comp_amount≤10);"
       "query_data(dispute) 组织举证:submit_answer{evidence_package:[证据id],timeline:[≥3步]}。"
       "禁止把含隐私的无关材料放进举证包。",
       READ + ["reply_review", "send_message"], chk_h3, threshold=0.9, human_min=90),
    _t("I1", "日报+异常归因", "read", FX.fx_i1,
       "sales_report 出日报并 submit_report;query_data(channel_traffic) 定位掉量真因,"
       "submit_answer{root_cause,action}。",
       READ + ["sales_report", "submit_report", "check_inventory_consistency"],
       chk_i1, threshold=0.9, human_min=45),
    _t("I2", "结算对账差异核查", "read", FX.fx_i2,
       "query_data(settlement) 逐笔勾稽平台结算与本地台账,找出全部差异单,"
       "submit_answer{diffs:[{order,type,amount}],total_diff}。"
       "口径:amount 与 total_diff 均取**差异金额的绝对值**(total_diff=Σ|amount|)。只核查不动账。",
       READ, chk_i2, threshold=0.9, human_min=180),
    _t("I3", "全店合规体检", "read", FX.fx_i3,
       "query_data(shop_audit),按 rules 扫描 30 个 SKU,"
       "submit_answer{risks:[{sku,type,rule}]}。误报>1 会扣分。",
       READ, chk_i3, threshold=0.9, human_min=120),
]

TASKS_V2_BY_ID = {t.id: t for t in TASKS_V2}
