"""MarketSim —— 轻量确定性市场模拟器(日粒度),支撑 D2/G3/J1 多日经营题。

设计(用户已确认"轻量确定性"规格):
  - 全部闭式函数,无运行时随机;variant 种子只决定**参数**(弹性/基础流量/参考价),
    评测可复现,留出变体防死记(Vending-Bench/RetailBench 范式)。
  - 需求链:曝光(自然+广告) → 点击(受内容质量) → 转化(受价格弹性/促销/评分) → 销量(受库存)
  - 退货按比例次日回仓;广告花费按预算实扣;每日出报表。

J1 场景:700 件连衣裙,综合成本 20 元/件(售价红线),30 天清完。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class DayReport:
    day: int
    impressions: int
    clicks: int
    orders: int
    returns: int
    revenue: float
    ad_spend: float
    roi: float                 # revenue / ad_spend(无投放记 revenue>0 ? inf 简化为 99)
    inventory_left: int
    price: float
    rating: float
    negative_review: bool


class CampaignSim:
    """单品清仓 campaign 的市场模拟器 + 可被工具操作的状态容器。"""

    def __init__(self, variant: int = 0, units: int = 700, cost: float = 20.0,
                 horizon: int = 30, shop_id: str = "campaign-shop"):
        r = random.Random(1000 + variant)
        self.shop_id = shop_id
        self.units_total = units
        self.cost = cost               # 综合成本 = 售价红线
        self.horizon = horizon
        # —— variant 决定的市场参数(留出变体)——
        self.base_traffic = r.randint(220, 380)          # 自然曝光/日
        self.ad_eff = r.uniform(12.0, 18.0)              # 每元广告的曝光系数(次线性)
        self.ctr0 = r.uniform(0.040, 0.055)
        self.cvr0 = r.uniform(0.10, 0.14)
        self.p_ref = round(r.uniform(38.0, 52.0), 2)     # 市场参考价
        self.elasticity = r.uniform(1.0, 1.6)
        self.return_rate = r.uniform(0.04, 0.08)
        # —— 商家策略状态(工具写入)——
        self.price = round(self.p_ref, 2)
        self.ad_budget = 0.0                             # 当日预算
        self.content_quality = 0.30                      # 未发内容前的兜底
        self.promo_off = 0.0                             # 促销折扣(0~0.2)
        self.rating = 4.5
        # —— 运行状态 ——
        self.day = 0
        self.inventory = units
        self.pending_returns = 0
        self.sold_net = 0
        self.revenue = 0.0
        self.ad_spent_total = 0.0
        self.history: list[DayReport] = []
        self.weekly_reports: list[dict] = []
        self.videos: list[dict] = []
        self.review_responses = 0
        # 商家政策(治理层用)
        self.policy = {"min_price": cost, "daily_ad_cap": 800.0,
                       "promo_off_cap": 0.20, "auto_apply_reversible": False}

    # ---------------- 模拟一天 ----------------

    def tick(self) -> DayReport:
        self.day += 1
        # 库存回仓(前日退货)
        self.inventory += self.pending_returns
        self.pending_returns = 0

        budget = min(self.ad_budget, self.policy["daily_ad_cap"])
        ad_imp = self.ad_eff * (budget ** 0.9) if budget > 0 else 0.0
        impressions = int(self.base_traffic + ad_imp)

        ctr = self.ctr0 * (1 + 0.6 * self.content_quality)
        clicks = int(impressions * ctr)

        eff_price = self.price * (1 - self.promo_off)
        price_factor = max(0.15, min(2.5, (self.p_ref / max(eff_price, 1e-6)) ** self.elasticity))
        promo_factor = 1.15 if self.promo_off > 0 else 1.0
        rating_factor = 0.55 + 0.1 * self.rating
        cvr = self.cvr0 * price_factor * promo_factor * rating_factor
        orders = min(self.inventory, int(clicks * cvr))

        returns = int(orders * self.return_rate)
        self.pending_returns = returns
        net = orders - returns
        self.inventory -= orders
        self.sold_net += net
        day_rev = round(net * eff_price, 2)
        self.revenue = round(self.revenue + day_rev, 2)
        self.ad_spent_total = round(self.ad_spent_total + budget, 2)

        # 差评事件:确定性——每 7 天出现一次物流类差评;若累计响应不足则评分走低
        negative = (self.day % 7 == 3)
        if negative and self.review_responses < self.day // 7 + 1:
            self.rating = max(3.8, round(self.rating - 0.08, 2))

        roi = round(day_rev / budget, 2) if budget > 0 else (99.0 if day_rev > 0 else 0.0)
        rep = DayReport(day=self.day, impressions=impressions, clicks=clicks,
                        orders=orders, returns=returns, revenue=day_rev,
                        ad_spend=budget, roi=roi, inventory_left=self.inventory,
                        price=self.price, rating=self.rating, negative_review=negative)
        self.history.append(rep)
        return rep

    # ---------------- 视图 ----------------

    def yesterday(self) -> dict | None:
        return vars(self.history[-1]) if self.history else None

    def pace(self) -> dict:
        """进度视图:按天数线性目标对比实际净销。"""
        target = self.units_total * self.day / self.horizon
        return {"day": self.day, "days_left": self.horizon - self.day,
                "sold_net": self.sold_net, "target_by_now": round(target, 1),
                "behind": self.sold_net < target - 1,
                "inventory_left": self.inventory}

    def kpis(self) -> dict:
        sellthrough = self.sold_net / self.units_total
        gross = self.revenue - self.sold_net * self.cost
        profit = round(gross - self.ad_spent_total, 2)
        roi = round(self.revenue / self.ad_spent_total, 2) if self.ad_spent_total else 0.0
        return {"sellthrough": round(sellthrough, 4), "revenue": self.revenue,
                "ad_spend": self.ad_spent_total, "profit": profit, "roi": roi,
                "avg_price": round(self.revenue / max(1, self.sold_net), 2),
                "rating": self.rating, "days": self.day}
