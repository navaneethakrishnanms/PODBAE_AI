"""The ONE outbound-payload filter. Nothing reaches an LLM provider except an `OutboundPayload`, and the only way to make one
is `prepare()` below, so every call passes the same checks:

ALLOWED to leave the machine: public podcast content only:
  show / episode titles and descriptions, transcript excerpts, ad snippets and their context windows, brand names / domains,
  the fixed taxonomies / class lists, and the deterministic explanation skeleton of a card (template ids + slot values).
NEVER: user e-mails or names, analytics uploads, creator settings (blocked brands, exclusivity...), human labels / reviews,
  anything from the Express app (users, advertisers, campaigns, messages). Enforced by
  1. a label allowlist for data blocks (each block says what it is; unknown labels are refused),
  2. a key allowlist + denylist for the small trusted META object,
  3. scrubbing of e-mail addresses, phone numbers and contact sentences inside the text (podcast notes contain them),
  4. a hard size cap.
A refused payload raises PrivacyViolation; the caller falls back to rules (the call is never sent)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RX = re.compile(r"(?<![\w/])\+?\d[\d ().-]{7,}\d(?![\w/])")
HANDLE_RX = re.compile(r"(?<![\w.])@[A-Za-z0-9_]{2,30}\b")          # social handles are contact routes, not needed by any task

ALLOWED_LABEL = re.compile(r"^(?:show_title|show_description|ep_[a-z0-9_]+|tr_[a-z0-9_]+|ev_\d+|ctx_\d+|brand_name|brand_domain|"
                           r"snip_\d+|skeleton|part_\d+)$")
ALLOWED_META_KEYS = {"task", "categories", "guest_share", "n_hosts", "rule_value", "rule_confidence", "styles", "topics_known",
                     "candidate_topics", "classes", "brand_categories", "items", "type_label", "max_topics", "domain", "hint"}
FORBIDDEN_KEY = re.compile(r"e-?mail|user|owner|password|labeler|reviewer|creator|setting|blocked|exclusive|analytic|upload|"
                           r"contact|phone|address|advertiser|campaign|message|member|hash|token|secret", re.I)
MAX_CHARS = 60_000


class PrivacyViolation(ValueError):
    pass


@dataclass(frozen=True)
class OutboundPayload:
    """Opaque, already-filtered prompt material. Providers accept only this type."""
    blocks: tuple[tuple[str, str], ...]
    meta: str
    scrubbed: dict = field(default_factory=dict, compare=False)


def scrub(text: str, counts: dict | None = None) -> str:
    """Remove e-mails, phone numbers, @handles and whole contact sentences ("email me at…", "call…")."""
    from ..sponsors.detect import no_contacts
    counts = counts if counts is not None else {}
    t = text or ""
    for name, rx, rep in (("emails", EMAIL_RX, "[email removed]"), ("phones", PHONE_RX, "[phone removed]"),
                          ("handles", HANDLE_RX, "[handle removed]")):
        t, n = rx.subn(rep, t)
        counts[name] = counts.get(name, 0) + n
    before = t
    t = no_contacts(t)
    if t != before:
        counts["contact_sentences"] = counts.get("contact_sentences", 0) + 1
    return t


def _check_meta(x, path: str = "meta") -> None:
    if isinstance(x, dict):
        for k, v in x.items():
            if FORBIDDEN_KEY.search(str(k)):
                raise PrivacyViolation(f"{path}.{k}: key not allowed to leave the machine")
            _check_meta(v, f"{path}.{k}")
    elif isinstance(x, (list, tuple)):
        for i, v in enumerate(x):
            _check_meta(v, f"{path}[{i}]")
    elif isinstance(x, str) and EMAIL_RX.search(x):
        raise PrivacyViolation(f"{path}: contains an e-mail address")


def prepare(blocks: dict[str, str], meta: dict | None = None) -> OutboundPayload:
    meta = meta or {}
    bad = [k for k in meta if k not in ALLOWED_META_KEYS]
    if bad:
        raise PrivacyViolation(f"meta keys not on the allowlist: {bad}")
    _check_meta(meta)
    counts: dict = {}
    out: list[tuple[str, str]] = []
    total = 0
    for label, text in blocks.items():
        if not ALLOWED_LABEL.match(label or ""):
            raise PrivacyViolation(f"data block label {label!r} is not public podcast content")
        t = scrub(str(text or ""), counts)
        total += len(t)
        out.append((label, t))
    if total > MAX_CHARS:
        raise PrivacyViolation(f"payload too large ({total} chars > {MAX_CHARS})")
    meta_s = json.dumps(meta, sort_keys=True, ensure_ascii=False)
    if EMAIL_RX.search(meta_s):
        raise PrivacyViolation("meta contains an e-mail address")
    return OutboundPayload(tuple(out), meta_s, counts)
