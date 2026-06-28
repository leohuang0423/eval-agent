#!/usr/bin/env python3
"""Subagent 复合任务 demo —— 一个"大促备战"高层目标,planner 用真模型分解为多步,
dispatcher 逐个跑 skill 限域子 agent(共享同一店铺 store + 治理 + memory)。

证明 subagent 机制端到端可用:真模型规划 + 多个域子 agent 协作改同一份经营状态,
全程治理层拦审批、记忆累积。复现:python scripts/composite_demo.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.env.store import seed_store
from ecom_agent.models.llm import claude_cli_completion
from ecom_agent.planner import plan_with_llm, dispatch
from ecom_agent.memory import MemoryStore

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

OBJECTIVE = ("周末要做一场大促。请规划:① 给低库存爆品补货;② 对标竞品给主推款调一个有竞争力的价格;"
             "③ 在营销预算内创建一张满减券;④ 最后出一份经营日报。")


def main():
    complete = claude_cli_completion(MODEL)
    store = seed_store()
    mem = MemoryStore(os.path.join(os.path.dirname(__file__), "..", ".agent_memory_demo"))
    mem.clear(store.shop_id)

    print(f"模型 {MODEL}\n高层目标:{OBJECTIVE}\n")
    plan = plan_with_llm(OBJECTIVE, complete)
    print("planner 分解的计划:")
    for i, s in enumerate(plan, 1):
        print(f"  {i}. [{s.get('skill')}] {s.get('instruction')}")
    if not plan:
        print("(planner 未产出计划)"); return

    print("\n逐步派发子 agent(共享 store):")
    results = dispatch(store, plan, complete, memory=mem)
    for r in results:
        print(f"  - [{r.skill}] 工具:{r.tools} 审批:{r.approvals} 安全违规:{r.safety_viol}")

    print("\n经营状态变化(终态):")
    print(f"  采购草稿: {store.po_drafts}")
    print(f"  P1 价格: {store.products['P1'].price}")
    print(f"  优惠券: {store.coupons}")
    print(f"  日报提交: {store.submitted}")
    print(f"  累计审批: {sum(r.approvals for r in results)}  安全违规: {sum(r.safety_viol for r in results)}")
    print(f"  记忆条数: {len(mem.recall(store.shop_id, k=20))}")
    print("\n解读:真模型自己规划了多步,各 skill 子 agent 在最小权限下改同一份经营状态,"
          "高风险动作全程经审批,记忆随之累积 —— 这是 chatbot 做不到的、面向经营结果的 agent 协作。")


if __name__ == "__main__":
    main()
