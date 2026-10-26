---
name: groq-llm
description: How to write backend code that calls LLMs through LiteLLM using Groq's free tier (no credit card) with the openai/gpt-oss-120b model and Structured Outputs parsed into Pydantic models. Use whenever writing or changing code in this project that calls an LLM.
---

# LLM calls via LiteLLM → Groq (free tier)

- Model: `groq/openai/gpt-oss-120b` (LiteLLM model string)
- Key: `GROQ_API_KEY` in `.env` at the project root. Never hard-code or log it.
- Cost: $0. Groq's free tier needs no credit card and is limited only by rate
  limits (roughly 30 requests/minute, plus per-model daily caps; current
  numbers at https://console.groq.com/settings/limits).
- Fallback: if the `openrouter-llm` skill is also present, use OpenRouter's
  free model as the fallback when Groq is rate-limited (see "Fallback" below).

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

MODEL = "groq/openai/gpt-oss-120b"


async def complete_structured(messages: list[dict], schema: type[T]) -> T:
    """Call Groq and return a validated instance of `schema`."""
    resp = await acompletion(
        model=MODEL,
        api_key=os.getenv("GROQ_API_KEY"),
        messages=messages,
        response_format=schema,   # LiteLLM converts Pydantic -> strict json_schema
        temperature=0.2,
        num_retries=2,            # retries 429s with backoff
        timeout=60,
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

## Structured Outputs rules (Groq strict mode)

Groq supports strict `json_schema` on `openai/gpt-oss-120b`, with these limits:

- Every field must be **required**. For an optional value, type it `X | None`
  with no default, so the model returns `null` instead of omitting it.
- Every object must have `additionalProperties: false`. Use nested Pydantic
  models for nested objects; never `dict[str, Any]` or free-form objects.
- Structured Outputs **cannot be combined with streaming or tool calls**. Use
  a non-streaming call for field extraction.
- Always validate with `model_validate_json` and handle `ValidationError`:
  re-ask once, then return a friendly error.

## Fallback (only if the openrouter-llm skill is present)

Swap `acompletion` for a LiteLLM `Router` so 429s fall through to OpenRouter's
free model:

```python
from litellm import Router

_router = Router(
    model_list=[
        {"model_name": "primary",
         "litellm_params": {"model": "groq/openai/gpt-oss-120b",
                            "api_key": os.getenv("GROQ_API_KEY")}},
        {"model_name": "fallback",
         "litellm_params": {"model": "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
                            "api_key": os.getenv("OPENROUTER_API_KEY"),
                            "extra_body": {"provider": {"require_parameters": True}}}},
    ],
    fallbacks=[{"primary": ["fallback"]}],
    num_retries=2,
    timeout=60,
)
# then: resp = await _router.acompletion(model="primary", messages=..., response_format=schema)
```

## Errors and limits

- `litellm.RateLimitError` after retries/fallbacks → HTTP 503 with "The
  assistant is busy, please try again in a minute." Never crash the request.
- Rate limits apply per Groq organization, not per key; extra keys don't help.
- If the model string stops working, check https://console.groq.com/docs/models
  and update `MODEL`. Use only models available on the free tier.
- Don't put real client secrets or sensitive personal data in prompts.

## Testing

Unit tests must not hit the network: patch `app.llm.acompletion` (or
`app.llm._router.acompletion` when using the fallback) with
`unittest.mock.AsyncMock` returning an object whose
`choices[0].message.content` is valid JSON for the schema. Keep one optional
integration test marked `@pytest.mark.integration` that runs only when
`GROQ_API_KEY` is set.
