#!/usr/bin/env python3
"""商家入口 CLI —— 电商经营 agent 的产品形态。

  python scripts/agent_cli.py "给物流停滞的订单发个安抚通知,再出一份今日日报"
  python scripts/agent_cli.py "..." --yes            # 演示:自动批准(生产勿用)
  python scripts/agent_cli.py "..." --tenant shopA   # 多店铺:状态/记忆/审计按租户隔离

流程:真模型 planner 分解指令 → 按 skill 派发最小权限子 agent(共享店铺状态+记忆)→
高风险动作弹审批卡(y=批准 / n=驳回 / 输入数字=改金额)→ 输出经营终态摘要,
全链路审计落盘 results/audit/cli-<tenant>.jsonl,记忆持久 .agent_memory/<tenant>.json。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.env.store import seed_store
from ecom_agent.governance import ApprovalDecision, ApprovalRequest, AuditLog
from ecom_agent.models.llm import claude_cli_completion
from ecom_agent.planner import plan_with_llm, run_subagent
from ecom_agent.memory import MemoryStore

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_approver(auto: bool):
    def _appr(req: ApprovalRequest) -> ApprovalDecision:
        print(f"\n🔔 审批请求 [{req.risk.value}] {req.tool}")
        print(f"   参数: {req.args}")
        if req.est_cost:
            print(f"   预估资金: {req.est_cost}")
        if auto:
            print("   (--yes 自动批准)")
            return ApprovalDecision(approved=True, note="auto")
        ans = input("   批准? [y=批准 / n=驳回 / 数字=改金额] ").strip()
        if ans.lower() in ("y", "yes"):
            return ApprovalDecision(approved=True)
        try:
            amt = float(ans)
            args = dict(req.args)
            args["amount" if "amount" in args else "budget"] = amt
            return ApprovalDecision(approved=True, modified_args=args, note=f"改额{amt}")
        except ValueError:
            return ApprovalDecision(approved=False, note="商家驳回")
    return _appr


def summarize(store):
    out = []
    if store.refunds:
        out.append(f"退款: {[(r.order_id, r.amount) for r in store.refunds.values()]}")
    if store.po_drafts:
        out.append(f"采购草稿: {store.po_drafts}")
    if store.coupons:
        out.append(f"活动/券: {store.coupons}")
    if store.outbox:
        out.append(f"外发消息: {[(m.get('to'), m.get('channel')) for m in store.outbox]}")
    if store.submitted:
        out.append(f"日报: {store.submitted}")
    drafts = [p.id for p in store.products.values() if p.status == "draft"]
    if drafts:
        out.append(f"商品草稿: {drafts}")
    return out or ["(无状态变化)"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instruction", help="一句话经营指令")
    ap.add_argument("--tenant", default="demo-shop")
    ap.add_argument("--yes", action="store_true", help="自动批准(演示)")
    args = ap.parse_args()

    complete = claude_cli_completion(MODEL)
    store = seed_store(args.tenant)
    memory = MemoryStore()
    approver = make_approver(args.yes)

    print(f"🏪 店铺 {args.tenant} | 模型 {MODEL}")
    print(f"📋 指令: {args.instruction}\n")

    plan = plan_with_llm(args.instruction, complete)
    if not plan:
        plan = [{"skill": "analytics", "instruction": args.instruction}]
    print("🧭 计划:")
    for i, s in enumerate(plan, 1):
        print(f"  {i}. [{s.get('skill')}] {s.get('instruction')}")

    print("\n🤖 执行:")
    master_audit = AuditLog()
    total_appr = total_viol = 0
    for step in plan:
        r = run_subagent(store, step["skill"], step["instruction"], complete,
                         memory=memory, approver=approver)
        total_appr += r.approvals
        total_viol += r.safety_viol
        print(f"  ✔ [{r.skill}] 工具:{r.tools} 审批:{r.approvals}")
        master_audit.record(kind="cli", action="step_done", skill=r.skill,
                            tools=r.tools, approvals=r.approvals)

    print("\n📦 经营终态:")
    for line in summarize(store):
        print(f"  - {line}")
    print(f"\n审批 {total_appr} 次 | 安全违规 {total_viol}(应为0) "
          f"| 记忆 {len(memory.recall(args.tenant, k=50))} 条")
    audit_path = os.path.join(ROOT, "results", "audit", f"cli-{args.tenant}.jsonl")
    master_audit.to_jsonl(audit_path)
    print(f"审计落盘: {audit_path}")


if __name__ == "__main__":
    main()
