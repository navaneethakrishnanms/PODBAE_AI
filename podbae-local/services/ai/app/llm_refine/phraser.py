"""Phase 4 LLM phrasing of partner + sponsor card explanations (the Phase 2 Phraser seam).

Input = ONLY the deterministic skeleton: the template parts already produced by explain.build (template id + the rendered
sentence, which contains only slot values: target title, factor inputs, evidence titles, Fit, confidence level).
Output must pass `check()`:
  * every number in the phrased text is a number from a slot,
  * every capitalised word / name in it appears in the skeleton text (no new entities),
  * no URLs / e-mails / @handles, no longer than 1.6x the template text, and the template parts themselves still pass
    explain.faithfulness().
Otherwise the template text is shown. The card's breakdown says which source was used ('template' or 'ai_phrased').

Lazy and budgeted: phrasing is requested only for cards the app actually SHOWED (impression events) -> job 'llm_phrase',
at most LLM_PHRASE_DAILY_CALLS provider calls per day. Listing endpoints only attach already-cached phrasings
(cache_only: no provider call on the request path). Cache key = hash of the skeleton (+ prompt version + model)."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..intel.config import get_settings
from ..opportunities import explain as ex
from . import client, llm_active
from .models import LlmCall

PV = "phrase-v1"
TASK = ("Rewrite the numbered sentences (part_ blocks) about a recommended podcast partnership into ONE short, friendly paragraph "
        "for the creator (2-3 sentences). Keep every fact exactly as given; do not add any fact, name, number, claim or "
        "promise that is not in the parts; do not add links. Write in the second person ('you').")
ALLOWED_CAPS = {"you", "your", "you're", "you've", "both", "they", "their", "they're", "it", "its", "this", "that", "these", "those",
                "a", "an", "the", "and", "but", "so", "also", "plus", "with", "as", "at", "on", "in", "for", "by", "from", "together",
                "fit", "high", "medium", "low", "evidence", "confidence", "there", "here", "we", "our", "if", "what", "why", "how",
                "recently", "lately", "right", "now", "today", "overall", "since", "while", "when", "because", "i"}
URL_RX = re.compile(r"https?://|www\.|@|\b[\w-]+\.(?:com|net|org|io|co|fm|ly)\b", re.I)
WORD_RX = re.compile(r"[A-Za-z][A-Za-z'’&.-]*")


class PhraseOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=700)


def enabled() -> bool:
    return llm_active() and get_settings().llm_phrasing_enabled


def _blocks(expl: dict) -> dict[str, str]:
    return {f"part_{i}": p["text"] for i, p in enumerate(expl.get("parts") or [])}


def check(text: str, expl: dict, record: dict | None = None) -> list[str]:
    """Problems with a phrased text ([] = faithful)."""
    parts = expl.get("parts") or []
    if not parts:
        return ["no skeleton"]
    skel = " ".join(p["text"] for p in parts)
    probs: list[str] = []
    if not text.strip():
        probs.append("empty")
    if len(text) > max(160, int(1.6 * len(skel))):
        probs.append("too long")
    if URL_RX.search(text):
        probs.append("link / handle / e-mail in text")
    slot_nums: set[float] = set()
    for p in parts:
        for v in p.get("slots", {}).values():
            for item in (v if isinstance(v, list) else [v]):
                for n in ex.NUM_RX.findall(str(item)):
                    slot_nums.add(float(n))
    for n in ex.NUM_RX.findall(text):
        if float(n) not in slot_nums:
            probs.append(f"number {n} not from a slot")
    skel_words = {w.lower().strip(".'’") for w in WORD_RX.findall(skel)}
    for w in WORD_RX.findall(text):
        core = w.strip(".'’").lower()
        if w[0].isupper() and core not in ALLOWED_CAPS and core not in skel_words:
            probs.append(f"new entity '{w}'")
    if record is not None:
        probs += [f"skeleton: {p}" for p in ex.faithfulness(expl, record)]
    return probs


def calls_today(s: Session) -> int:
    t = datetime.utcnow()
    return int(s.scalar(select(func.count()).select_from(LlmCall).where(
        LlmCall.task == "phrase", LlmCall.cache_hit.is_(False), LlmCall.ts >= datetime(t.year, t.month, t.day))) or 0)


def phrase(s: Session, expl: dict, *, entity: tuple[str, str] | None = None, cache_only: bool = False,
           type_label: str | None = None) -> tuple[str | None, str]:
    """(phrased_text | None, status). None means: show the template."""
    if not enabled() or not expl.get("parts"):
        return None, "disabled"
    if not cache_only and calls_today(s) >= get_settings().llm_phrase_daily_calls:
        return None, "daily_budget"
    out = client.run(s, "phrase", PV, TASK, _blocks(expl), PhraseOut, meta={"type_label": type_label or ""}, entity=entity,
                     cache_only=cache_only)
    if not out.ok:
        return None, out.status
    probs = check(out.value.text, expl)
    if not cache_only and out.status == "ok":          # measured once per new phrasing (eval: faithfulness failure rate)
        from ..intel.trust.audit import audit
        audit(s, "llm", "phrase_unfaithful" if probs else "phrase_faithful", entity and entity[0], entity and entity[1],
              {"problems": probs[:5]} if probs else {})
    if probs:
        return None, "unfaithful: " + "; ".join(probs[:3])
    return out.value.text.strip(), out.status


def attach(s: Session, items: list[dict]) -> list[dict]:
    """Listing path: attach cached phrasings only (no provider calls), always keep the template text alongside."""
    on = enabled()
    for it in items:
        e = it.get("explanation") or {}
        e["template_text"] = e.get("text")
        e["text_source"] = "template"
        if on and e.get("parts"):
            txt, _st = phrase(s, e, cache_only=True, type_label=it.get("type_label"))
            if txt:
                e["text"], e["text_source"] = txt, "ai_phrased"
        it["explanation"] = e
    return items
