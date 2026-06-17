"""
Price tables for LLM providers (USD per 1M tokens).
Kept minimal and inline — no network calls required.

Last updated: June 2026. Override with custom prices if needed:

    from agent_budget import PRICE_TABLE
    PRICE_TABLE["my-model"] = {"input": 0.5, "output": 1.5}
"""

# USD per 1M tokens  {model: {input, output}}
PRICE_TABLE: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4-8":          {"input": 15.00,  "output": 75.00},
    "claude-sonnet-4-6":        {"input": 3.00,   "output": 15.00},
    "claude-haiku-4-5":         {"input": 0.80,   "output": 4.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022":  {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229":   {"input": 15.00,  "output": 75.00},

    # OpenAI
    "gpt-4o":                   {"input": 2.50,   "output": 10.00},
    "gpt-4o-mini":              {"input": 0.15,   "output": 0.60},
    "gpt-4-turbo":              {"input": 10.00,  "output": 30.00},
    "o3":                       {"input": 10.00,  "output": 40.00},
    "o3-mini":                  {"input": 1.10,   "output": 4.40},
    "o4-mini":                  {"input": 1.10,   "output": 4.40},

    # Google
    "gemini-2.0-flash":         {"input": 0.10,   "output": 0.40},
    "gemini-2.5-pro":           {"input": 1.25,   "output": 10.00},
    "gemini-2.5-flash":         {"input": 0.075,  "output": 0.30},

    # Meta / open weights (typical hosted pricing)
    "llama-3.3-70b-instruct":   {"input": 0.59,   "output": 0.79},
    "llama-3.1-405b-instruct":  {"input": 3.00,   "output": 3.00},

    # Mistral
    "mistral-large-latest":     {"input": 3.00,   "output": 9.00},
    "mistral-small-latest":     {"input": 0.10,   "output": 0.30},

    # Fallback for unknown models
    "__default__":              {"input": 5.00,   "output": 15.00},
}


def price_for_tokens(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a given token count. Falls back to __default__."""
    prices = PRICE_TABLE.get(model, PRICE_TABLE["__default__"])
    cost = (input_tokens / 1_000_000) * prices["input"]
    cost += (output_tokens / 1_000_000) * prices["output"]
    return cost
