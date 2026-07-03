"""Agent Loop —— 内核:model.step → 治理拦截 → 执行/审批/恢复 → 回灌 → 重复。

与 Anthropic《Building Effective Agents》/ OpenAI Agents SDK 的 run loop 同构:
薄 loop,智能在 model + tools,安全在 governance。

支持异步审批中断/恢复(spec §3.3 的 GoalState):
  - approver 抛出 ApprovalPending → loop 序列化 checkpoint,返回 stopped="awaiting_approval"
  - 商家稍后决策 → loop.resume(checkpoint, ApprovalDecision) 从断点继续
    (批准→按原参/改参执行;驳回→把"被驳回"回灌给模型,由模型决定后续)
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

from .models.base import ModelClient, ToolCall, Final, Observation
from .tools.base import registry, ToolCtx, RiskTier
from .governance import (Governance, BudgetExceeded, ApprovalPending,
                         ApprovalDecision)


@dataclass
class RunResult:
    final: Any
    observations: list
    turns: int
    stopped: str                 # "final" | "max_turns" | "budget" | "awaiting_approval"
    token_cost: int
    money_cost: float
    approvals: int               # 已批准的审批次数
    unapproved_high_risk: int    # 未经审批就执行的高风险动作次数(安全红线,应=0)
    checkpoint: Optional[dict] = None   # stopped=="awaiting_approval" 时的可恢复断点


class AgentLoop:
    def __init__(self, model: ModelClient, governance: Governance,
                 ctx: ToolCtx, max_turns: int = 12, allowed_tools=None):
        self.model = model
        self.gov = governance
        self.ctx = ctx
        self.max_turns = max_turns
        # skill 最小权限:None=全部;否则只允许这些工具,越界的调用被拒并回灌
        self.allowed_tools = set(allowed_tools) if allowed_tools else None

    # ---------------- 入口 ----------------

    def run(self, task_input: dict) -> RunResult:
        st = {"task_input": task_input, "obs": [], "money": 0.0,
              "approvals": 0, "unapproved": 0, "turn": 0}
        return self._drive(st, pending=None)

    def resume(self, checkpoint: dict, decision: ApprovalDecision) -> RunResult:
        """从 awaiting_approval 断点恢复:先落实审批决策,再继续正常循环。"""
        st = {"task_input": checkpoint["task_input"],
              "obs": [Observation(**o) for o in checkpoint["observations"]],
              "money": checkpoint["money"], "approvals": checkpoint["approvals"],
              "unapproved": checkpoint["unapproved"], "turn": checkpoint["turn"]}
        call = ToolCall(**checkpoint["pending_call"])
        self.gov.audit.record(kind="approval", action="resolve", tool=call.name,
                              approved=decision.approved, note=decision.note,
                              resumed=True)
        if decision.approved:
            st["approvals"] += 1
            tool = registry.get(call.name)
            args = decision.modified_args or call.args
            stop = self._exec(tool, args, approved=True, st=st)
            if stop is not None:
                return stop
        else:
            st["obs"].append(Observation(
                name=call.name, args=call.args, ok=False, data=None,
                error="rejected_by_approver", executed=False, approved=False))
        rest = [ToolCall(**c) for c in checkpoint.get("remaining_calls", [])]
        return self._drive(st, pending=rest or None)

    # ---------------- 内核 ----------------

    def _drive(self, st: dict, pending) -> RunResult:
        if pending:   # 恢复时,先处理同批剩余调用
            stop = self._process_calls(pending, st)
            if stop is not None:
                return stop
        while st["turn"] < self.max_turns:
            action = self.model.step(st["task_input"], st["obs"])
            st["turn"] += 1
            if isinstance(action, Final):
                return self._result(action.output, st, "final")
            calls = action if isinstance(action, list) else [action]
            stop = self._process_calls(calls, st)
            if stop is not None:
                return stop
        return self._result(None, st, "max_turns")

    def _process_calls(self, calls: list, st: dict) -> Optional[RunResult]:
        for i, call in enumerate(calls):
            if not isinstance(call, ToolCall):
                continue
            # skill 越权:工具不在该任务允许集 → 拒绝并回灌(最小权限)
            if self.allowed_tools is not None and call.name not in self.allowed_tools:
                st["obs"].append(Observation(
                    name=call.name, args=call.args, ok=False, data=None,
                    error="tool_not_in_scope", executed=False))
                continue
            tool = registry.get(call.name)

            # —— 治理闸门(可能同步放行/审批,也可能抛 ApprovalPending 挂起)——
            try:
                outcome = self.gov.gate(tool, call.args, reason=call.reason)
            except ApprovalPending as p:
                res = self._result(None, st, "awaiting_approval")
                res.checkpoint = {
                    "task_input": st["task_input"],
                    "observations": [asdict(o) for o in st["obs"]],
                    "money": st["money"], "approvals": st["approvals"],
                    "unapproved": st["unapproved"], "turn": st["turn"],
                    "pending_call": {"name": call.name, "args": call.args,
                                     "reason": call.reason},
                    "remaining_calls": [
                        {"name": c.name, "args": c.args, "reason": c.reason}
                        for c in calls[i + 1:] if isinstance(c, ToolCall)],
                    "approval_id": p.request_id,
                }
                return res

            if outcome.approved is True:
                st["approvals"] += 1
            if not outcome.executed:
                st["obs"].append(Observation(
                    name=call.name, args=call.args, ok=False, data=None,
                    error="blocked_or_rejected", executed=False,
                    approved=outcome.approved))
                continue
            stop = self._exec(tool, outcome.args_used, outcome.approved, st)
            if stop is not None:
                return stop
        return None

    def _exec(self, tool, args: dict, approved, st: dict) -> Optional[RunResult]:
        """预算护栏 + 执行 + 回灌。返回 RunResult 表示熔断终止,None 表示继续。"""
        est = tool.estimate_cost(args)
        try:
            self.gov.budget.check_and_add(est)
        except BudgetExceeded as e:
            st["obs"].append(Observation(name=tool.name, args=args, ok=False,
                                         data=None, error=str(e), executed=False))
            return self._result(None, st, "budget")
        # 安全红线:高风险动作"真正执行"却未经审批,才记违规
        if tool.risk == RiskTier.IRREVERSIBLE and approved is not True:
            st["unapproved"] += 1
        res = tool.run(self.ctx, args)
        st["money"] += res.money_cost
        st["obs"].append(Observation(name=tool.name, args=args, ok=res.ok,
                                     data=res.data, error=res.error,
                                     executed=True, approved=approved))
        return None

    def _result(self, final, st: dict, stopped: str) -> RunResult:
        return RunResult(final=final, observations=st["obs"], turns=st["turn"],
                         stopped=stopped, token_cost=self.model.token_cost(),
                         money_cost=st["money"], approvals=st["approvals"],
                         unapproved_high_risk=st["unapproved"])
