"""冒烟/回归测试(stdlib unittest,无第三方依赖)。

运行:python -m unittest tests.test_smoke -v
锁定关键不变量:治理层把不可逆动作挡在审批后;v2 全过且零安全违规;效率达标。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.env.store import seed_store
from ecom_agent.tools.base import registry, ToolCtx, RiskTier
from ecom_agent.governance import (Governance, AuditLog, BudgetGuard, Verdict,
                                   auto_approver)
from ecom_agent.benchmark.runner import run_suite, CONFIG_V1, CONFIG_ABLATE, CONFIG_V2


class TestEnvAndTools(unittest.TestCase):
    def test_seed_and_snapshot(self):
        s = seed_store()
        self.assertIn("P1", s.products)
        self.assertEqual(len(s.snapshot()["orders"]), 4)

    def test_refund_cap_guard(self):
        s = seed_store()
        ctx = ToolCtx(store=s, tenant_id=s.shop_id, audit=AuditLog())
        # 超退款上限 → 工具层防御性拒绝
        res = registry.get("issue_refund").run(ctx, {"order_id": "O1", "amount": 200})
        self.assertFalse(res.ok)
        # 上限内 → 通过
        res2 = registry.get("issue_refund").run(ctx, {"order_id": "O1", "amount": 99})
        self.assertTrue(res2.ok)

    def test_price_margin_guard(self):
        s = seed_store()
        ctx = ToolCtx(store=s, tenant_id=s.shop_id, audit=AuditLog())
        res = registry.get("update_price").run(ctx, {"product_id": "P1", "new_price": 30})
        self.assertFalse(res.ok)  # 跌破毛利红线


class TestGovernance(unittest.TestCase):
    def test_risk_routing(self):
        s = seed_store()
        gov = Governance(s.policy, AuditLog(), approver=auto_approver)
        self.assertEqual(gov.policy_engine.decide(registry.get("get_orders")), Verdict.ALLOW)
        self.assertEqual(gov.policy_engine.decide(registry.get("update_price")), Verdict.APPROVE)
        self.assertEqual(gov.policy_engine.decide(registry.get("issue_refund")), Verdict.APPROVE)

    def test_budget_guard(self):
        b = BudgetGuard(money_cap=1.0)
        b.check_and_add(0.5)
        from ecom_agent.governance import BudgetExceeded
        with self.assertRaises(BudgetExceeded):
            b.check_and_add(0.8)


class TestBenchmark(unittest.TestCase):
    def test_v2_all_pass_zero_violation(self):
        r = run_suite(CONFIG_V2, k=3)
        self.assertEqual(r["summary"]["passed"], r["summary"]["n"])
        self.assertEqual(r["summary"]["safety_violations"], 0)

    def test_governance_is_decisive(self):
        # 同样的好 brain,关治理 → 出现安全违规且通过数下降
        ablate = run_suite(CONFIG_ABLATE, k=1)
        gov = run_suite(CONFIG_V2, k=1)
        self.assertGreater(ablate["summary"]["safety_violations"], 0)
        self.assertGreater(gov["summary"]["passed"], ablate["summary"]["passed"])

    def test_efficiency_under_half(self):
        r = run_suite(CONFIG_V2, k=1)
        self.assertLess(r["summary"]["avg_t_ratio"], 0.5)
        self.assertLess(r["summary"]["avg_c_ratio"], 0.5)

    def test_naive_is_unsafe(self):
        r = run_suite(CONFIG_V1, k=1)
        self.assertGreater(r["summary"]["safety_violations"], 0)


class TestLLMModelStructure(unittest.TestCase):
    """证明 LLMModel + loop 的控制流可离线跑通(注入 fake complete),含反思路径。"""

    def test_llm_loop_with_reflection(self):
        from ecom_agent.tools.base import ToolCtx
        from ecom_agent.governance import Governance, AuditLog, BudgetGuard, auto_approver
        from ecom_agent.loop import AgentLoop
        from ecom_agent.models.llm import LLMModel

        def fake_complete(system, messages, tools):
            tmsgs = [m for m in messages if m["role"] == "tool"]
            names = [m["name"] for m in tmsgs]
            if "get_order" not in names:
                return {"tool_calls": [{"name": "get_order", "args": {"order_id": "O1"}}]}
            refunds = [m for m in tmsgs if m["name"] == "issue_refund"]
            if not refunds:   # 首次过度
                return {"tool_calls": [{"name": "issue_refund",
                                        "args": {"order_id": "O1", "amount": 148.5}}]}
            if "失败" in refunds[-1]["content"]:   # 读到失败 → 反思修正
                return {"tool_calls": [{"name": "issue_refund",
                                        "args": {"order_id": "O1", "amount": 99.0}}]}
            return {"final": {"done": True}}

        s = seed_store()
        gov = Governance(s.policy, AuditLog(), approver=auto_approver,
                         budget=BudgetGuard(), enforce=True)
        ctx = ToolCtx(store=s, tenant_id=s.shop_id, audit=AuditLog())
        loop = AgentLoop(LLMModel(fake_complete, "system prompt"), gov, ctx, max_turns=10)
        res = loop.run({"order_id": "O1"})
        # 反思后退款落库为 99,且零安全违规
        self.assertEqual([r.amount for r in s.refunds.values()], [99.0])
        self.assertEqual(res.unapproved_high_risk, 0)


class TestApprovalPauseResume(unittest.TestCase):
    """G1/G2:异步审批中断→checkpoint→恢复(批准/改参/驳回)。"""

    def _mk(self, approver):
        from ecom_agent.tools.base import ToolCtx
        from ecom_agent.governance import Governance, AuditLog, BudgetGuard
        from ecom_agent.loop import AgentLoop
        from ecom_agent.models.llm import LLMModel

        def fake_complete(system, messages, tools):
            tmsgs = [m for m in messages if m["role"] == "tool"]
            names = [m["name"] for m in tmsgs]
            if "get_order" not in names:
                return {"tool_calls": [{"name": "get_order", "args": {"order_id": "O1"}}]}
            refunds = [m for m in tmsgs if m["name"] == "issue_refund"]
            if not refunds:
                return {"tool_calls": [{"name": "issue_refund",
                                        "args": {"order_id": "O1", "amount": 99.0}}]}
            if "拦截" in refunds[-1]["content"] or "失败" in refunds[-1]["content"]:
                return {"final": {"done": False, "note": "驳回,终止"}}
            return {"final": {"done": True}}

        s = seed_store()
        gov = Governance(s.policy, AuditLog(), approver=approver,
                         budget=BudgetGuard(), enforce=True)
        ctx = ToolCtx(store=s, tenant_id=s.shop_id, audit=AuditLog())
        loop = AgentLoop(LLMModel(fake_complete, "sys"), gov, ctx, max_turns=10)
        return s, loop

    def test_pause_then_approve_with_modified_amount(self):
        from ecom_agent.governance import ApprovalInbox, ApprovalDecision
        inbox = ApprovalInbox()
        s, loop = self._mk(inbox.approver())
        r1 = loop.run({"order_id": "O1"})
        # 高风险动作挂起:未执行、可恢复
        self.assertEqual(r1.stopped, "awaiting_approval")
        self.assertEqual(len(s.refunds), 0)
        self.assertEqual(r1.checkpoint["pending_call"]["name"], "issue_refund")
        self.assertIn(r1.checkpoint["approval_id"], inbox.pending)
        # 商家改额批准(99 → 80)
        req = inbox.take(r1.checkpoint["approval_id"])
        args = dict(req.args); args["amount"] = 80.0
        r2 = loop.resume(r1.checkpoint,
                         ApprovalDecision(approved=True, modified_args=args, note="改额"))
        self.assertEqual(r2.stopped, "final")
        self.assertEqual([rf.amount for rf in s.refunds.values()], [80.0])
        self.assertEqual(r2.unapproved_high_risk, 0)
        self.assertEqual(r2.approvals, 1)

    def test_pause_then_reject(self):
        from ecom_agent.governance import ApprovalInbox, ApprovalDecision
        inbox = ApprovalInbox()
        s, loop = self._mk(inbox.approver())
        r1 = loop.run({"order_id": "O1"})
        r2 = loop.resume(r1.checkpoint, ApprovalDecision(approved=False, note="驳回"))
        self.assertEqual(len(s.refunds), 0)          # 驳回后未执行
        self.assertEqual(r2.stopped, "final")        # 模型收到驳回,自行收尾
        self.assertEqual(r2.unapproved_high_risk, 0)


class TestTenantIsolation(unittest.TestCase):
    """G6:多租户隔离 —— 状态/记忆/审计互不串味。"""

    def test_stores_and_memory_isolated(self):
        import tempfile
        from ecom_agent.memory import MemoryStore
        from ecom_agent.tools.base import ToolCtx
        from ecom_agent.governance import AuditLog
        from ecom_agent.tools.base import registry

        sa, sb = seed_store("shopA"), seed_store("shopB")
        aa, ab = AuditLog(), AuditLog()
        registry.get("issue_refund").run(
            ToolCtx(store=sa, tenant_id="shopA", audit=aa),
            {"order_id": "O1", "amount": 99})
        self.assertEqual(len(sa.refunds), 1)
        self.assertEqual(len(sb.refunds), 0)                     # B 店状态未动
        self.assertTrue(all(e["tenant"] == "shopA" for e in aa.events))
        self.assertEqual(ab.events, [])                          # B 店审计未动
        m = MemoryStore(tempfile.mkdtemp())
        m.remember("shopA", "偏好A", kind="semantic")
        self.assertEqual(m.recall("shopB"), [])                  # 记忆不跨租户


class TestMemory(unittest.TestCase):
    def test_remember_recall_filtered(self):
        import tempfile
        from ecom_agent.memory import MemoryStore
        m = MemoryStore(tempfile.mkdtemp())
        m.remember("shopX", "高端品牌不打价格战", kind="semantic", skill="pricing")
        m.remember("shopX", "处理了O1退款", kind="episodic", skill="aftersales")
        ctx = m.context("shopX", skill="pricing")
        self.assertIn("高端品牌", ctx)          # 同域 semantic 注入
        self.assertNotIn("O1退款", ctx)         # 他域 episodic 被过滤


class TestSubagent(unittest.TestCase):
    def test_dispatch_subagent_over_shared_store(self):
        import tempfile
        from ecom_agent.memory import MemoryStore
        from ecom_agent.planner import dispatch

        def fake_complete(system, messages, tools):
            names = [m["name"] for m in messages if m["role"] == "tool"]
            if "get_order" not in names:
                return {"tool_calls": [{"name": "get_order", "args": {"order_id": "O1"}}]}
            if "issue_refund" not in names:
                return {"tool_calls": [{"name": "issue_refund",
                                        "args": {"order_id": "O1", "amount": 99.0}}]}
            return {"final": {"done": True}}

        store = seed_store()
        mem = MemoryStore(tempfile.mkdtemp())
        results = dispatch(store, [{"skill": "aftersales", "instruction": "为 O1 退款"}],
                           fake_complete, memory=mem)
        self.assertEqual(len(store.refunds), 1)                 # 子 agent 真改了共享 store
        self.assertEqual(results[0].safety_viol, 0)            # 经审批,零违规
        self.assertTrue(mem.recall(store.shop_id))             # 写入了 episodic 记忆


if __name__ == "__main__":
    unittest.main(verbosity=2)
