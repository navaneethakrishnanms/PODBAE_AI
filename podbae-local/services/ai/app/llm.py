"""Provider-pluggable LLM interface. LLM_PROVIDER=openai|anthropic|mock."""

from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

SYSTEM_PROMPT = (
    "You are Hey Bae, a podcast matchmaker assistant. Answer ONLY from the context JSON provided "
    "(the member's podcast, episodes and current matches). Never invent sponsors, contacts, venues "
    "or podcasts. If the context lacks the answer, say so."
)


class LLM(Protocol):
    name: str

    def chat(self, message: str, context: dict[str, Any], history: list[dict[str, str]]) -> str: ...


class MockLLM:
    name = "mock"

    def chat(self, message: str, context: dict[str, Any], history: list[dict[str, str]]) -> str:
        pod = context.get("podcast") or {}
        matches = context.get("matches") or []
        if not pod:
            return "Hey! I don't see a podcast on your profile yet — finish your intake and I can help."
        top = matches[:3]
        if not top:
            return f"Hi! I'm looking at {pod.get('name')}, but there are no matches yet. Try 'Run matching'."
        lines = [
            f"- {m.get('name')} ({m.get('targetType')}, {m.get('totalScore')}%): "
            f"{(m.get('explanation') or {}).get('summary', '')}"
            for m in top
        ]
        return f"[mock] Here are your top matches for {pod.get('name')}:\n" + "\n".join(lines)


class OpenAILLM:
    name = "openai"

    def chat(self, message: str, context: dict[str, Any], history: list[dict[str, str]]) -> str:
        msgs = [{"role": "system", "content": f"{SYSTEM_PROMPT}\nContext: {context}"}]
        msgs += history[-10:] + [{"role": "user", "content": message}]
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "messages": msgs},
            timeout=60,
        )
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"])


class AnthropicLLM:
    name = "anthropic"

    def chat(self, message: str, context: dict[str, Any], history: list[dict[str, str]]) -> str:
        msgs = history[-10:] + [{"role": "user", "content": message}]
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                "max_tokens": 800,
                "system": f"{SYSTEM_PROMPT}\nContext: {context}",
                "messages": msgs,
            },
            timeout=60,
        )
        r.raise_for_status()
        return str(r.json()["content"][0]["text"])


def get_llm() -> LLM:
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider == "openai" and os.getenv("OPENAI_API_KEY"):
        return OpenAILLM()
    if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    return MockLLM()  # no key / unknown provider -> mock
