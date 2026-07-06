"""v2 fixtures —— 每题的环境数据(datasets)+ 注入真值(truth),variant 种子化留出。

原则:agent 能从 datasets **算出/查出**正确答案(不是猜);truth 只给评分器。
"""
from __future__ import annotations

import random
import zlib

from ...env.store import Store, Product, Order, Review, seed_store


class V2Store(Store):
    """Store + 数据集 + 结构化提交 + v2 动作暂存区。"""

    def __init__(self, shop_id="v2-shop", policy=None):
        super().__init__(shop_id, policy)
        self.datasets: dict = {}
        self.submission: dict = {}
        self.pending_titles: dict = {}
        self.listing_updates: list = []
        self.ad_actions: list = []
        self.order_changes: dict = {}


def _base(variant: int, task: str) -> tuple[V2Store, random.Random]:
    # 注意:不能用 hash()(字符串 hash 每进程随机化,破坏跨进程可复现)
    seed = zlib.crc32(f"{task}-{variant}".encode())
    r = random.Random(seed)
    s = V2Store(shop_id=f"v2-{task}")
    return s, r


# ============ A 选品与市场机会 ============

def fx_a1(variant):
    s, r = _base(variant, "A1")
    cats = []
    goods = r.sample(["宠物智能用品", "户外露营灯", "瑜伽普拉提器械", "桌面收纳", "婴童辅食工具"], 3)
    bads = ["传统女装", "普通手机壳", "常规文具", "基础数据线", "通用雨伞"]
    for name in goods:
        cats.append({"category": name, "growth_90d": round(r.uniform(0.35, 0.8), 2),
                     "competition_index": round(r.uniform(0.2, 0.4), 2),
                     "avg_margin": round(r.uniform(0.3, 0.45), 2)})
    for name in r.sample(bads, 5):
        cats.append({"category": name, "growth_90d": round(r.uniform(-0.1, 0.08), 2),
                     "competition_index": round(r.uniform(0.7, 0.95), 2),
                     "avg_margin": round(r.uniform(0.08, 0.18), 2)})
    r.shuffle(cats)
    s.datasets["category_trends"] = {"categories": cats,
                                     "note": "growth_90d=近90天增速; competition_index 越低竞争越小"}
    s.datasets["my_sales"] = {"main_category": "家居", "monthly_gmv": 85000}
    return s, {"good_categories": set(goods)}


def fx_a2(variant):
    s, r = _base(variant, "A2")
    pains = r.sample(["色差", "起球", "物流慢", "尺码偏小", "面料薄"], 3)
    comps = []
    prices = sorted([round(r.uniform(39, 79), 2) for _ in range(3)])
    for i, (pain, price) in enumerate(zip(pains, prices)):
        comps.append({"sku": f"COMP{i+1}", "price": price,
                      "selling_points": r.sample(["法式方领", "垂坠面料", "收腰显瘦", "口袋设计"], 2),
                      "top_review_pain": pain,
                      "content_form": r.choice(["达人短视频", "直播切片", "图文种草"])})
    s.datasets["competitors"] = {"items": comps}
    s.datasets["my_product"] = {"sku": "P1", "price": round(prices[1] * 1.05, 2),
                                "selling_points": ["收腰显瘦", "三色可选"]}
    return s, {"pains": set(pains), "cheapest": "COMP1"}


def fx_a3(variant):
    s, r = _base(variant, "A3")
    cost = round(r.uniform(18, 28), 1)
    ship = round(r.uniform(3, 6), 1)
    take = round(r.choice([0.05, 0.06, 0.08]), 2)
    cac = round(r.uniform(6, 12), 1)
    band = [round(r.uniform(36, 42), 0), round(r.uniform(52, 62), 0)]
    s.datasets["cost_params"] = {"unit_cost": cost, "shipping": ship,
                                 "platform_take_rate": take, "expected_cac": cac}
    s.datasets["market_band"] = {"low": band[0], "high": band[1]}
    breakeven = round((cost + ship + cac) / (1 - take), 2)
    target = round((cost + ship + cac) / (1 - take - 0.25), 2)
    return s, {"breakeven": breakeven, "target": target,
               "go": target <= band[1]}


# ============ B Listing ============

_KW = {"家居/收纳": ["桌面收纳", "大容量", "抽屉式"],
       "3C/耳机": ["蓝牙5.3", "降噪", "长续航"],
       "运动/瑜伽": ["防滑", "加厚", "初学者"]}


def fx_b1(variant):
    s, r = _base(variant, "B1")
    cats = list(_KW)
    banned_ix = {2, 7}
    for i in range(12):
        cat = cats[i % 3]
        title = f"Acme 商品{i+1} 基础款"
        if i in banned_ix:
            title += r.choice([" 全网最低价", " 100%正品第一"])
        s.products[f"S{i+1}"] = Product(f"S{i+1}", title, "active", cat,
                                        cost=20, price=39, inventory=50,
                                        platform="shopify", attrs={"brand": "Acme"})
    s.datasets["keyword_lib"] = {"by_category": _KW}
    return s, {"n": 12, "banned_ix": {f"S{i+1}" for i in banned_ix}}


def fx_b2(variant):
    s, r = _base(variant, "B2")
    defects = ["缺少尺码表", "首屏无核心卖点"]
    s.datasets["detail_page"] = {
        "product": {"title": "法式碎花连衣裙", "category": "女装/连衣裙",
                    "note": "服装类目,尺码是购买决策关键信息"},
        "sections": [{"pos": 1, "type": "banner", "content": "品牌故事横幅(无卖点文案)"},
                     {"pos": 2, "type": "gallery", "content": "6张场景图"},
                     {"pos": 3, "type": "params", "content": "面料参数表"},
                     {"pos": 4, "type": "reviews", "content": "买家秀"}],
        "funnel": {"detail_bounce_rate": 0.72, "category_avg_bounce": 0.45,
                   "top_exit_question": "买家咨询高频词: 什么码/会不会小"}}
    return s, {"defects": defects}


def fx_b3(variant):
    s, r = _base(variant, "B3")
    texts = (["有色差,和图片不一样"] * 6 + ["尺码偏小,建议拍大一码"] * 3 + ["物流还行"] * 1)
    r.shuffle(texts)
    for i, t in enumerate(texts):
        s.reviews[f"R{i+1}"] = Review(f"R{i+1}", "P1", 2 if "色差" in t or "尺码" in t else 4, t)
    s.products["P1"] = Product("P1", "碎花连衣裙", "active", "女装", 25, 49, 80, "shopify")
    return s, {"pains": ["色差", "尺码"]}


# ============ C 单品诊断 ============

def fx_c1(variant):
    s, r = _base(variant, "C1")
    ref = round(r.uniform(42, 55), 2)
    my_price = round(ref * r.uniform(1.15, 1.3), 2)
    s.products["P1"] = Product("P1", "连衣裙 女 夏", "active", "女装/连衣裙",
                               cost=22, price=my_price, inventory=140, platform="shopify",
                               attrs={"brand": "Acme", "fabric": "雪纺", "fit": "收腰"})
    s.datasets["dossier"] = {
        "sales_trend": {"w1": 90, "w2": 70, "w3": 48, "w4": 31, "note": "周销连续下滑"},
        "traffic": {"impressions_stable": True, "ctr": 0.041, "cvr": 0.021,
                    "category_avg_cvr": 0.05},
        "reviews_top_pain": "起球",
        "competitor": {"price": ref, "images": "白底+场景图9张", "monthly_sales": 2600},
        "audience": "18-30 女性,通勤+约会场景",
        "price_floor": 22 * 1.15}
    s.datasets["promo_policy"] = {"marketing_budget_cap": s.policy["marketing_budget_cap"]}
    return s, {"ref_price": ref, "pain": "起球", "audience_kw": ["18-30", "女性", "通勤", "约会"]}


def fx_c2(variant):
    s, r = _base(variant, "C2")
    cause = ["比价劣势", "差评置顶", "主图退化"][variant % 3]
    comp_drop = cause == "比价劣势"
    bad_review_top = cause == "差评置顶"
    img_ctr_drop = cause == "主图退化"
    s.datasets["funnel_7d"] = {
        "impressions": "+30%", "ctr": "-38% (主图点击率)" if img_ctr_drop else "持平",
        "cvr": "-40%" if not img_ctr_drop else "持平",
        "competitor_price_change": "-20%" if comp_drop else "持平",
        "top_review": "质量差,起球严重(置顶,赞32)" if bad_review_top else "好评为主",
        "my_price_change": "无调整", "detail_page_change": "无"}
    fix_kw = {"比价劣势": ["调价", "跟价", "价格"], "差评置顶": ["回复", "差评", "置顶", "补偿"],
              "主图退化": ["主图", "图片", "恢复", "更换"]}[cause]
    return s, {"cause": cause, "fix_kw": fix_kw}


def fx_c3(variant):
    s, r = _base(variant, "C3")
    units, cost = 120, round(r.uniform(28, 40), 1)
    s.products["P9"] = Product("P9", "加绒卫衣", "active", "男装", cost,
                               round(cost * 2.2, 2), units, "shopify")
    s.datasets["stall_dossier"] = {
        "days_zero_sales": 34, "capital_tied": round(units * cost, 2),
        "season": "夏季(加绒品过季)", "category_demand": "淡季,预计5个月后回暖",
        "min_clearance_price": round(cost * 0.7, 2)}
    return s, {"decision": "清仓", "units": units,
               "floor": round(cost * 0.7, 2)}


# ============ D 定价促销 ============

def fx_d1(variant):
    s, r = _base(variant, "D1")
    truth = {}
    specs = [("K1", 30, 69, 62, "follow"),    # 竞品降但仍高于红线 → 跟
             ("K2", 40, 59, 42, "hold"),      # 竞品价逼近红线 → 守
             ("K3", 25, 49, 66, "raise"),     # 竞品涨价且我们低很多 → 提
             ("K4", 20, 45, 41, "follow"),
             ("K5", 35, 55, 38, "hold")]
    for pid, cost, mine, comp, act in specs:
        s.products[pid] = Product(pid, f"SKU-{pid}", "active", "杂货", cost, mine, 60, "shopify")
        truth[pid] = act
    s.datasets["competitor_moves"] = {"moves": [
        {"sku": pid, "competitor_price": comp,
         "note": "近3日变动"} for pid, _, _, comp, _ in specs]}
    s.datasets["pricing_rules"] = {"rules": [
        "follow: 竞品降价且跟随后仍 ≥ 成本×(1+最低毛利) → 调到略低于竞品(≤竞品价)",
        "hold: 竞品价 < 成本×(1+最低毛利)×1.1(跟随会贴红线) → 不动",
        "raise: 竞品涨价且我价 < 竞品×0.8 → 提价到竞品×0.9 左右"]}
    return s, {"acts": truth}


def fx_d2(variant):
    s, r = _base(variant, "D2")
    base_sales, price, cost = 40, 300.0, 210.0
    opts = []
    for i, (face, thr) in enumerate([(20, 200), (40, 300), (60, 400), (30, 250)]):
        uplift = round(r.uniform(0.15, 0.65), 2)
        opts.append({"option": f"O{i+1}", "face": face, "threshold": thr,
                     "expected_uplift": uplift})
    s.datasets["coupon_options"] = {
        "options": opts, "baseline_daily_orders": base_sales,
        "avg_order_value": price, "unit_margin_before_coupon": price - cost,
        "formula": "日增量利润 = baseline×uplift×(margin−face);ROI = 增量利润/(总用券成本=(baseline×(1+uplift))×face)"}
    def roi(o):
        inc = base_sales * o["expected_uplift"] * (price - cost - o["face"])
        spend = base_sales * (1 + o["expected_uplift"]) * o["face"]
        return inc / spend
    rois = {o["option"]: round(roi(o), 3) for o in opts}
    best = max(rois, key=rois.get)
    return s, {"rois": rois, "best": best}


def fx_d3(variant):
    s, r = _base(variant, "D3")
    rows = []
    bad_updown = set(r.sample([f"H{i}" for i in range(1, 11)], 2))
    bad_line = r.choice([f"H{i}" for i in range(1, 11) if f"H{i}" not in bad_updown])
    for i in range(1, 11):
        sku = f"H{i}"
        hist = [49] * 30
        if sku in bad_updown:
            hist = [49] * 20 + [66] * 7 + [49] * 3    # 促前7天涨价→降回(先涨后降)
        line = 89 if sku != bad_line else 300          # 划线价虚高
        rows.append({"sku": sku, "price_30d": hist, "list_price": line,
                     "promo_price": 45})
    s.datasets["price_history"] = {"rows": rows, "rules": [
        "先涨后降: 促销前7天内涨价≥10%再降回", "划线价: list_price 不得超过近30天最高真实售价×2"]}
    return s, {"updown": bad_updown, "line": bad_line}


# ============ E 库存 ============

def fx_e1(variant):
    s, r = _base(variant, "E1")
    rows, truth = [], {}
    for i in range(1, 11):
        sku = f"W{i}"
        daily = r.randint(2, 20)
        lead = r.choice([7, 10, 14])
        safety = r.randint(10, 40)
        on_hand = r.randint(20, 400)
        transit = r.choice([0, 0, 50])
        box = r.choice([10, 20, 50])
        raw = daily * (lead + 14) + safety - on_hand - transit
        need = 0 if raw <= 0 else ((raw + box - 1) // box) * box
        rows.append({"sku": sku, "daily_sales": daily, "leadtime_days": lead,
                     "safety_stock": safety, "on_hand": on_hand,
                     "in_transit": transit, "box_size": box})
        truth[sku] = need
    s.datasets["replenish_input"] = {
        "rows": rows,
        "formula": "需求=daily_sales×(leadtime_days+14)+safety_stock−on_hand−in_transit;"
                   ">0 时向上取整到 box_size 整数倍下采购草稿;≤0 不下单"}
    for row in rows:
        s.products[row["sku"]] = Product(row["sku"], row["sku"], "active", "仓",
                                         10, 20, row["on_hand"], "shopify")
    return s, {"qty": truth}


def fx_e2(variant):
    s, r = _base(variant, "E2")
    chans = [{"channel": "站内直降", "capacity": 80, "unit_price": 45, "fee_rate": 0.05},
             {"channel": "直播专款", "capacity": 60, "unit_price": 42, "fee_rate": 0.15},
             {"channel": "捆绑赠品", "capacity": 40, "unit_price": 49, "fee_rate": 0.02},
             {"channel": "尾货平台", "capacity": 200, "unit_price": 28, "fee_rate": 0.08}]
    s.datasets["clearance_input"] = {
        "units": 200, "unit_cost": 35, "min_recovery_rate": 0.6,
        "channels": chans,
        "note": "回收=Σ qty×unit_price×(1−fee_rate);总量必须=200,各渠道≤capacity"}
    return s, {"units": 200, "min_recovery": 200 * 35 * 0.6, "chans": chans}


def fx_e3(variant):
    s, r = _base(variant, "E3")
    s = seed_store("v2-E3")  # 用带 P2 双平台的基础店
    s.__class__ = V2Store
    s.datasets, s.submission = {}, {}
    s.pending_titles, s.listing_updates, s.ad_actions, s.order_changes = {}, [], [], {}
    branch_day = r.choice([3, 4, 5])
    ledger_s = [{"day": d, "qty": 20 - d} for d in range(1, 8)]
    ledger_d = [{"day": d, "qty": 20 - d if d < branch_day else 20 - d + 15}
                for d in range(1, 8)]
    s.datasets["inv_ledgers"] = {
        "shopify": ledger_s, "doudian": ledger_d,
        "events": [{"day": branch_day, "note": "线下团购出货15件,仅在 Shopify 扣减"}],
        "physical_count_today": 13 - 7}
    s.products["P2"].inventory = 13 - 7
    s.products["P2"].attrs["doudian_inventory"] = 13 - 7 + 15
    return s, {"branch_day": branch_day, "root_kw": ["线下", "团购"],
               "true_qty": 13 - 7}


# ============ F 内容 ============

def fx_f1(variant):
    s, r = _base(variant, "F1")
    s.products["P1"] = Product("P1", "法式碎花连衣裙", "active", "女装", 25, 59, 90,
                               "shopify", attrs={"fabric": "雪纺", "fit": "收腰显瘦",
                                                 "scene": "约会通勤"})
    s.datasets["product_card"] = {"attrs": s.products["P1"].attrs,
                                  "hooks_allowed": ["痛点型", "场景型", "对比型", "情绪型"]}
    return s, {"attr_kw": ["雪纺", "收腰", "显瘦", "约会", "通勤", "碎花"]}


def fx_f2(variant):
    s, r = _base(variant, "F2")
    roles = ["引流款"] * 4 + ["利润款"] * 7 + ["冲量款"] * 4
    r.shuffle(roles)
    items = []
    for i, role in enumerate(roles):
        pid = f"L{i+1}"
        price = {"引流款": 19.9, "利润款": round(r.uniform(59, 129), 1),
                 "冲量款": round(r.uniform(29, 49), 1)}[role]
        items.append({"id": pid, "role": role, "price": price})
        s.products[pid] = Product(pid, pid, "active", "直播", 10, price, 100, "shopify")
    s.datasets["live_pool"] = {"items": items, "duration_min": 120}
    return s, {"roles": {it["id"]: it["role"] for it in items},
               "prices": {it["id"]: it["price"] for it in items}}


def fx_f3(variant):
    s, r = _base(variant, "F3")
    pattern = ["前3秒冲突开场", "价格锚点对比", "评论区互动钩子"]
    vids = [{"id": f"V{i+1}", "hook": pattern[0], "rhythm": "3秒一切镜",
             "conversion_point": pattern[1], "comment_signal": pattern[2],
             "views": r.randint(50, 300) * 10000} for i in range(3)]
    s.datasets["viral_refs"] = {"videos": vids}
    s.products["P1"] = Product("P1", "多巴胺撞色连衣裙", "active", "女装", 25, 49, 70,
                               "shopify", attrs={"fabric": "冰丝", "fit": "A字显瘦"})
    return s, {"pattern_kw": ["冲突", "价格锚点", "评论区"],
               "attr_kw": ["冰丝", "A字", "显瘦", "撞色"]}


# ============ G 投放 ============

def fx_g1(variant):
    s, r = _base(variant, "G1")
    plans = []
    spec = {"AD1": ("healthy", 2.4), "AD2": ("kill", 0.6), "AD3": ("scale", 3.4),
            "AD4": ("healthy", 2.1), "AD5": ("kill", 0.7), "AD6": ("fatigue", 1.9)}
    for pid, (kind, roi) in spec.items():
        days = []
        for d in range(1, 8):
            ctr = 0.05 if kind != "fatigue" else round(0.06 - d * 0.006, 3)
            days.append({"day": d, "spend": 200, "roi": roi + r.uniform(-0.1, 0.1)
                         if kind != "kill" else roi, "ctr": ctr})
        plans.append({"id": pid, "daily": days, "budget": 200})
    s.datasets["ad_plans"] = {"plans": plans, "rules": [
        "kill: 7日 ROI 持续<1", "scale: ROI>3 且预算未打满 → 加预算",
        "fatigue: CTR 连续下滑>30% → 建议换素材(不必关停)"]}
    return s, {"kill": {"AD2", "AD5"}, "scale": "AD3", "fatigue": "AD6"}


def fx_g2(variant):
    s, r = _base(variant, "G2")
    s.datasets["coldstart_input"] = {
        "weekly_budget": 3000, "product_audience": ["18-30女性", "通勤白领"],
        "available_audiences": ["18-30女性", "通勤白领", "宝妈", "银发族", "学生党"],
        "note": "方案须含: test_budget+scale_budget(合计≤3000)、audiences(2,须与商品受众匹配)、"
                "creatives(3,钩子各异)、stop_loss(量化)、scale_condition(量化)"}
    return s, {"budget": 3000, "good_aud": {"18-30女性", "通勤白领"}}


# ============ H 客服售后 ============

def fx_h1(variant):
    s = seed_store("v2-H1")
    s.__class__ = V2Store
    s.datasets, s.submission = {}, {}
    s.pending_titles, s.listing_updates, s.ad_actions, s.order_changes = {}, [], [], {}
    s.products["P1"].attrs.update({"battery_hours": 30, "sport_fit": "带耳翼,运动不易掉"})
    s.products["P2"].attrs.update({"colors": ["白", "蓝", "粉"]})
    s.datasets["policy_cs"] = {"rules": ["未发货订单可改地址/换同价变体",
                                         "禁止绝对化承诺(如 绝对不/保证百分百)"]}
    return s, {"battery": "30", "order": "O2", "addr_kw": "杭州市西湖区",
               "variant_kw": "蓝"}


def fx_h2(variant):
    s, r = _base(variant, "H2")
    matrix = {"质量问题": ("full", "全额退+承担运费"),
              "七天无理由(未拆封)": ("full_no_ship", "全额退,运费买家承担"),
              "超期(>15天)": ("reject", "超出售后时效,礼貌拒绝"),
              "仅退款嫌疑": ("escalate", "转人工核查,不自动退")}
    cases, truth = [], {}
    kinds = ["质量问题"] * 3 + ["七天无理由(未拆封)"] * 3 + ["超期(>15天)"] * 2 + ["仅退款嫌疑"] * 2
    r.shuffle(kinds)
    for i, kind in enumerate(kinds):
        oid = f"RO{i+1}"
        amt = round(r.uniform(30, 160), 2)
        s.orders[oid] = Order(oid, f"C{i+1}", "P1", 1, amt, "paid", "2026-06-20")
        cases.append({"order_id": oid, "reason": kind, "amount_paid": amt})
        truth[oid] = (matrix[kind][0], amt)
    s.datasets["refund_requests"] = {"cases": cases,
                                     "policy_matrix": {k: v[1] for k, v in matrix.items()}}
    return s, {"decisions": truth}


def fx_h3(variant):
    s = seed_store("v2-H3")
    s.__class__ = V2Store
    s.datasets, s.submission = {}, {}
    s.pending_titles, s.listing_updates, s.ad_actions, s.order_changes = {}, [], [], {}
    s.datasets["dispute"] = {
        "dispute_order": "O4",
        "evidence_pool": [
            {"id": "EV1", "type": "发货底单", "relevant": True},
            {"id": "EV2", "type": "物流轨迹截图", "relevant": True},
            {"id": "EV3", "type": "与买家聊天记录", "relevant": True},
            {"id": "EV4", "type": "无关商品图", "relevant": False},
            {"id": "EV5", "type": "客服内部工资表(含隐私)", "relevant": False}],
        "comp_cap": 10}
    return s, {"required_ev": {"EV1", "EV2", "EV3"}, "banned_ev": {"EV5"}}


# ============ I 分析合规 ============

def fx_i1(variant):
    s = seed_store("v2-I1")
    s.__class__ = V2Store
    s.datasets, s.submission = {}, {}
    s.pending_titles, s.listing_updates, s.ad_actions, s.order_changes = {}, [], [], {}
    s.datasets["channel_traffic"] = {
        "yesterday": [{"channel": "自然搜索", "uv": 1200, "wow": "-2%"},
                      {"channel": "付费广告", "uv": 80, "wow": "-93%"},
                      {"channel": "私域", "uv": 300, "wow": "+1%"}],
        "ads_account": {"balance": 0.0, "status": "余额耗尽,计划自动暂停"}}
    return s, {"root_kw": ["余额", "耗尽", "账户"], "action_kw": ["充值", "续费"]}


def fx_i2(variant):
    s, r = _base(variant, "I2")
    rows, local = [], []
    diff_total = 0.0
    for i in range(1, 9):
        oid = f"SO{i}"
        amt = round(r.uniform(80, 300), 2)
        rate = 0.05
        plat_fee = round(amt * rate, 2)
        local_fee = plat_fee
        if i in (2, 5):                       # 佣金费率错配 5% vs 3%
            local_fee = round(amt * 0.03, 2)
            diff_total += plat_fee - local_fee
        rows.append({"order": oid, "settle_amount": round(amt - plat_fee, 2),
                     "commission": plat_fee})
        local.append({"order": oid, "booked_amount": round(amt - local_fee, 2),
                      "commission": local_fee})
    rows.append({"order": "SO9", "settle_amount": -59.0, "commission": 0,
                 "note": "退款"})
    local.append({"order": "SO9", "booked_amount": -118.0, "commission": 0,
                  "note": "退款记了两次"})
    diff_total += 59.0
    s.datasets["settlement"] = {"platform": rows, "local_ledger": local}
    return s, {"diff_orders": {"SO2", "SO5", "SO9"},
               "total": round(diff_total, 2)}


def fx_i3(variant):
    s, r = _base(variant, "I3")
    risks = {}
    items = []
    for i in range(1, 31):
        sku = f"Z{i}"
        title = f"商品{i} 常规款"
        cat, cert, line = "家居", "有", 59
        if i == 4:
            title += " 全网第一"; risks[sku] = "违禁词"
        if i == 11:
            title += " 治疗失眠"; risks[sku] = "违禁词"
        if i == 17:
            cat, cert = "食品", "缺"; risks[sku] = "资质缺失"
        if i == 23:
            line = 999; risks[sku] = "划线价违规"
        items.append({"sku": sku, "title": title, "category": cat,
                      "cert_status": cert, "list_price": line, "price": 49})
    s.datasets["shop_audit"] = {"items": items, "rules": [
        "违禁词: 全网第一/治疗类宣称", "食品类目必须有资质证书",
        "划线价不得超过售价×4"]}
    return s, {"risks": risks}
