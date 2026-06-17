"""
agent-budget: One-line spending control for AI agents.

    @budget(max_usd=10.00)
    async def my_agent(query: str):
        ...

Tracks LLM API costs + x402 payments. Raises BudgetExceeded when the limit is hit.
"""

from .core import BudgetContext, BudgetExceeded, BudgetTracker
from .decorators import budget, withBudget
from .providers import PRICE_TABLE

__version__ = "0.1.0"
__all__ = [
    "budget",
    "withBudget",
    "BudgetContext",
    "BudgetExceeded",
    "BudgetTracker",
    "PRICE_TABLE",
]
