"""LLM providers for extraction. Mock (default, zero keys, deterministic), OpenAI and Anthropic via plain HTTPS.
The mock "reads" the delimited prompt with the heuristic analyser, so it can never be hijacked by instructions in
the data (it does not follow instructions at all)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import get_settings
from .rules import find_evidence, heuristic_analysis


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int


class Provider(Protocol):
    name: str
    model_version: str
    price_in_per_1k: float
    price_out_per_1k: float

    def complete_json(self, system: str, user: str) -> LLMResponse: ...


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MockProvider:
    name = "mock"
    model_version = "mock-heuristic-v1"
    price_in_per_1k = 0.0
    price_out_per_1k = 0.0

    def complete_json(self, system: str, user: str) -> LLMResponse:
        blocks = dict(re.findall(r'<untrusted_data label="([a-z0-9_]+)">\n(.*?)\n</untrusted_data>', user, re.S))
        meta = json.loads(re.search(r"<<<META\n(.*?)\nMETA>>>", user, re.S).group(1))  # trusted rule facts
        ep_blocks = {k: v for k, v in blocks.items() if k.startswith("ep_")}
        out = heuristic_analysis(
            title=blocks.get("show_title", ""), description=blocks.get("show_description", ""),
            categories=meta.get("categories", []), episode_titles=[v.split("\n", 1)[0] for v in ep_blocks.values()],
            episode_texts=[v for k, v in blocks.items() if k.startswith(("ep_", "tr_"))],
            guest_share=meta.get("guest_share", 0.0), n_hosts=meta.get("n_hosts", 1))
        out["evidence"] = find_evidence(blocks, out)
        text = json.dumps(out)
        return LLMResponse(text, est_tokens(system + user), est_tokens(text))


class OpenAIProvider:
    name = "openai"
    price_in_per_1k, price_out_per_1k = 0.00015, 0.0006   # gpt-4o-mini list price (estimate; verify before relying on it)

    def __init__(self, key: str, model: str):
        self.key, self.model_version = key, model

    def complete_json(self, system: str, user: str) -> LLMResponse:
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=60,
                       headers={"Authorization": f"Bearer {self.key}"},
                       json={"model": self.model_version, "response_format": {"type": "json_object"}, "temperature": 0,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        return LLMResponse(d["choices"][0]["message"]["content"], u.get("prompt_tokens", est_tokens(user)),
                           u.get("completion_tokens", 300))


class AnthropicProvider:
    name = "anthropic"
    price_in_per_1k, price_out_per_1k = 0.001, 0.005      # estimate; verify before relying on it

    def __init__(self, key: str, model: str):
        self.key, self.model_version = key, model

    def complete_json(self, system: str, user: str) -> LLMResponse:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60,
                       headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                       json={"model": self.model_version, "max_tokens": 1500, "temperature": 0, "system": system,
                             "messages": [{"role": "user", "content": user}]})
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        return LLMResponse("".join(b.get("text", "") for b in d.get("content", [])), u.get("input_tokens", est_tokens(user)),
                           u.get("output_tokens", 300))


def get_provider() -> Provider:
    cfg = get_settings()
    p = cfg.llm_provider.lower()
    if p == "openai" and cfg.openai_key:
        return OpenAIProvider(cfg.openai_key, cfg.openai_model)
    if p == "anthropic" and cfg.anthropic_key:
        return AnthropicProvider(cfg.anthropic_key, cfg.anthropic_model)
    return MockProvider()


def provider_status() -> dict:
    cfg = get_settings()
    p = get_provider()
    return {"configured": cfg.llm_provider, "active": p.name, "model": p.model_version,
            "keys": {"openai": bool(cfg.openai_key), "anthropic": bool(cfg.anthropic_key)}}
