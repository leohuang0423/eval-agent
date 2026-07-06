"""ScriptedModel —— 用确定性"brain"函数充当 agent 大脑。

定位:既是 benchmark 的参考解 / oracle(让整套 loop+治理+终态校验在无 LLM 时
也能端到端跑通、可复现),也是真实 LLM 接入前的对照基线。brain 读取任务输入与
历史观察,返回下一步动作(工具调用或最终答复),与真实 LLM 的 ReAct 循环同构。
"""
from __future__ import annotations

from typing import Callable

from .base import ModelClient, Action, Observation


# brain 签名:(task_input, observations) -> Action
Brain = Callable[[dict, list], Action]


class ScriptedModel(ModelClient):
    def __init__(self, brain: Brain, est_tokens_per_step: int = 800):
        self.brain = brain
        self._tokens = 0
        self._per_step = est_tokens_per_step

    def step(self, task_input: dict, observations: list[Observation]) -> Action:
        self._tokens += self._per_step
        return self.brain(task_input, observations)

    def token_cost(self) -> int:
        return self._tokens
