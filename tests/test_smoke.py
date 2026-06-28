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


if __name__ == "__main__":
    unittest.main(verbosity=2)
