---
name: openrouter-llm
description: How to write backend code that calls LLMs through LiteLLM using OpenRouter's free models only (IDs ending in :free, no credit card), defaulting to nvidia/nemotron-3-super-120b-a12b:free with Structured Outputs parsed into Pydantic models. Use whenever writing or changing code in this project that calls an LLM through OpenRouter.
---

# LLM calls via LiteLLM → OpenRouter (free models only)

- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free` (LiteLLM model string). OpenRouter dropped the free
  `openai/gpt-oss-120b:free` in October 2026 (no providers left); it is slower than
  Groq (about 15-30 s per structured call), so give it a 60 s timeout.
- Key: `OPENROUTER_API_KEY` in `.env` at the project root. Never hard-code or
  log it.
- Cost: $0. **Only model IDs ending in `:free` are free.** Never use the plain
  `openrouter/openai/gpt-oss-120b`, and never pin a paid inference provider
  (for example Cerebras) via `provider.order` — both bill per token.
- Limits: about 20 requests/minute and 50 requests/day on free models, shared
  across all keys on the account (rises to 1,000/day only after a one-time
  $10 credit purchase, which is optional).
- If the `groq-llm` skill is also present, Groq is the primary provider and
  this model is the fallback; follow that skill's "Fallback" section.

## Dependencies

```bash
cd backend
uv add litellm pydantic python-dotenv
```

## Canonical client — `backend/app/llm.py`

```python
import os
from typing import TypeVar

from dotenv import load_dotenv
from litellm import acompletion
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)

MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"


async def complete_structured(messages: list[dict], schema: type[T]) -> T:
    """Call an OpenRouter free model and return a validated instance of `schema`."""
    resp = await acompletion(
        model=MODEL,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        messages=messages,
        response_format=schema,   # LiteLLM converts Pydantic -> json_schema
        temperature=0.2,
        num_retries=2,            # retries 429s with backoff
        timeout=60,
        # Route only to providers that honour response_format
        extra_body={"provider": {"require_parameters": True}},
    )
    return schema.model_validate_json(resp.choices[0].message.content)
```

Usage in a FastAPI route:

```python
from pydantic import BaseModel, Field
from app.llm import complete_structured

class NDAFields(BaseModel):
    party_one_name: str | None = Field(description="First party legal name, or null if not yet known")
    party_two_name: str | None
    effective_date: str | None = Field(description="ISO date YYYY-MM-DD, or null")
    governing_law: str | None
    reply: str = Field(description="Message to show the user in chat")

result = await complete_structured(
    [{"role": "system", "content": SYSTEM_PROMPT}, *chat_history],
    NDAFields,
)
```

## Structured Outputs rules

Write schemas so they also work on strict providers (Groq):

- Every field **required**; for optional values use `X | None` with no default.
- Nested objects as nested Pydantic models; no `dict[str, Any]`.
- Don't combine Structured Outputs with streaming or tool calls.
- Always validate with `model_validate_json` and handle `ValidationError`:
  re-ask once, then return a friendly error. Free providers occasionally
  return malformed JSON, so this matters more here than on paid routes.

## Free-model fallbacks

Free models are rate-limited hard at peak times and can be removed without
notice. To stay free when one is unavailable, list other `:free` models as
OpenRouter fallbacks (OpenRouter tries them in order):

```python
extra_body={
    "models": ["nvidia/nemotron-3-super-120b-a12b:free", "<another-model>:free"],
    "provider": {"require_parameters": True},
}
```

Check what's currently free at https://openrouter.ai/models?max_price=0 and
only add models whose ID ends in `:free` and that support structured outputs.

## Errors and limits

- `litellm.RateLimitError` after retries → HTTP 503 with "The assistant is
  busy, please try again in a minute." Never crash the request.
- HTTP 402 means the account balance went negative; free models stop working
  until it's back to $0 or above. Never top up into a paid route by accident.
- Extra accounts or keys don't add capacity; limits are per account.
- Don't put real client secrets or sensitive personal data in prompts; free
  providers may log prompts.

## Testing

Unit tests must not hit the network: patch `app.llm.acompletion` with
`unittest.mock.AsyncMock` returning an object whose
`choices[0].message.content` is valid JSON for the schema. Keep one optional
integration test marked `@pytest.mark.integration` that runs only when
`OPENROUTER_API_KEY` is set.
