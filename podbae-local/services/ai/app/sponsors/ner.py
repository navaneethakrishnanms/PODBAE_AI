"""Brand names near ad cues: local zero-shot NER (GLiNER) with a rules-only fallback. Which one ran is recorded.

Model choice - urchade/gliner_small-v2.1 (gliner 0.2.16):
  * zero-shot: we ask for 'brand' / 'company' / 'product' spans without training data we do not have;
  * Apache-2.0 licence (the multilingual GLiNER is CC BY-NC, unusable commercially);
  * ~166M params, runs on the local GPU in ~2 GB; we only run it on short windows after ad cues (a few thousand), so a
    full corpus scan costs seconds of GPU time;
  * gliner 0.2.16 works with the pinned transformers 4.46 (newer gliner needs transformers >= 4.51, which would move the
    whole torch_gpu stack). Its DeBERTa tokenizer conversion needs protobuf's pure-python mode, set below only here.
If the model cannot load (offline, no GPU memory), extraction falls back to rules and events record method='rules'."""
from __future__ import annotations

import os
import re
import threading

GLINER_MODEL = os.environ.get("SPONSOR_NER_MODEL", "urchade/gliner_small-v2.1")
LABELS = ["brand", "company", "product"]
GENERIC = re.compile(r"^(our|the|my|your|this|today'?s?|these|those|a|an|all|you|listeners?|patrons?|supporters?|sponsors?|"
                     r"members?|friends?|fans?|community|show|podcast|episode|team|network|support|people|everyone|"
                     # imperative words that start ad copy ("Use code SHOW", "Get 20% off") are never brand names
                     r"use|get|visit|go|head|try|download|save|shop|enter|apply|click|sign|join|check|order|grab|text|call|"
                     r"start|claim|receive|learn|find|book|buy|subscribe|follow|listen|watch|code|promo|discount|offer|free)\b", re.I)
_lock = threading.Lock()
_model = None
_status: dict = {"loaded": False, "method": "rules", "error": None}


def status() -> dict:
    return dict(_status)


def _load():
    global _model
    if _model is not None or _status.get("error") or os.environ.get("SPONSOR_NER", "gliner") == "rules":
        return _model
    with _lock:
        if _model is not None or _status.get("error"):
            return _model
        try:
            os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
            import gliner
            import torch
            from gliner import GLiNER
            m = GLiNER.from_pretrained(GLINER_MODEL)
            m = m.to("cuda" if torch.cuda.is_available() else "cpu")
            m.eval()
            _model = m
            _status.update(loaded=True, method=f"gliner:{GLINER_MODEL}@{gliner.__version__}",
                           device=str(next(m.parameters()).device))
        except Exception as exc:  # noqa: BLE001 - offline / no GPU memory / dependency problem -> rules
            _status.update(error=f"{type(exc).__name__}: {exc}"[:300], method="rules")
    return _model


def method() -> str:
    _load()
    return _status["method"]


# ── rules fallback: the capitalised phrase right after the cue ("sponsored by Better Help, ...") ──
RULE_NAME = re.compile(r"((?:[A-Z][\w&'.+-]*|[A-Z0-9]{2,})(?:\s+(?:[A-Z][\w&'.+-]*|of|and|&|[A-Z0-9]{2,})){0,3})")


def rule_names(window: str) -> list[str]:
    window = re.split(r"[.!?,;:](?:\s|$)", window.strip())[0]     # a name never spans a sentence boundary
    m = RULE_NAME.search(window[:80])
    if not m or m.start() > 12:
        return []
    name = re.sub(r"\s+(of|and|&)$", "", m.group(1)).strip(" .,'")
    return [] if not name or GENERIC.match(name) or len(name) < 2 else [name]


def names(windows: list[str], threshold: float = 0.45) -> list[list[str]]:
    """Brand names in each window (GLiNER, batched; else rules). Generic phrases ('our listeners') are dropped."""
    m = _load()
    out: list[list[str]] = []
    if m is None:
        return [rule_names(w) for w in windows]
    with _lock:
        for i in range(0, len(windows), 16):
            batch = [w[:300] for w in windows[i:i + 16]]
            res = m.batch_predict_entities(batch, LABELS, threshold=threshold) if hasattr(m, "batch_predict_entities") else \
                [m.predict_entities(b, LABELS, threshold=threshold) for b in batch]
            for ents in res:
                seen, keep = set(), []
                for e in sorted(ents, key=lambda e: e["start"]):
                    t = e["text"].strip(" .,'\"")
                    if len(t) >= 2 and not GENERIC.match(t) and t.lower() not in seen:
                        seen.add(t.lower())
                        keep.append(t)
                out.append(keep)
    # the model occasionally misses an obvious capitalised name right after the cue: fall back to the rule per window
    return [o or rule_names(w) for o, w in zip(out, windows)]


STOP = {"I", "We", "You", "He", "She", "They", "It", "The", "A", "An", "This", "That", "These", "Those", "Our", "My", "Your", "Their", "In",
        "On", "At", "For", "And", "But", "Or", "So", "If", "When", "What", "Why", "How", "Who", "Where", "Episode", "Today", "Follow", "Join",
        "Listen", "Subscribe", "Check", "Visit", "Get", "Go", "Plus", "Also", "Then", "Now", "Here", "There", "Thanks", "Thank", "Please",
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December", "Part", "Season", "Chapter", "Mr", "Mrs", "Ms", "Dr"}
ORG_RULE = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]+[A-Z]?[a-z]*(?:'s)?|[A-Z]{2,}[a-z]*)\b")


def rule_organic(window: str) -> list[str]:
    """Capitalised words that are not sentence-initial and not stopwords ("inspired by Microsoft's research" -> Microsoft)."""
    out = []
    words = window.split()
    for j, w in enumerate(words):
        core = re.sub(r"[^\w'&.+-]", "", w)
        core = re.sub(r"'s$", "", core)
        if j == 0 or not core or not core[0].isupper() or core in STOP or core.rstrip(".") in STOP:
            continue
        if words[j - 1].endswith((".", "!", "?", ":")):
            continue
        if core not in out:
            out.append(core.rstrip("."))
    return out


def organic_names(windows: list[str]) -> list[list[str]]:
    """Names in cue-less segments: GLiNER when loaded, else the capitalised-word rule."""
    return names(windows) if _load() is not None else [rule_organic(w) for w in windows]
