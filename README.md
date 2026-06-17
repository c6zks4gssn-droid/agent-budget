# agent-budget

**One-line spending control for AI agents.**

```python
@budget(max_usd=10.00)
async def my_agent(query: str):
    ...  # anything inside stays under $10
```

Tracks LLM API costs (Anthropic, OpenAI, Gemini, and more) plus x402 payments.  
Raises `BudgetExceeded` the moment your agent tries to go over.

---

## Install

```bash
pip install agent-budget
```

No required dependencies. Works with any LLM SDK.

---

## Quickstart

```python
from agent_budget import budget, BudgetExceeded
from agent_budget.decorators import track_llm, track_payment, current_spend

@budget(max_usd=5.00)
async def research_agent(query: str) -> str:
    # Call your LLM
    response = await llm.chat(query)

    # Manually record the cost (or use auto_patch=True)
    track_llm("claude-sonnet-4-6",
              input_tokens=response.usage.input_tokens,
              output_tokens=response.usage.output_tokens)

    # Fetch paid content via x402
    data = await fetch_x402("https://data.example.com/report")
    track_payment(0.10, label="x402 report fetch")

    print(f"Spent so far: ${current_spend():.4f}")
    return response.text


# Usage
try:
    result = await research_agent("latest AI research")
except BudgetExceeded as e:
    print(f"Agent hit the limit: spent ${e.spent:.4f} of ${e.limit:.2f}")
```

---

## Auto-patch (zero-instrumentation mode)

Let agent-budget automatically intercept every Anthropic or OpenAI call:

```python
@budget(max_usd=10.00, auto_patch=True)
async def my_agent(query: str):
    # Every client.messages.create() call is tracked — no manual tracking needed
    response = await anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": query}]
    )
    return response.content[0].text
```

Install with the extras:
```bash
pip install "agent-budget[anthropic]"   # auto-patch Anthropic SDK
pip install "agent-budget[openai]"      # auto-patch OpenAI SDK
pip install "agent-budget[all]"         # both
```

---

## Behaviour options

```python
@budget(
    max_usd=10.00,          # Hard limit in USD
    on_exceed="raise",      # "raise" | "warn" | "ignore"
    auto_patch=True,        # Auto-track Anthropic + OpenAI SDK calls
    report_on_exit=True,    # Print spend report when function exits
)
async def my_agent(): ...
```

| `on_exceed` | Behaviour |
|---|---|
| `"raise"` | Raises `BudgetExceeded` immediately (default) |
| `"warn"`  | Emits a `RuntimeWarning`, continues |
| `"ignore"` | Silent — useful for logging/testing |

---

## Manual tracking (no decorator)

```python
from agent_budget import BudgetTracker

tracker = BudgetTracker(max_usd=5.00)

# Record any LLM call
tracker.track_llm("gpt-4o", input_tokens=1200, output_tokens=400)

# Record an x402 payment
tracker.track_payment(amount_usd=0.25, label="data-purchase")

# Any custom cost
tracker.track_custom(amount_usd=0.01, label="tool-call-fee")

print(tracker.report())
# {
#   "limit_usd": 5.0,
#   "spent_usd": 0.030725,
#   "remaining_usd": 4.969275,
#   "entries": [...]
# }
```

---

## withBudget (functional style)

```python
from agent_budget import withBudget

safe_agent = withBudget(my_agent, max_usd=5.00)
result = await safe_agent("hello")
```

---

## Supported models (built-in price table)

| Provider | Models |
|---|---|
| **Anthropic** | claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5, claude-3.5-* |
| **OpenAI** | gpt-4o, gpt-4o-mini, o3, o3-mini, o4-mini, gpt-4-turbo |
| **Google** | gemini-2.0-flash, gemini-2.5-pro, gemini-2.5-flash |
| **Meta** | llama-3.3-70b, llama-3.1-405b |
| **Mistral** | mistral-large, mistral-small |

Unknown models fall back to `$5.00 / $15.00 per M tokens`. Override any price:

```python
from agent_budget import PRICE_TABLE
PRICE_TABLE["my-custom-model"] = {"input": 0.50, "output": 1.50}
```

---

## x402 integration

`agent-budget` tracks x402 payments when you call `track_payment()`.  
For full spending firewall enforcement on x402 payments, see  
[bonanza-labs.com](https://bonanza-labs.com) — production-grade policy engine  
with human approval queues, vendor blocklists, and audit logs.

---

## FAQ

**Does this make network calls?**  
No. The price table is entirely inline. Zero network calls, zero telemetry.

**Does this work with streaming?**  
Yes for manual tracking — call `track_llm()` with the final token counts from the stream's `usage` object. Auto-patch doesn't cover streaming yet (coming in 0.2.0).

**What if I nest @budget decorators?**  
Each call to a `@budget`-decorated function gets its own isolated context.  
Inner contexts don't affect outer ones — you can nest safely.

**Thread-safe?**  
Yes. Uses `contextvars.ContextVar` for async isolation and `threading.Lock` inside each context.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Built by [Bonanza Labs](https://bonanza-labs.com).  
For teams: managed dashboard, policy engine, and approval queue at **bonanza-labs.com/firewall**.
