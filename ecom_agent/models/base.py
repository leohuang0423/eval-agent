"""可插拔 model 接口 —— loop 不关心背后是 ScriptedModel(参考解)还是真实 LLM。"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    name: str
    args: dict
    reason: str = ""


@dataclass
class Final:
    output: Any


# 一步的产出:要么发起若干工具调用,要么给出最终答复
Action = Any  # Union[list[ToolCall], Final]


@dataclass
class Observation:
    name: str
    args: dict
    ok: bool
    data: Any
    error: Optional[str] = None
    executed: bool = True
    approved: Optional[bool] = None


class ModelClient(abc.ABC):
    """模型客户端。step 根据任务输入 + 历史观察,决定下一步动作。"""

    @abc.abstractmethod
    def step(self, task_input: dict, observations: list[Observation]) -> Action:
        ...

    # 估算本步 token 成本(用于效率/预算统计)。LLM 适配可重写为真实用量。
    def token_cost(self) -> int:
        return 0
