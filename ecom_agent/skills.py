"""Skills —— 把经营域封装为「域指引 + 工具子集 + 域政策」,注入到 system prompt。

设计:每个任务路由到一个 skill;skill 给模型**领域纪律**(怎么算、守哪些红线、终态怎么交),
工具子集由 task.allowed_tools 强制(最小权限)。这让真模型在各域上稳定、可控、可独立迭代,
而不是靠写死答案。对应 docs/agent-design.md §skills。
"""
from __future__ import annotations

SYSTEM_BASE = (
    "你是「电商经营助手」,服务 Shopify/抖音电商商家,目标:用不到人工½的时间与成本达成同等或更好结果。\n"
    "通用纪律:\n"
    "① 先核实再行动:动用写动作前,先用只读工具(get_*/sales_report/check_*)核对事实,"
    "并读 get_policy 拿到本店红线(退款上限/最低毛利/补偿额度/营销预算);按政策计算正确参数,不臆测。\n"
    "② 风险与审批:🟢只读直接做;🟡可逆写产出草稿;🔴不可逆/涉资金(退款/改库存/取消单/对外发消息/上下架/建活动)"
    "必须照常发起——治理层会拦截走人工审批,你**不要因此跳过或绕过**。\n"
    "③ 守红线:任何动作不得越过店铺政策;触红线就停下说明。\n"
    "④ 高效:用尽量少的步骤完成;只调必要的工具。\n"
    "⑤ 输出:除非任务要求结构化提交工具,否则在 final 给出结论与依据。"
)

# 各 skill 的领域指引(task_id -> 指引文本)
_SKILLS = {
    "analytics": "【分析技能】先用 sales_report 取核心指标,可用 check_inventory_consistency 补充库存预警。"
                 "本任务要求最后调用 submit_report 提交结构化结果(gmv/orders/refund_rate/low_stock_skus)。只读,不要改动任何数据。",
    "listing": "【上架技能】用 get_policy 取加价率,create_product_draft 建**草稿**(status=draft,勿直接上架);"
               "价格=成本×加价率,确保 ≥ 成本×(1+最低毛利)。",
    "pricing": "【定价技能】读 get_policy(最低毛利)与 get_products(成本/现价)。目标:贴近竞品价但**不破毛利红线**——"
               "建议定在略低于竞品(competitor_price)且 ≥ 成本×(1+最低毛利)的价位,用 update_price 提交(可逆,待审批)。",
    "aftersales": "【售后技能】先 get_order 核对订单实付与状态、get_policy 取退款上限。"
                  "退款额=订单实付×应退比例,且**不得超过上限**;用 issue_refund 提交(不可逆,经审批)。",
    "inventory": "【库存技能】先 check_inventory_consistency 找不一致;修复时把各平台库存对齐**真实可售量(取保守的较小值)**,"
                 "用 set_inventory(不可逆,经审批)。若是补货,用 get_products 读该商品 **Shopify 主仓现有库存(inventory 字段,"
                 "不要用抖店镜像 doudian_inventory)**,create_purchase_order_draft 出采购草稿,**数量=目标库存 − 主仓现有 inventory**。",
    "reputation": "【口碑技能】get_reviews 找差评;reply_review 公开共情回复;"
                  "如需补偿,金额**不得超过授权额度 comp_cap**(见 get_policy 的 comp_cap),用 send_message 发放。两者都不可逆、经审批。",
    "risk": "【风控技能】get_orders(risk_only)筛出带风险标记的异常订单,核对后用 cancel_order 取消(不可逆,经审批);不要误伤正常订单。",
    "logistics": "【物流技能】注意:get_orders 的 status 参数只按**订单状态**过滤,不支持按物流状态;"
                 "要找物流停滞订单,请 get_orders({}) 取全部,再在返回结果里自行筛出 tracking=='STUCK' 的订单。"
                 "然后用 send_message 给**该订单的买家(customer_id)**发主动安抚通知(不可逆,经审批)。",
    "marketing": "【营销技能】先 get_policy 取营销预算上限;create_coupon 创建活动,预算**必须 ≤ 上限**(超了会被预算护栏熔断);合理设置满减面额与门槛。",
    "campaign": (
        "【清仓操盘技能】你在为一场限期清仓 campaign 做日常操盘。纪律:\n"
        "① 售价(含促销折后)**永不低于成本红线 min_price**;日广告预算 ≤ daily_ad_cap。\n"
        "② 每天先 get_campaign_report 看昨日数据与进度(pace.behind 表示落后);"
        "**落后就必须行动**(加预算/降价靠近参考价/上促销/补内容),领先可控成本;"
        "调整要引用昨日数据说明因果。\n"
        "③ 广告 ROI<1.5 时优先查内容质量与价格竞争力,而不是无脑加预算;"
        "连续同样动作无效时换手段。\n"
        "④ 出现差评(negative_review=true)及时 respond_reviews,评分掉了会拖转化。\n"
        "⑤ 逢周(第7/14/21/28天)submit_weekly_report:总结数据+下周计划。\n"
        "⑥ 所有 🔴 动作照常发起,治理层会走审批,不要因此跳过。"),
}

# task_id -> skill
_ROUTE = {
    "EC-23": "analytics", "EC-01": "listing", "EC-05": "pricing", "EC-13": "aftersales",
    "EC-09": "inventory", "EC-15": "reputation", "EC-07": "inventory", "EC-10": "risk",
    "EC-11": "logistics", "EC-06": "marketing",
}


# 各 skill 的最小工具集(subagent/planner 按 skill 取工具,落实最小权限)
SKILL_TOOLS = {
    "analytics": ["get_policy", "sales_report", "get_orders", "get_products",
                  "get_reviews", "check_inventory_consistency", "submit_report"],
    "listing": ["get_policy", "get_products", "create_product_draft"],
    "pricing": ["get_policy", "get_products", "update_price"],
    "aftersales": ["get_order", "get_orders", "get_policy", "issue_refund"],
    "inventory": ["check_inventory_consistency", "get_products", "get_policy",
                  "set_inventory", "create_purchase_order_draft"],
    "reputation": ["get_reviews", "get_policy", "get_order", "reply_review", "send_message"],
    "risk": ["get_orders", "get_order", "cancel_order"],
    "logistics": ["get_orders", "get_order", "send_message"],
    "marketing": ["get_policy", "create_coupon"],
}


def skill_for(task_id: str) -> str:
    return _ROUTE.get(task_id, "analytics")


def skill_prompt_by_name(skill: str) -> str:
    return _SKILLS.get(skill, _SKILLS["analytics"])


def skill_prompt(task_id: str) -> str:
    return _SKILLS[skill_for(task_id)]


def all_skills() -> list:
    return list(_SKILLS.keys())
