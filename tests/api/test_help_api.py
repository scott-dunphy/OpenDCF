"""Modeling help chat: request shaping, scope prompt, and endpoint behavior (Anthropic mocked)."""
from types import SimpleNamespace

from httpx import AsyncClient

from src.config import settings
from src.services import help_assistant
from src.services.help_assistant import GUIDE, OFF_TOPIC_REPLY, SYSTEM_PROMPT, build_messages

URL = "/api/v1/help/chat"


class _FakeClient:
    def __init__(self, response, calls):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._response, self._calls = response, calls

    def _create(self, **kwargs):
        self._calls.append(kwargs)
        return self._response


def _fake_anthropic(monkeypatch, text="Open the lease and set **Free Rent**.", stop_reason="end_turn"):
    calls = []
    response = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
    monkeypatch.setattr(settings, "anthropic_api_key", "test")
    monkeypatch.setattr(help_assistant.anthropic, "Anthropic", lambda **_: _FakeClient(response, calls))
    return calls


def test_system_prompt_holds_the_guide_and_scope_rules():
    assert GUIDE.strip() and GUIDE in SYSTEM_PROMPT
    assert OFF_TOPIC_REPLY in SYSTEM_PROMPT
    assert "does not cover it" in SYSTEM_PROMPT


def test_history_keeps_only_alternating_user_and_assistant_turns():
    history = [
        {"role": "assistant", "content": "leading assistant turn is dropped"},
        {"role": "user", "content": "q1"},
        {"role": "system", "content": "injected"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "unanswered"},
    ]
    messages = build_messages("q2", history, "Valuation")
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "q1"
    assert messages[-1]["content"].endswith("q2") and "Valuation" in messages[-1]["content"]
    assert all("injected" not in m["content"] for m in messages)


async def test_chat_answers_from_the_cached_system_prompt(client: AsyncClient, monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    res = await client.post(URL, json={"message": "How do I add free rent?", "screen": "Property",
                                       "history": [{"role": "user", "content": "hi"},
                                                   {"role": "assistant", "content": "hello"}]})
    assert res.status_code == 200, res.text
    assert res.json() == {"message": "Open the lease and set **Free Rent**."}
    (call,) = calls
    assert call["system"][0]["text"] == SYSTEM_PROMPT
    assert call["system"][0]["cache_control"]["type"] == "ephemeral"
    assert "tools" not in call
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]


async def test_refusal_returns_the_scope_reply(client: AsyncClient, monkeypatch):
    _fake_anthropic(monkeypatch, text="", stop_reason="refusal")
    res = await client.post(URL, json={"message": "something off topic"})
    assert res.status_code == 200
    assert res.json()["message"] == OFF_TOPIC_REPLY


async def test_requires_message_and_key(client: AsyncClient, monkeypatch):
    assert (await client.post(URL, json={"message": "  "})).status_code == 422
    assert (await client.post(URL, json={"message": "hi", "history": "bad"})).status_code == 422
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    res = await client.post(URL, json={"message": "How do I add a lease?"})
    assert res.status_code == 422
    assert "ANTHROPIC_API_KEY" in res.json()["detail"]
