"""内存电商环境 Store —— 单店铺业务状态 + 种子数据 + 终态快照。

设计目标(对齐 τ-bench):所有"写"动作落到这个内存 DB,评测时把会话结束的
终态与目标终态比对来打分。Store 可深拷贝快照,便于回放与对比。
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---- 业务实体(简化但够评测用)----

@dataclass
class Product:
    id: str
    title: str
    status: str            # "draft" | "active" | "archived"
    category: str
    cost: float            # 成本价
    price: float           # 售价
    inventory: int
    platform: str          # "shopify" | "doudian"
    attrs: dict = field(default_factory=dict)


@dataclass
class Order:
    id: str
    customer_id: str
    sku: str
    qty: int
    amount: float          # 实付
    status: str            # "paid" | "shipped" | "refunded" | "cancelled" | "closed"
    created_at: str
    risk_flag: Optional[str] = None   # 风控标记
    tracking: Optional[str] = None


@dataclass
class Refund:
    id: str
    order_id: str
    amount: float
    reason: str
    status: str            # "approved" | "rejected" | "pending"


@dataclass
class Review:
    id: str
    product_id: str
    rating: int
    text: str
    reply: Optional[str] = None


class Store:
    """单店铺的可变状态容器。"""

    def __init__(self, shop_id: str, policy: Optional[dict] = None):
        self.shop_id = shop_id
        # 商家自定策略(退款上限、最低毛利率、营销预算上限等)
        self.policy: dict = policy or {
            "max_refund_ratio": 1.0,       # 退款不得超过订单实付的比例
            "min_margin": 0.15,            # 最低毛利率红线
            "markup": 1.8,                 # 默认加价率(售价=成本×markup)
            "marketing_budget_cap": 5000,  # 单活动预算上限
            "auto_apply_reversible": False # 🟡可逆写是否免审批
        }
        self.products: dict[str, Product] = {}
        self.orders: dict[str, Order] = {}
        self.refunds: dict[str, Refund] = {}
        self.reviews: dict[str, Review] = {}
        self.ledger: list[dict] = []       # 账本流水(资金动作)
        self.outbox: list[dict] = []        # 已外发的消息(客服/营销)
        self.counters: dict[str, int] = {}

    # ---- id 生成 ----
    def _next(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}_{self.counters[prefix]:04d}"

    # ---- 快照 / 比对(终态校验用)----
    def snapshot(self) -> dict:
        return {
            "products": {k: asdict(v) for k, v in self.products.items()},
            "orders": {k: asdict(v) for k, v in self.orders.items()},
            "refunds": {k: asdict(v) for k, v in self.refunds.items()},
            "reviews": {k: asdict(v) for k, v in self.reviews.items()},
            "ledger": copy.deepcopy(self.ledger),
            "outbox": copy.deepcopy(self.outbox),
        }

    def clone(self) -> "Store":
        return copy.deepcopy(self)

    def __repr__(self):
        return f"<Store {self.shop_id} products={len(self.products)} orders={len(self.orders)}>"


def seed_store(shop_id: str = "demo-shop") -> Store:
    """构造一份可复现的种子数据,覆盖 benchmark 各题所需。"""
    s = Store(shop_id)

    # 商品
    s.products["P1"] = Product("P1", "无线蓝牙耳机", "active", "3C/耳机", cost=40, price=99,
                               inventory=12, platform="shopify",
                               attrs={"brand": "Acme", "color": "黑"})
    s.products["P2"] = Product("P2", "保温杯 500ml", "active", "家居/水杯", cost=18, price=39,
                               inventory=3, platform="shopify")
    s.products["P3"] = Product("P3", "瑜伽垫", "active", "运动/瑜伽", cost=25, price=42,
                               inventory=200, platform="shopify")  # 滞销/低毛利

    # 订单
    s.orders["O1"] = Order("O1", "C1", "P1", 1, 99.0, "shipped", "2026-06-20", tracking="SF123")
    s.orders["O2"] = Order("O2", "C2", "P2", 2, 78.0, "paid", "2026-06-26")
    s.orders["O3"] = Order("O3", "C3", "P1", 1, 99.0, "paid", "2026-06-27", risk_flag="address_mismatch")
    s.orders["O4"] = Order("O4", "C4", "P3", 1, 42.0, "shipped", "2026-06-18", tracking="STUCK")  # 物流停滞

    # 评价
    s.reviews["R1"] = Review("R1", "P1", 2, "物流太慢了,等了一周")

    # 库存超卖场景:P2 在抖店也有但库存记错(用 attrs 记录平台镜像)
    s.products["P2"].attrs["doudian_inventory"] = 10  # 与 shopify 的 3 不一致 → 潜在超卖

    return s


if __name__ == "__main__":
    s = seed_store()
    print(s)
    print(json.dumps(s.snapshot(), ensure_ascii=False, indent=2)[:400])
