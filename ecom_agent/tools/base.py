"""工具层基础设施 —— 每个工具显式声明风险等级与是否可逆/涉资金。

风险分级(对应 benchmark 的 🟢🟡🔴):
  READ          只读 / 出建议         —— 直接执行
  REVERSIBLE    可逆写(草稿/计划)    —— 按店铺策略,默认审批
  IRREVERSIBLE  不可逆 / 涉资金         —— 永远人工审批(HITL)
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class RiskTier(str, enum.Enum):
    READ = "read"             # 🟢
    REVERSIBLE = "reversible"  # 🟡
    IRREVERSIBLE = "irreversible"  # 🔴


@dataclass
class ToolCtx:
    """工具运行上下文。agent 永不直接持有长期凭证 —— 由治理层注入。"""
    store: Any                      # 当前店铺的 Store
    tenant_id: str
    audit: Any = None               # AuditLog
    dry_run: bool = False           # 评测/影子模式:只记录不真正落库
    money_cost: float = 0.0         # 本次工具调用的直接成本(广告/短信等)


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None
    money_cost: float = 0.0         # 该调用产生的直接资金成本


@dataclass
class Tool:
    name: str
    risk: RiskTier
    reversible: bool
    fn: Callable[[ToolCtx, dict], ToolResult]
    description: str = ""
    # 估算资金成本(用于预算护栏),默认 0
    cost_fn: Optional[Callable[[dict], float]] = None

    def estimate_cost(self, args: dict) -> float:
        return self.cost_fn(args) if self.cost_fn else 0.0

    def run(self, ctx: ToolCtx, args: dict) -> ToolResult:
        return self.fn(ctx, args)


class _Registry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool):
        self._tools[t.name] = t

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def all(self) -> dict[str, Tool]:
        return dict(self._tools)

    def specs(self) -> list[dict]:
        return [{"name": t.name, "risk": t.risk.value, "reversible": t.reversible,
                 "description": t.description} for t in self._tools.values()]


registry = _Registry()


def tool(name: str, risk: RiskTier, reversible: bool, description: str = "",
         cost_fn: Optional[Callable[[dict], float]] = None):
    """装饰器:把一个 fn(ctx, args)->ToolResult 注册为工具。"""
    def deco(fn):
        registry.register(Tool(name=name, risk=risk, reversible=reversible,
                               fn=fn, description=description, cost_fn=cost_fn))
        return fn
    return deco
