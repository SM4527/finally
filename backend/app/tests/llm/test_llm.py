from types import SimpleNamespace
from unittest.mock import AsyncMock

import litellm
import pytest

from app import llm
from app.llm import MALFORMED_REPLY, ChatReply, LLMUnavailable, get_chat_reply

VALID = '{"message": "Done", "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 2.5}],' \
        ' "watchlist_changes": [{"ticker": "PYPL", "action": "add"}]}'
USER = [{"role": "user", "content": "hello"}]


def response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def router(monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    fake = SimpleNamespace(model_list=[{"model_name": "primary"}], acompletion=AsyncMock())
    monkeypatch.setattr(llm, "_router", lambda: fake)
    return fake


async def test_parses_structured_output(router):
    router.acompletion.return_value = response(VALID)
    reply = await get_chat_reply(USER)
    assert reply.trades[0].quantity == 2.5
    assert reply.watchlist_changes[0].action == "add"
    assert router.acompletion.call_args.kwargs["response_format"] is ChatReply


async def test_parses_empty_actions(router):
    router.acompletion.return_value = response('{"message": "Hi", "trades": [], "watchlist_changes": []}')
    reply = await get_chat_reply(USER)
    assert reply == ChatReply(message="Hi", trades=[], watchlist_changes=[])


async def test_reasks_once_on_malformed_output(router):
    router.acompletion.side_effect = [response("not json"), response(VALID)]
    reply = await get_chat_reply(USER)
    assert reply.message == "Done"
    assert router.acompletion.await_count == 2


@pytest.mark.parametrize("bad", ["{", '{"message": "x"}', '{"message": "x", "trades": [{"ticker": "A",'
                                 ' "side": "hold", "quantity": 1}], "watchlist_changes": []}'])
async def test_friendly_reply_after_two_malformed(router, bad):
    router.acompletion.return_value = response(bad)
    reply = await get_chat_reply(USER)
    assert reply.message == MALFORMED_REPLY
    assert reply.trades == [] and reply.watchlist_changes == []
    assert router.acompletion.await_count == 2


async def test_rate_limit_raises_unavailable(router):
    router.acompletion.side_effect = litellm.RateLimitError("slow down", "groq", "gpt-oss-120b")
    with pytest.raises(LLMUnavailable):
        await get_chat_reply(USER)


async def test_no_keys_raises_unavailable(monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    llm._router.cache_clear()
    with pytest.raises(LLMUnavailable):
        await get_chat_reply(USER)


def test_router_has_fallback_with_both_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    llm._router.cache_clear()
    router = llm._router()
    llm._router.cache_clear()
    models = [d["litellm_params"]["model"] for d in router.model_list]
    assert models == [llm.PRIMARY_MODEL, llm.FALLBACK_MODEL]
    assert all(m.endswith(":free") for m in models if m.startswith("openrouter/"))
    assert router.fallbacks == [{"primary": ["fallback"]}]


@pytest.mark.parametrize("text, side", [("Please BUY something", "buy"), ("sell it", "sell")])
async def test_mock_mode_trades(monkeypatch, text, side):
    monkeypatch.setenv("LLM_MOCK", "true")
    reply = await get_chat_reply([{"role": "user", "content": text}])
    assert [(t.ticker, t.side, t.quantity) for t in reply.trades] == [("AAPL", side, 1)]


async def test_mock_mode_other(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    reply = await get_chat_reply(USER)
    assert reply.trades == [] and reply.watchlist_changes == [] and reply.message
