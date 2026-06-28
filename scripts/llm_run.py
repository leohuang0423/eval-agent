#!/usr/bin/env python3
"""用真实模型(Claude Sonnet 4.6,经 `claude -p`)驱动 agent loop 的模型节点。

把 ScriptedModel 换成 LLMModel,在**留出变体**(模型没"背"过的数值)上跑,
验证:真模型能不能 读状态→按政策推理→发起动作→(失败时)反思修正,并通过终态校验+治理。

用法:python scripts/llm_run.py [variant] [task_id ...]
默认 variant=3,跑 EC-23 / EC-13 / EC-05 三道代表题。
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

SYSTEM = ("你是「电商经营助手」,服务 Shopify/抖音电商商家,目标:用不到人工½的时间与成本"
          "达成同等或更好的结果。先核实再行动,守红线,高风险动作必须经人工审批,草稿优先,可解释。")

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")


def run_task(task_id: str, variant: int):
    task = TASKS_BY_ID[task_id]
    store = task.setup(variant=variant)
    inp = _make_input(task, store, variant, None)
    audit = AuditLog()
    gov = Governance(store.policy, audit, approver=auto_approver,
                     budget=BudgetGuard(money_cap=task.money_cap, call_cap=30),
                     enforce=True)
    ctx = ToolCtx(store=store, tenant_id=store.shop_id, audit=audit)
    model = LLMModel(claude_cli_completion(MODEL), SYSTEM,
                     allowed_tools=task.allowed_tools)
    loop = AgentLoop(model, gov, ctx, max_turns=8, allowed_tools=task.allowed_tools)
    res = loop.run(inp)
    chk = task.goal_check(store, res, inp)

    print(f"\n===== {task.id} {task.title}  (variant={variant}) =====")
    print(f"输入: {inp}")
    for i, o in enumerate(res.observations, 1):
        st = "OK" if o.ok else f"FAIL({o.error})"
        ap = "" if o.approved is None else f" approved={o.approved}"
        print(f"  {i}. {o.name}({o.args}) -> {st}{ap}")
    ok = chk["success"] >= 0.999 and chk["policy"] >= 0.999 and res.unapproved_high_risk == 0
    print(f"  final={res.final}")
    print(f"  判定: success={chk['success']} policy={chk['policy']} "
          f"安全违规={res.unapproved_high_risk} 审批={res.approvals} → "
          f"{'✅ 通过' if ok else '❌ 未过'}  ({chk['notes']})")
    return ok


def main():
    args = sys.argv[1:]
    variant = int(args[0]) if args and args[0].isdigit() else 3
    ids = [a for a in args if not a.isdigit()] or ["EC-23", "EC-13", "EC-05"]
    print(f"模型: {MODEL}  |  留出 variant={variant}  |  题: {ids}")
    results = {tid: run_task(tid, variant) for tid in ids}
    passed = sum(results.values())
    print(f"\n真模型小结: {passed}/{len(results)} 通过  {results}")


if __name__ == "__main__":
    main()
