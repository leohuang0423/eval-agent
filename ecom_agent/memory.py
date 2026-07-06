"""Memory —— 跨任务/跨运行的持久记忆(按租户隔离),并注入到 system prompt。

两类:
  semantic  店铺画像/商家偏好/政策细则(长期稳定,影响决策)
  episodic  过往动作与结果(审计/避免重复;近因优先)

存储:每租户一个 JSON 文件(可换 DB/向量库)。召回:按 skill/关键词过滤 + 近因,取 top-k。
这让 agent 具备"记住这家店怎么经营"的能力,而不是每次从零开始。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Optional

DEFAULT_DIR = os.environ.get("AGENT_MEMORY_DIR",
                             os.path.join(os.path.dirname(os.path.dirname(
                                 os.path.abspath(__file__))), ".agent_memory"))


@dataclass
class Note:
    kind: str            # "semantic" | "episodic"
    text: str
    skill: Optional[str] = None    # 关联技能域(便于召回)
    seq: int = 0                   # 写入序号(近因)


class MemoryStore:
    def __init__(self, base_dir: str = DEFAULT_DIR):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _path(self, tenant: str) -> str:
        return os.path.join(self.base_dir, f"{tenant}.json")

    def _load(self, tenant: str) -> list[dict]:
        p = self._path(tenant)
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, tenant: str, notes: list[dict]):
        with open(self._path(tenant), "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)

    def remember(self, tenant: str, text: str, kind: str = "episodic",
                 skill: Optional[str] = None):
        notes = self._load(tenant)
        notes.append(asdict(Note(kind=kind, text=text, skill=skill, seq=len(notes))))
        self._save(tenant, notes)

    def recall(self, tenant: str, skill: Optional[str] = None, k: int = 5) -> list[dict]:
        notes = self._load(tenant)
        # semantic 全保留;episodic 取与该 skill 相关的近因
        sem = [n for n in notes if n["kind"] == "semantic"
               and (skill is None or n.get("skill") in (None, skill))]
        epi = [n for n in notes if n["kind"] == "episodic"
               and (skill is None or n.get("skill") in (None, skill))]
        epi = sorted(epi, key=lambda n: n["seq"], reverse=True)[:k]
        return sem + epi

    def context(self, tenant: str, skill: Optional[str] = None, k: int = 5) -> str:
        """召回并格式化为可注入 system prompt 的一段文本。"""
        notes = self.recall(tenant, skill=skill, k=k)
        if not notes:
            return ""
        lines = ["【店铺记忆(请据此调整决策,但不得违反店铺红线政策)】"]
        for n in notes:
            tag = "偏好" if n["kind"] == "semantic" else "历史"
            lines.append(f"- [{tag}] {n['text']}")
        return "\n".join(lines)

    def clear(self, tenant: str):
        p = self._path(tenant)
        if os.path.exists(p):
            os.remove(p)
