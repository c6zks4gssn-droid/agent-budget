"""
Tests for agent-budget.

Run: pytest tests/
"""

import asyncio
import pytest
import warnings

from agent_budget import budget, BudgetExceeded, BudgetTracker
from agent_budget.decorators import (
    track_llm,
    track_payment,
    track_cost,
    current_spend,
    budget_remaining,
    withBudget,
)
from agent_budget.providers import price_for_tokens, PRICE_TABLE


# ---------------------------------------------------------------------------
# Provider / price table
# ---------------------------------------------------------------------------

class TestPriceTable:
    def test_known_model(self):
        cost = price_for_tokens("gpt-4o", input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(2.50)

    def test_unknown_model_uses_default(self):
        cost = price_for_tokens("nonexistent-model-xyz", 1_000_000, 0)
        default_input_price = PRICE_TABLE["__default__"]["input"]
        assert cost == pytest.approx(default_input_price)

    def test_zero_tokens(self):
        assert price_for_tokens("gpt-4o", 0, 0) == 0.0

    def test_claude_pricing(self):
        # claude-sonnet-4-6: $3/M input, $15/M output
        cost = price_for_tokens("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.00)


# ---------------------------------------------------------------------------
# BudgetTracker (manual)
# ---------------------------------------------------------------------------

class TestBudgetTracker:
    def test_starts_at_zero(self):
        t = BudgetTracker(max_usd=10.00)
        assert t.spent == 0.0
        assert t.remaining == 10.0

    def test_track_llm(self):
        t = BudgetTracker(max_usd=10.00)
        cost = t.track_llm("gpt-4o-mini", input_tokens=100_000, output_tokens=10_000)
        assert cost > 0
        assert t.spent == pytest.approx(cost)

    def test_track_payment(self):
        t = BudgetTracker(max_usd=10.00)
        t.track_payment(2.50, "x402 data fetch")
        assert t.spent == pytest.approx(2.50)
        assert t.remaining == pytest.approx(7.50)

    def test_exceeds_raises(self):
        t = BudgetTracker(max_usd=1.00, on_exceed="raise")
        with pytest.raises(BudgetExceeded) as exc_info:
            t.track_payment(1.01, "over budget")
        assert exc_info.value.spent > 1.00
        assert exc_info.value.limit == 1.00

    def test_exceeds_warns(self):
        t = BudgetTracker(max_usd=1.00, on_exceed="warn")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            t.track_payment(1.50, "over budget")
        assert len(w) == 1
        assert "exceeds limit" in str(w[0].message).lower()

    def test_exceeds_ignore(self):
        t = BudgetTracker(max_usd=1.00, on_exceed="ignore")
        t.track_payment(5.00, "silent overage")
        assert t.spent == pytest.approx(5.00)  # no exception, no warning

    def test_report_structure(self):
        t = BudgetTracker(max_usd=5.00)
        t.track_payment(1.00, "test")
        report = t.report()
        assert "limit_usd" in report
        assert "spent_usd" in report
        assert "remaining_usd" in report
        assert len(report["entries"]) == 1


# ---------------------------------------------------------------------------
# @budget decorator — sync
# ---------------------------------------------------------------------------

class TestBudgetDecoratorSync:
    def test_basic(self):
        @budget(max_usd=5.00)
        def fn():
            track_payment(1.00, "payment")
            return "ok"

        assert fn() == "ok"

    def test_context_is_set_inside(self):
        @budget(max_usd=5.00)
        def fn():
            return budget_remaining()

        remaining = fn()
        assert remaining == pytest.approx(5.00)

    def test_tracking_inside(self):
        results = {}

        @budget(max_usd=5.00)
        def fn():
            track_payment(2.00, "x402 pay")
            results["spent"] = current_spend()

        fn()
        assert results["spent"] == pytest.approx(2.00)

    def test_raises_on_exceed(self):
        @budget(max_usd=1.00)
        def fn():
            track_payment(2.00, "too much")

        with pytest.raises(BudgetExceeded):
            fn()

    def test_context_cleared_after_call(self):
        @budget(max_usd=5.00)
        def fn():
            pass

        fn()
        # After the call, context should be cleared
        assert budget_remaining() == float("inf")
        assert current_spend() == 0.0

    def test_independent_calls(self):
        """Each call gets its own fresh budget."""
        call_spends = []

        @budget(max_usd=5.00)
        def fn():
            track_payment(1.00, "p")
            call_spends.append(current_spend())

        fn()
        fn()
        fn()
        # Each call should have spent exactly $1, not accumulated
        assert all(s == pytest.approx(1.00) for s in call_spends)


# ---------------------------------------------------------------------------
# @budget decorator — async
# ---------------------------------------------------------------------------

class TestBudgetDecoratorAsync:
    @pytest.mark.asyncio
    async def test_basic_async(self):
        @budget(max_usd=5.00)
        async def fn():
            track_payment(1.00, "async payment")
            return current_spend()

        spent = await fn()
        assert spent == pytest.approx(1.00)

    @pytest.mark.asyncio
    async def test_raises_async(self):
        @budget(max_usd=0.50)
        async def fn():
            track_payment(1.00, "over")

        with pytest.raises(BudgetExceeded):
            await fn()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="contextvar isolation in concurrent async — known limitation")
    async def test_concurrent_calls_isolated(self):
        """Concurrent async calls should have separate budget contexts."""
        results = []

        @budget(max_usd=5.00)
        async def fn(amount: float):
            await asyncio.sleep(0.01)
            track_payment(amount, "p")
            await asyncio.sleep(0.01)
            results.append(current_spend())

        await asyncio.gather(fn(1.00), fn(2.00), fn(3.00))
        # Each should only see its own spend
        assert set(pytest.approx(r) for r in results) == {
            pytest.approx(1.00),
            pytest.approx(2.00),
            pytest.approx(3.00),
        }


# ---------------------------------------------------------------------------
# withBudget wrapper
# ---------------------------------------------------------------------------

class TestWithBudget:
    def test_sync(self):
        def fn():
            track_payment(1.00, "p")
            return current_spend()

        safe = withBudget(fn, max_usd=5.00)
        assert safe() == pytest.approx(1.00)

    def test_exceeds(self):
        def fn():
            track_payment(10.00, "way over")

        safe = withBudget(fn, max_usd=1.00)
        with pytest.raises(BudgetExceeded):
            safe()

    def test_preserves_name(self):
        def my_agent():
            pass

        safe = withBudget(my_agent, max_usd=5.00)
        assert safe.__name__ == "my_agent"


# ---------------------------------------------------------------------------
# BudgetExceeded attributes
# ---------------------------------------------------------------------------

class TestBudgetExceededException:
    def test_attributes(self):
        @budget(max_usd=1.00)
        def fn():
            track_payment(1.50, "p")

        with pytest.raises(BudgetExceeded) as exc:
            fn()

        err = exc.value
        assert err.spent == pytest.approx(1.50)
        assert err.limit == pytest.approx(1.00)
        assert err.context is not None
        assert "1.50" in str(err)
