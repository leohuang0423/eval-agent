"""Agent Loop —— 内核:model.step → 治理拦截 → 执行/审批/恢复 → 回灌 → 重复。

与 Anthropic《Building Effective Agents》/ OpenAI Agents SDK 的 run loop 同构:
薄 loop,智能在 model + tools,安全在 governance。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .models.base import ModelClient, ToolCall, Final, Observation
from .tools.base import registry, ToolCtx
from .governance import Governance, BudgetExceeded


@dataclass
class RunResult:
    final: Any
    observations: list
    turns: int
    stopped: str                 # "final" | "max_turns" | "budget"
    token_cost: int
    money_cost: float
    approvals: int               # 触发审批次数
    unapproved_high_risk: int    # 未经审批就执行的高风险动作次数(安全红线,应=0)


class AgentLoop:
    def __init__(self, model: ModelClient, governance: Governance,
                 ctx: ToolCtx, max_turns: int = 12):
        self.model = model
        self.gov = governance
        self.ctx = ctx
        self.max_turns = max_turns

    def run(self, task_input: dict) -> RunResult:
        observations: list[Observation] = []
        money = 0.0
        approvals = 0
        unapproved_high = 0
        stopped = "max_turns"
        final = None

        for turn in range(self.max_turns):
            action = self.model.step(task_input, observations)

            if isinstance(action, Final):
                final, stopped = action.output, "final"
                break

            calls = action if isinstance(action, list) else [action]
            for call in calls:
                if not isinstance(call, ToolCall):
                    continue
                tool = registry.get(call.name)

                # —— 治理闸门 ——
                outcome = self.gov.gate(tool, call.args, reason=call.reason)
                if outcome.approved is True:
                    approvals += 1
                # 安全红线:高风险动作在"未经审批"的情况下被执行
                from .tools.base import RiskTier
                if (tool.risk == RiskTier.IRREVERSIBLE and outcome.executed
                        and outcome.approved is not True):
                    unapproved_high += 1

                if not outcome.executed:
                    observations.append(Observation(
                        name=call.name, args=call.args, ok=False, data=None,
                        error="blocked_or_rejected", executed=False,
                        approved=outcome.approved))
                    continue

                # —— 预算护栏 + 执行 ——
                est = tool.estimate_cost(outcome.args_used)
                try:
                    self.gov.budget.check_and_add(est)
                except BudgetExceeded as e:
                    stopped = "budget"
                    observations.append(Observation(
                        name=call.name, args=outcome.args_used, ok=False,
                        data=None, error=str(e), executed=False))
                    return self._result(final, observations, turn + 1, stopped,
                                        money, approvals, unapproved_high)

                res = tool.run(self.ctx, outcome.args_used)
                money += res.money_cost
                observations.append(Observation(
                    name=call.name, args=outcome.args_used, ok=res.ok,
                    data=res.data, error=res.error, executed=True,
                    approved=outcome.approved))

            if stopped == "budget":
                break

        return self._result(final, observations, turn + 1, stopped, money,
                            approvals, unapproved_high)

    def _result(self, final, obs, turns, stopped, money, approvals, unapproved):
        return RunResult(final=final, observations=obs, turns=turns, stopped=stopped,
                         token_cost=self.model.token_cost(), money_cost=money,
                         approvals=approvals, unapproved_high_risk=unapproved)
