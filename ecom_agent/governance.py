"""电商治理层 —— pi/SDK 之外自建的部分,是本框架的核心壁垒。

5 个能力:
  AuditLog          全链路留痕(model/tool/approval)
  RiskPolicyEngine  按工具风险 + 店铺策略决定 放行/审批/拒绝
  ApprovalQueue     高风险动作挂起 → 人工决策(批准/改参/驳回)→ 恢复
  BudgetGuard       资金/调用次数护栏,超限熔断
  Governance        以上的门面,供 loop 调用
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .tools.base import RiskTier, Tool


# ---------------- 审计 ----------------

class AuditLog:
    def __init__(self):
        self.events: list[dict] = []

    def record(self, **ev):
        self.events.append(ev)

    def actions(self, action: str) -> list[dict]:
        return [e for e in self.events if e.get("action") == action]

    def count(self, kind: str) -> int:
        return sum(1 for e in self.events if e.get("kind") == kind)

    def to_jsonl(self, path: str):
        """全链路留痕落盘(每事件一行 JSON),供审计/复盘。"""
        import json
        import os
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")


# ---------------- 决策类型 ----------------

class Verdict(str, enum.Enum):
    ALLOW = "allow"        # 直接执行
    APPROVE = "approve"    # 需人工审批
    DENY = "deny"          # 拒绝


@dataclass
class ApprovalRequest:
    tool: str
    args: dict
    risk: RiskTier
    reason: str
    est_cost: float


@dataclass
class ApprovalDecision:
    approved: bool
    modified_args: Optional[dict] = None   # 商家改参(如改退款额)
    note: str = ""


# 审批者:模拟商家审批台。benchmark 里按题注入不同行为。
ApprovalDecider = Callable[[ApprovalRequest], ApprovalDecision]


def auto_approver(req: ApprovalRequest) -> ApprovalDecision:
    return ApprovalDecision(approved=True)


class ApprovalPending(Exception):
    """审批无法同步得到决策(真实商家是异步审批的)。
    loop 捕获后序列化 checkpoint 暂停;商家决策后 loop.resume 恢复。"""

    def __init__(self, request_id: str, request: ApprovalRequest):
        super().__init__(f"approval pending: {request_id}")
        self.request_id = request_id
        self.request = request


class ApprovalInbox:
    """异步审批收件箱:高风险动作挂起进箱,商家稍后 批准/改参/驳回。"""

    def __init__(self):
        self._n = 0
        self.pending: dict[str, ApprovalRequest] = {}

    def approver(self) -> ApprovalDecider:
        def _appr(req: ApprovalRequest) -> ApprovalDecision:
            self._n += 1
            rid = f"apr_{self._n:04d}"
            self.pending[rid] = req
            raise ApprovalPending(rid, req)
        return _appr

    def take(self, request_id: str) -> ApprovalRequest:
        return self.pending.pop(request_id)


# ---------------- 预算护栏 ----------------

class BudgetExceeded(Exception):
    pass


@dataclass
class BudgetGuard:
    money_cap: float = 1e9
    call_cap: int = 1000
    money_spent: float = 0.0
    calls: int = 0

    def check_and_add(self, money: float):
        if self.calls + 1 > self.call_cap:
            raise BudgetExceeded(f"call cap {self.call_cap} exceeded")
        if self.money_spent + money > self.money_cap + 1e-6:
            raise BudgetExceeded(f"money cap {self.money_cap} exceeded")
        self.calls += 1
        self.money_spent += money


# ---------------- 风险策略引擎 ----------------

class RiskPolicyEngine:
    def __init__(self, store_policy: dict):
        self.auto_reversible = store_policy.get("auto_apply_reversible", False)
        self.reversible_whitelist = set(store_policy.get("reversible_whitelist", []))

    def decide(self, tool: Tool) -> Verdict:
        if tool.risk == RiskTier.READ:
            return Verdict.ALLOW
        if tool.risk == RiskTier.REVERSIBLE:
            if self.auto_reversible or tool.name in self.reversible_whitelist:
                return Verdict.ALLOW
            return Verdict.APPROVE
        # IRREVERSIBLE 永远审批
        return Verdict.APPROVE


# ---------------- 治理门面 ----------------

@dataclass
class GovOutcome:
    executed: bool
    approved: Optional[bool]   # None 表示无需审批
    verdict: Verdict
    args_used: dict


class Governance:
    def __init__(self, store_policy: dict, audit: AuditLog,
                 approver: ApprovalDecider = auto_approver,
                 budget: Optional[BudgetGuard] = None,
                 enforce: bool = True):
        self.policy_engine = RiskPolicyEngine(store_policy)
        self.audit = audit
        self.approver = approver
        self.budget = budget or BudgetGuard()
        self.enforce = enforce       # False = 关闭治理(用于复现 v1 naive 的不安全行为)

    def gate(self, tool: Tool, args: dict, reason: str = "") -> GovOutcome:
        """工具调用前置闸门。返回是否放行执行 + 最终参数。"""
        if not self.enforce:
            # naive 模式:不拦截高风险动作(用于对照实验)
            return GovOutcome(executed=True, approved=None,
                              verdict=Verdict.ALLOW, args_used=args)

        verdict = self.policy_engine.decide(tool)
        self.audit.record(kind="gov", action="decide", tool=tool.name,
                          risk=tool.risk.value, verdict=verdict.value)

        if verdict == Verdict.ALLOW:
            return GovOutcome(True, None, verdict, args)

        if verdict == Verdict.DENY:
            return GovOutcome(False, False, verdict, args)

        # APPROVE:挂起 → 人工决策
        req = ApprovalRequest(tool=tool.name, args=args, risk=tool.risk,
                              reason=reason, est_cost=tool.estimate_cost(args))
        decision = self.approver(req)
        self.audit.record(kind="approval", action="resolve", tool=tool.name,
                          approved=decision.approved, note=decision.note)
        if not decision.approved:
            return GovOutcome(False, False, verdict, args)
        return GovOutcome(True, True, verdict, decision.modified_args or args)
