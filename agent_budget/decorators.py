"""
@budget decorator and withBudget wrapper.

Usage (async):
    @budget(max_usd=10.00)
    async def my_agent(query: str):
        ...

Usage (sync):
    @budget(max_usd=5.00, on_exceed="warn")
    def run_agent(query: str):
        ...

Usage (TypeScript-style wrapper for sync functions):
    safe_agent = withBudget(my_agent, max_usd=10.00)
    result = safe_agent("hello")

Auto-patching:
    When installed, agent-budget can auto-patch the Anthropic and OpenAI SDKs
    so that every API call within a @budget context is tracked automatically.
    Enable with: budget(max_usd=10.00, auto_patch=True)
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Callable, Literal, TypeVar

from .core import BudgetContext, SpendEntry, _current_budget, get_current_budget
from .providers import price_for_tokens

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Auto-patch helpers
# ---------------------------------------------------------------------------

def _patch_anthropic(ctx: BudgetContext) -> Callable:
    """Monkey-patch anthropic.Anthropic.messages.create to track token usage."""
    try:
        import anthropic as _anthropic

        original_create = _anthropic.resources.messages.Messages.create

        @functools.wraps(original_create)
        def patched_create(self, *args, **kwargs):  # type: ignore[override]
            response = original_create(self, *args, **kwargs)
            try:
                model = kwargs.get("model", "claude-sonnet-4-6")
                usage = getattr(response, "usage", None)
                if usage:
                    cost = price_for_tokens(
                        model,
                        getattr(usage, "input_tokens", 0),
                        getattr(usage, "output_tokens", 0),
                    )
                    current = get_current_budget()
                    if current is ctx:
                        ctx.add(SpendEntry(
                            kind="llm",
                            amount_usd=cost,
                            label=f"anthropic/{model}",
                            meta={"model": model},
                        ))
            except Exception:
                pass
            return response

        _anthropic.resources.messages.Messages.create = patched_create  # type: ignore

        def unpatch():
            _anthropic.resources.messages.Messages.create = original_create  # type: ignore

        return unpatch
    except ImportError:
        return lambda: None


def _patch_openai(ctx: BudgetContext) -> Callable:
    """Monkey-patch openai.OpenAI.chat.completions.create to track token usage."""
    try:
        import openai as _openai

        original_create = _openai.resources.chat.completions.Completions.create

        @functools.wraps(original_create)
        def patched_create(self, *args, **kwargs):  # type: ignore[override]
            response = original_create(self, *args, **kwargs)
            try:
                model = kwargs.get("model", "gpt-4o")
                usage = getattr(response, "usage", None)
                if usage:
                    cost = price_for_tokens(
                        model,
                        getattr(usage, "prompt_tokens", 0),
                        getattr(usage, "completion_tokens", 0),
                    )
                    current = get_current_budget()
                    if current is ctx:
                        ctx.add(SpendEntry(
                            kind="llm",
                            amount_usd=cost,
                            label=f"openai/{model}",
                            meta={"model": model},
                        ))
            except Exception:
                pass
            return response

        _openai.resources.chat.completions.Completions.create = patched_create  # type: ignore

        def unpatch():
            _openai.resources.chat.completions.Completions.create = original_create  # type: ignore

        return unpatch
    except ImportError:
        return lambda: None


# ---------------------------------------------------------------------------
# Core decorator factory
# ---------------------------------------------------------------------------

def budget(
    max_usd: float,
    per: Literal["call", "session"] = "call",
    on_exceed: Literal["raise", "warn", "ignore"] = "raise",
    auto_patch: bool = False,
    report_on_exit: bool = False,
) -> Callable[[F], F]:
    """
    Decorator factory that wraps a function with a spending budget.

    Args:
        max_usd:        Maximum spend in USD before BudgetExceeded is raised.
        per:            "call" creates a fresh budget each invocation (default).
                        "session" is a synonym for "call" at this time.
        on_exceed:      "raise"  → raise BudgetExceeded (default)
                        "warn"   → emit a RuntimeWarning and continue
                        "ignore" → silently continue
        auto_patch:     If True, monkey-patch Anthropic & OpenAI SDKs to
                        automatically track every API call inside the function.
        report_on_exit: If True, print a spend report when the function exits.
    """
    def decorator(fn: F) -> F:
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                ctx = BudgetContext(max_usd=max_usd, on_exceed=on_exceed)
                token = _current_budget.set(ctx)
                unpatchers: list[Callable] = []
                if auto_patch:
                    unpatchers.append(_patch_anthropic(ctx))
                    unpatchers.append(_patch_openai(ctx))
                try:
                    result = await fn(*args, **kwargs)
                    return result
                finally:
                    _current_budget.reset(token)
                    for unpatch in unpatchers:
                        unpatch()
                    if report_on_exit:
                        import json
                        print(f"[agent-budget] {fn.__name__}: {json.dumps(ctx.report(), indent=2)}")

            return async_wrapper  # type: ignore

        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                ctx = BudgetContext(max_usd=max_usd, on_exceed=on_exceed)
                token = _current_budget.set(ctx)
                unpatchers: list[Callable] = []
                if auto_patch:
                    unpatchers.append(_patch_anthropic(ctx))
                    unpatchers.append(_patch_openai(ctx))
                try:
                    result = fn(*args, **kwargs)
                    return result
                finally:
                    _current_budget.reset(token)
                    for unpatch in unpatchers:
                        unpatch()
                    if report_on_exit:
                        import json
                        print(f"[agent-budget] {fn.__name__}: {json.dumps(ctx.report(), indent=2)}")

            return sync_wrapper  # type: ignore

    return decorator


# ---------------------------------------------------------------------------
# withBudget  (TypeScript-inspired functional wrapper)
# ---------------------------------------------------------------------------

def withBudget(
    fn: F,
    max_usd: float,
    on_exceed: Literal["raise", "warn", "ignore"] = "raise",
    auto_patch: bool = False,
) -> F:
    """
    Functional alternative to @budget for when you can't use the decorator syntax.

        safe_agent = withBudget(my_agent, max_usd=5.00)
        result = safe_agent("hello")
    """
    return budget(max_usd=max_usd, on_exceed=on_exceed, auto_patch=auto_patch)(fn)


# ---------------------------------------------------------------------------
# Convenience functions for manual tracking within a @budget context
# ---------------------------------------------------------------------------

def track_llm(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Manually record an LLM API call inside a @budget context.
    Returns the USD cost. No-op if called outside a @budget context.

        response = client.messages.create(model="claude-sonnet-4-6", ...)
        track_llm("claude-sonnet-4-6", response.usage.input_tokens, response.usage.output_tokens)
    """
    ctx = get_current_budget()
    if ctx is None:
        return 0.0
    cost = price_for_tokens(model, input_tokens, output_tokens)
    ctx.add(SpendEntry(kind="llm", amount_usd=cost, label=f"{model} ({input_tokens}in/{output_tokens}out)"))
    return cost


def track_payment(amount_usd: float, label: str = "payment") -> None:
    """
    Manually record an x402 or other payment inside a @budget context.
    No-op if called outside a @budget context.
    """
    ctx = get_current_budget()
    if ctx is None:
        return
    ctx.add(SpendEntry(kind="x402", amount_usd=amount_usd, label=label))


def track_cost(amount_usd: float, label: str) -> None:
    """
    Record any arbitrary cost (tool fee, external API, etc.) inside a @budget context.
    """
    ctx = get_current_budget()
    if ctx is None:
        return
    ctx.add(SpendEntry(kind="custom", amount_usd=amount_usd, label=label))


def current_spend() -> float:
    """Return total USD spent so far in the current @budget context, or 0.0."""
    ctx = get_current_budget()
    return ctx.total_spent if ctx else 0.0


def budget_remaining() -> float:
    """Return USD remaining in the current @budget context, or float('inf')."""
    ctx = get_current_budget()
    return ctx.remaining if ctx else float("inf")
