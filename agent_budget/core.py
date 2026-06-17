"""
Core budget tracking: thread-local context, spend accumulation, limit enforcement.
"""

from __future__ import annotations

import contextvars
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

from .providers import price_for_tokens

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BudgetExceeded(Exception):
    """Raised when the budget limit is hit."""

    def __init__(
        self,
        spent: float,
        limit: float,
        context: "BudgetContext | None" = None,
    ) -> None:
        self.spent = spent
        self.limit = limit
        self.context = context
        super().__init__(
            f"Budget exceeded: spent ${spent:.4f} of ${limit:.2f} limit."
        )


# ---------------------------------------------------------------------------
# Spend entries
# ---------------------------------------------------------------------------

@dataclass
class SpendEntry:
    kind: Literal["llm", "x402", "tool", "custom"]
    amount_usd: float
    label: str
    timestamp: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# BudgetContext  (one per @budget invocation)
# ---------------------------------------------------------------------------

@dataclass
class BudgetContext:
    """Tracks all spending within a single @budget-decorated call."""

    max_usd: float
    on_exceed: Literal["raise", "warn", "ignore"] = "raise"
    _entries: list[SpendEntry] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def total_spent(self) -> float:
        return sum(e.amount_usd for e in self._entries)

    @property
    def remaining(self) -> float:
        return max(0.0, self.max_usd - self.total_spent)

    def add(self, entry: SpendEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            total = self.total_spent

        if total > self.max_usd:
            if self.on_exceed == "raise":
                raise BudgetExceeded(total, self.max_usd, self)
            elif self.on_exceed == "warn":
                import warnings
                warnings.warn(
                    f"agent-budget: spent ${total:.4f} exceeds limit ${self.max_usd:.2f}",
                    stacklevel=4,
                )

    def report(self) -> dict:
        return {
            "limit_usd": self.max_usd,
            "spent_usd": round(self.total_spent, 6),
            "remaining_usd": round(self.remaining, 6),
            "entries": [
                {
                    "kind": e.kind,
                    "amount_usd": round(e.amount_usd, 6),
                    "label": e.label,
                    "timestamp": e.timestamp,
                }
                for e in self._entries
            ],
        }

    def __repr__(self) -> str:
        return (
            f"BudgetContext(spent=${self.total_spent:.4f} / ${self.max_usd:.2f})"
        )


# ---------------------------------------------------------------------------
# Context variable (async-safe)
# ---------------------------------------------------------------------------

_current_budget: contextvars.ContextVar[BudgetContext | None] = (
    contextvars.ContextVar("_current_budget", default=None)
)


def get_current_budget() -> BudgetContext | None:
    return _current_budget.get()


# ---------------------------------------------------------------------------
# BudgetTracker  (public helper for manual tracking)
# ---------------------------------------------------------------------------

class BudgetTracker:
    """
    Manual tracker — use when you can't use the @budget decorator.

        tracker = BudgetTracker(max_usd=5.00)
        tracker.track_llm("claude-sonnet-4-6", input_tokens=1200, output_tokens=400)
        tracker.track_payment(amount_usd=0.50, label="data-fetch")
        print(tracker.report())
    """

    def __init__(
        self,
        max_usd: float,
        on_exceed: Literal["raise", "warn", "ignore"] = "raise",
    ) -> None:
        self._ctx = BudgetContext(max_usd=max_usd, on_exceed=on_exceed)

    def track_llm(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        label: str | None = None,
    ) -> float:
        """Record an LLM API call. Returns the USD cost."""
        cost = price_for_tokens(model, input_tokens, output_tokens)
        self._ctx.add(SpendEntry(
            kind="llm",
            amount_usd=cost,
            label=label or f"{model} ({input_tokens}in/{output_tokens}out)",
            meta={"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens},
        ))
        return cost

    def track_payment(self, amount_usd: float, label: str = "payment") -> None:
        """Record an x402 or other payment."""
        self._ctx.add(SpendEntry(kind="x402", amount_usd=amount_usd, label=label))

    def track_custom(self, amount_usd: float, label: str) -> None:
        """Record any other cost (tool call, API fee, etc.)."""
        self._ctx.add(SpendEntry(kind="custom", amount_usd=amount_usd, label=label))

    @property
    def spent(self) -> float:
        return self._ctx.total_spent

    @property
    def remaining(self) -> float:
        return self._ctx.remaining

    def report(self) -> dict:
        return self._ctx.report()

    def __repr__(self) -> str:
        return repr(self._ctx)
