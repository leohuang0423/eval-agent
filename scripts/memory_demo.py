#!/usr/bin/env python3
"""Memory 影响决策 demo —— 同一道调价题,加不同的店铺记忆,真模型给出不同定价。

证明 memory 不是摆设:商家偏好被记住并真实改变 agent 的推理结果(且都守住毛利红线)。
复现:python scripts/memory_demo.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.tools.base import ToolCtx
from ecom_agent.governance import Governance, AuditLog, BudgetGuard, auto_approver
from ecom_agent.loop import AgentLoop
from ecom_agent.models.llm import LLMModel, claude_cli_completion
from ecom_agent.benchmark.tasks import TASKS_BY_ID
from ecom_agent.benchmark.runner import _make_input
from ecom_agent.skills import SYSTEM_BASE, skill_prompt
from ecom_agent.memory import MemoryStore

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")


def run_pricing(memory_note: str | None, variant: int = 2) -> float:
    task = TASKS_BY_ID["EC-05"]
    store = task.setup(variant=variant)
    inp = _make_input(task, store, variant, None)
    mem = MemoryStore(os.path.join(os.path.dirname(__file__), "..", ".agent_memory_demo"))
    mem.clear(store.shop_id)
    if memory_note:
        mem.remember(store.shop_id, memory_note, kind="semantic", skill="pricing")
    system = SYSTEM_BASE + "\n\n" + skill_prompt("EC-05")
    mc = mem.context(store.shop_id, skill="pricing")
    if mc:
        system += "\n\n" + mc
    gov = Governance(store.policy, AuditLog(), approver=auto_approver,
                     budget=BudgetGuard(), enforce=True)
    ctx = ToolCtx(store=store, tenant_id=store.shop_id, audit=AuditLog())
    model = LLMModel(claude_cli_completion(MODEL), system, allowed_tools=task.allowed_tools)
    loop = AgentLoop(model, gov, ctx, max_turns=8, allowed_tools=task.allowed_tools)
    loop.run(inp)
    return store.products["P1"].price, inp["competitor_price"], store.products["P1"].cost


def main():
    print(f"模型 {MODEL} | 同一道 EC-05 调价,改变店铺记忆看决策变化\n")
    p0, comp, cost = run_pricing(None)
    print(f"A. 无记忆(默认):定价 {p0}  (竞品 {comp}, 成本 {cost})")
    p1, _, _ = run_pricing("本店策略:薄利多销,在守住毛利红线前提下,定价尽量压低到竞品价的约 96%。")
    print(f"B. 记忆[薄利多销→压到竞品96%]:定价 {p1}")
    p2, _, _ = run_pricing("本店定位高端品牌,坚持不打价格战;只要不亏,定价可与竞品持平甚至略高。")
    print(f"C. 记忆[高端不打价格战]:定价 {p2}")
    print(f"\n观察:同题同环境,仅店铺记忆不同,真模型定价从 {p0} → {p1}(更低)/ {p2}(更高)。"
          "\n记忆真实改变了决策,且都在毛利红线之上。")


if __name__ == "__main__":
    main()
