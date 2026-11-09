"""LLM calls via LiteLLM: Groq primary, OpenRouter free fallback, structured output."""

import os
from functools import cache
from typing import Literal

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402
from litellm import Router  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

PRIMARY_MODEL = "groq/openai/gpt-oss-120b"
FALLBACK_MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
MALFORMED_REPLY = "Sorry, I could not process that request. Please try rephrasing it."
MOCK_REPLY = "I am FinAlly running in mock mode. Ask me to buy or sell."

UNAVAILABLE_ERRORS = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.Timeout,
    litellm.AuthenticationError,
)


class Trade(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistChange(BaseModel):
    ticker: str
    action: Literal["add", "remove"]


class ChatReply(BaseModel):
    message: str
    trades: list[Trade]
    watchlist_changes: list[WatchlistChange]


class LLMUnavailable(Exception):
    """No provider could answer (rate limited, down or not configured) -> HTTP 503."""


@cache
def _router() -> Router:
    """Router over the providers whose keys are set; Groq falls back to OpenRouter."""
    deployments = []
    if os.getenv("GROQ_API_KEY"):
        deployments.append({"model_name": "primary", "litellm_params": {
            "model": PRIMARY_MODEL, "api_key": os.getenv("GROQ_API_KEY")}})
    if os.getenv("OPENROUTER_API_KEY"):
        deployments.append({"model_name": "fallback", "litellm_params": {
            "model": FALLBACK_MODEL, "api_key": os.getenv("OPENROUTER_API_KEY"),
            "extra_body": {"provider": {"require_parameters": True}}}})
    if not deployments:
        raise LLMUnavailable("No LLM API key configured")
    fallbacks = [{"primary": ["fallback"]}] if len(deployments) == 2 else []
    return Router(model_list=deployments, fallbacks=fallbacks, num_retries=2, timeout=60)


async def _complete(messages: list[dict]) -> str:
    """One structured completion; returns the raw JSON content."""
    router = _router()
    model = router.model_list[0]["model_name"]
    try:
        resp = await router.acompletion(
            model=model, messages=messages, response_format=ChatReply, temperature=0.2
        )
    except UNAVAILABLE_ERRORS as exc:
        raise LLMUnavailable(str(exc)) from exc
    return resp.choices[0].message.content


def mock_reply(messages: list[dict]) -> ChatReply:
    """Deterministic reply for LLM_MOCK=true, keyed on the last user message."""
    text = messages[-1]["content"].lower()
    if "buy" in text:
        return ChatReply(message="Buying 1 AAPL.", watchlist_changes=[],
                         trades=[Trade(ticker="AAPL", side="buy", quantity=1)])
    if "sell" in text:
        return ChatReply(message="Selling 1 AAPL.", watchlist_changes=[],
                         trades=[Trade(ticker="AAPL", side="sell", quantity=1)])
    return ChatReply(message=MOCK_REPLY, trades=[], watchlist_changes=[])


async def get_chat_reply(messages: list[dict]) -> ChatReply:
    """Ask the LLM for a ChatReply. Re-asks once on malformed output. Raises LLMUnavailable."""
    if os.getenv("LLM_MOCK", "").lower() == "true":
        return mock_reply(messages)
    for _ in range(2):
        try:
            return ChatReply.model_validate_json(await _complete(messages))
        except ValidationError:
            continue
    return ChatReply(message=MALFORMED_REPLY, trades=[], watchlist_changes=[])
