#!/usr/bin/env python3
"""反思闭环 demo —— 证明 loop 架构支持"执行 → 观察失败 → 反思 → 再执行"。

场景:退款。brain 首次过度自信按 1.5×订单额申请 → 工具层上限拒绝 →
brain 从 observation 里读到 error → 反思修正为订单实付额 → 通过。整个过程在**一次 run 内**闭环。

说明:这里"反思"由手写 brain 演示**控制流**;真正的 agent 中,这一步交给 LLM
读取 error 自主再规划。loop/治理/工具不变 —— 槽位已经留好。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.env.store import seed_store
from ecom_agent.tools.base import ToolCtx
from ecom_agent.governance import Governance, AuditLog, BudgetGuard, auto_approver
from ecom_agent.loop import AgentLoop
from ecom_agent.models.scripted import ScriptedModel
from ecom_agent.benchmark.solvers import reflective_refund


def main():
    store = seed_store()
    audit = AuditLog()
    gov = Governance(store.policy, audit, approver=auto_approver,
                     budget=BudgetGuard(), enforce=True)
    ctx = ToolCtx(store=store, tenant_id=store.shop_id, audit=audit)
    loop = AgentLoop(ScriptedModel(reflective_refund), gov, ctx, max_turns=10)
    res = loop.run({"order_id": "O1"})

    print("=== 工具调用轨迹(单次 run 内)===")
    for i, o in enumerate(res.observations, 1):
        status = "OK" if o.ok else f"FAIL({o.error})"
        amt = o.args.get("amount")
        print(f"{i}. {o.name}({'amount=%.2f' % amt if amt else ''})  -> {status}")

    print(f"\n最终: {res.final}")
    print(f"退款落库: {[vars(r) for r in store.refunds.values()]}")
    print(f"安全违规: {res.unapproved_high_risk}  审批次数: {res.approvals}")
    print("\n解读:第 2 步过度退款被上限拒(FAIL)→ 第 3 步 brain 读到 error 反思修正 → OK。"
          "\n这就是'执行→反思→再执行'的闭环;loop 没变,换 LLM 即由模型自主完成这步推理。")


if __name__ == "__main__":
    main()
