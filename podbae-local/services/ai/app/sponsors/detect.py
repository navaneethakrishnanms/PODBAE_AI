"""Sponsorship detection: rules (+ local NER for names near cues). No LLM, no fetching.

Each text (episode show notes or a transcript) is split into segments (lines / sentences). Every finding is assigned
exactly ONE evidence class, with the rule that fired:

  declared_sponsorship  explicit sponsor phrase or ad-section header + an identifiable brand (domain or name)
  likely_sponsorship    promo code / % off / free-trial / "go to brand.com/<show>" vanity URL + brand, no explicit phrase
  affiliate             affiliate link patterns (amzn.to, ?tag=, ?ref=, /aff/, "affiliate link", "I earn a commission")
  podcast_promo         promotion of ANOTHER podcast (podcast-app link + "check out / listen to ...")  -> cross-promo evidence
  self_promotion        the show's own domain, merch, Patreon / tips, newsletter, courses, tickets  (excluded)
  network_disclosure    ad-choices / hosting-platform ad boilerplate: dynamic ads exist, but no brand is visible
  organic_mention       a brand / site named with no commercial cue  (excluded)
  uncertain             a sponsor cue whose brand cannot be identified, or other ambiguity -> human review queue

Ad sections are NOT treated as boilerplate: a sponsor block repeated across episodes is a running campaign and every
episode keeps its event."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import domains as dm

DETECTOR_VERSION = "sponsor-rules-v1"

NETWORK = [("adchoices", re.compile(r"adchoices|ad choices|podcastchoices\.com", re.I)),
           ("hosting_privacy_ads", re.compile(r"(?:acast\.com/privacy|art19\.com/privacy|omnystudio\.com/listener|privacy (?:policy|notice)"
                                              r".{0,80}advertis|personal data for advertising)", re.I)),
           ("ad_sales_contact", re.compile(r"advertising (?:inquiries|enquiries)|sponsorship (?:inquiries|enquiries|opportunities)|"
                                           r"interested in (?:advertising|sponsoring)|(?:to )?advertise (?:on|with) (?:this|the|our|my) (?:show|podcast)|"
                                           r"redcircle\.com/brands|advertisecast|podcorn", re.I)),
           ("hosted_on_network", re.compile(r"hosted (?:on|by) acast|see acast\.com|megaphone\.fm/adchoices", re.I))]
EXPLICIT = [("sponsored_by", re.compile(r"\bsponsored by\b", re.I)),
            ("brought_to_you_by", re.compile(r"\bbrought to you by\b", re.I)),
            ("thanks_to_sponsor", re.compile(r"\bthank(?:s| you) (?:to )?(?:our|today'?s|this week'?s|this episode'?s) (?:sponsors?|partners?)\b", re.I)),
            ("todays_sponsor", re.compile(r"\b(?:today'?s|this (?:week'?s|episode'?s)) (?:sponsors?|partners?)\b", re.I)),
            ("supported_by", re.compile(r"\b(?:episode|show|podcast) is (?:also )?(?:supported|presented|powered|made possible) by\b", re.I)),
            ("in_partnership_with", re.compile(r"\bin (?:paid )?partnership with\b", re.I)),
            ("paid_promotion", re.compile(r"#ad\b|\bpaid (?:promotion|partnership)\b", re.I))]
AD_HEADER = re.compile(r"(?im)^\s*(?:(?:our |today'?s |this episode'?s |episode |show )?sponsors?|deals?|offers?|promo(?:tion)?s?|"
                       r"(?:our )?partners?|thanks to our sponsors)\s*[:\-–—]")
BLOCK_END = re.compile(r"(?im)^\s*(?:follow|connect|links?|credits?|hosted|produced|music|support (?:the|this|us)|find us|socials?|"
                       r"subscribe|about|contact|listen)\b")
PROMO_CODE = re.compile(r"\b(?:use|with|enter|apply|promo|discount|coupon|offer)\s+(?:the\s+)?(?:promo |discount |coupon |offer )?code\s*:?\s*"
                        r"[\"“'(]?([A-Za-z0-9][A-Za-z0-9_-]{2,19})", re.I)
PROMO_OTHER = [("percent_off", re.compile(r"\b\d{1,2}\s?%\s?off\b|\b\d{1,2} percent off\b", re.I)),
               ("free_trial", re.compile(r"\bfirst (?:month|order|box|week) (?:free|for free)\b|\bfree (?:trial|month|shipping|gift)\b|"
                                         r"\bsave \$\d+|\$\d+ off\b", re.I))]
GO_TO = re.compile(r"\b(?:go|head|visit|check out)\s+(?:to|over to)?\s*$", re.I)
AFFILIATE_TEXT = re.compile(r"affiliate link|affiliate links|i (?:may )?earn (?:a )?(?:small )?commission|we (?:may )?earn (?:a )?commission|"
                            r"as an amazon associate", re.I)
SELF_CUE = re.compile(r"\b(?:merch|merchandise|patreon|patrons?|newsletter|my course|our course|my book|our book|our (?:store|shop)|"
                      r"support (?:the|this|our) (?:show|podcast)|buy (?:me|us) a coffee|join (?:the|our) (?:community|club|discord)|"
                      r"membership|tickets?|live show|tour dates|my website|our website|subscribe to (?:my|our))\b", re.I)
PODCAST_LINK = re.compile(r"podcasts\.apple\.com/.+/podcast/|open\.spotify\.com/show/|pod\.link/|podcasts\.google\.com/feed/|"
                          r"overcast\.fm/itunes|pca\.st/|castbox\.fm/channel", re.I)
PODCAST_PROMO_CUE = re.compile(r"\b(?:check out|listen to|go listen|new podcast|another podcast|sister (?:show|podcast)|friends? (?:at|over at)|"
                               r"cross[- ]?promo|feed swap|their (?:show|podcast)|wherever you (?:get|listen)|subscribe to)\b", re.I)
SEG_SPLIT = re.compile(r"\n+|(?<=[.!?])\s+(?=[A-Z0-9\"“])|\s+[|•·]\s+")


@dataclass
class Detection:
    cls: str
    rule: str
    snippet: str
    url: str | None = None
    domain: str | None = None
    brand_name: str | None = None
    promo_code: str | None = None
    aliases: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def identity(self) -> str:
        if self.cls == "network_disclosure":
            return "network:" + self.rule                 # one ad-choices disclosure per rule per text
        return self.domain or (self.brand_name or "").lower() or self.rule


@dataclass
class ShowContext:
    own_domains: set[str] = field(default_factory=set)
    own_names: set[str] = field(default_factory=set)       # normalised show title / author / hosts


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _snip(seg: str, start: int = 0) -> str:
    seg = " ".join(seg.split())
    if len(seg) <= 300:
        return seg
    a = max(0, min(start, len(seg)) - 120)
    return seg[a:a + 300]


def segments(text: str) -> list[tuple[str, bool]]:
    """[(segment, in_ad_block)] - ad blocks start at a 'Sponsors:' style header and end at a blank line / section header."""
    out: list[tuple[str, bool]] = []
    for block in re.split(r"\n\s*\n", text or ""):
        in_block = False
        for line in block.split("\n"):
            if AD_HEADER.match(line):
                in_block = True
            elif in_block and BLOCK_END.match(line):
                in_block = False
            for seg in SEG_SPLIT.split(line):
                if seg.strip():
                    out.append((seg.strip(), in_block or bool(AD_HEADER.match(seg))))
    return out


def _explicit(s: str) -> tuple[str, re.Match] | None:
    for name, rx in EXPLICIT:
        m = rx.search(s)
        if m:
            return name, m
    return None


def _promo(s: str) -> tuple[str, str | None] | None:
    m = PROMO_CODE.search(s)
    if m:
        return "promo_code", m.group(1)
    for name, rx in PROMO_OTHER:
        if rx.search(s):
            return name, None
    return None


def _is_own_name(name: str, ctx: ShowContext) -> bool:
    c = compact(name)
    return bool(c) and any(c == o or (len(c) >= 5 and (o.startswith(c) or c.startswith(o))) for o in ctx.own_names if o)


def _aliases(seg: str, domain: str) -> list[str]:
    lab = compact(dm.label(domain))
    out = []
    for m in re.finditer(r"\b([A-Z][\w&'.+-]*(?:\s+[A-Z][\w&'.+-]*){0,2})", seg):
        if compact(m.group(1)) == lab and len(lab) >= 3:
            out.append(m.group(1).strip(" .,'"))
    return sorted(set(out))


def classify_url(raw: str, seg: str, prev: str, in_block: bool, ctx: ShowContext) -> Detection | None:
    url = dm.clean_url(raw)
    if not url:
        return None
    reg = dm.registrable(url)
    if not reg:
        return None
    ctxt = f"{prev} {seg}"
    if reg in ctx.own_domains:
        return Detection("self_promotion", "own_domain", _snip(seg), url, reg)
    aff = dm.is_affiliate(url)
    if aff or AFFILIATE_TEXT.search(seg):
        return Detection("affiliate", aff or "affiliate_text", _snip(seg), url, reg)
    if dm.is_denylisted(url):
        if PODCAST_LINK.search(url) and PODCAST_PROMO_CUE.search(ctxt) and not SELF_CUE.search(seg):
            return Detection("podcast_promo", "podcast_app_link+promo_cue", _snip(seg), url, reg, extra={"promoted_url": url})
        if reg in {"patreon.com", "buymeacoffee.com", "ko-fi.com", "kofi.com", "paypal.com", "paypal.me", "venmo.com", "cash.app",
                   "supercast.com", "memberful.com", "glow.fm", "supporter.fm", "gofundme.com"}:
            return Detection("self_promotion", "support_page", _snip(seg), url, reg)
        return None                                           # platform link: not a brand, not evidence of anything
    exp = _explicit(ctxt)
    if (exp or in_block) and not SELF_CUE.search(seg):
        return Detection("declared_sponsorship", f"explicit:{exp[0]}" if exp else "ad_block_header", _snip(seg), url, reg,
                         aliases=_aliases(seg, reg))
    if SELF_CUE.search(seg):
        return Detection("self_promotion", "self_cue", _snip(seg), url, reg)
    pr = _promo(ctxt)
    van = dm.vanity_path(url)
    before = seg[: max(0, seg.find(raw))] if raw in seg else ""
    if pr or (van and GO_TO.search(before)):
        rule = pr[0] if pr else "go_to_vanity_url"
        return Detection("likely_sponsorship", rule, _snip(seg), url, reg, promo_code=pr[1] if pr else None, aliases=_aliases(seg, reg))
    return Detection("organic_mention", "url_no_commercial_cue", _snip(seg), url, reg)


def detect(text: str, ctx: ShowContext, *, ner_fn=None, organic_fn=None, organic_names: bool = False) -> list[Detection]:
    """All detections in one text. ner_fn(list[str]) -> list[list[str]] finds brand names in cue windows (GLiNER or
    rules). organic_names=True also runs NER on cue-less segments to label organic name mentions (review / tests); the
    corpus scan leaves them out (they are excluded from sponsorship history anyway) to keep GPU cost bounded."""
    from . import ner as _ner
    ner_fn = ner_fn or _ner.names
    organic_fn = organic_fn or _ner.organic_names
    segs = segments(text)
    found: list[Detection] = []
    pending: list[tuple[int, str, str, str | None, str]] = []   # (seg idx, window, cue rule, promo code, cls)
    organic_windows: list[tuple[int, str]] = []
    for i, (seg, in_block) in enumerate(segs):
        prev = segs[i - 1][0] if i else ""
        for name, rx in NETWORK:
            m = rx.search(seg)
            if m:
                url = next((u for u in dm.URL_RX.findall(seg)), None)
                cu = dm.clean_url(url) if url else None
                found.append(Detection("network_disclosure", name, _snip(seg, m.start()), cu, dm.registrable(cu) if cu else None))
                break
        else:
            url_hits = [d for d in (classify_url(u, seg, prev, in_block, ctx) for u in dm.URL_RX.findall(seg)) if d]
            for d in url_hits:
                d.extra["seg"] = i
            found += url_hits
            sponsorish = any(d.cls in ("declared_sponsorship", "likely_sponsorship") for d in url_hits)
            exp = _explicit(seg)
            if exp and not sponsorish and not SELF_CUE.search(seg):
                pending.append((i, seg[exp[1].end():exp[1].end() + 160], f"explicit:{exp[0]}", None, "declared_sponsorship"))
            elif not exp and not url_hits:
                pr = _promo(seg)
                if pr and pr[0] == "promo_code" and not SELF_CUE.search(seg):
                    pending.append((i, seg[:240], "promo_code_named", pr[1], "likely_sponsorship"))
                elif organic_names and not pr and not AFFILIATE_TEXT.search(seg):
                    organic_windows.append((i, seg[:300]))
            if AFFILIATE_TEXT.search(seg) and not any(d.cls == "affiliate" for d in url_hits):
                found.append(Detection("affiliate", "affiliate_text", _snip(seg)))
    if pending:
        names = ner_fn([w for _, w, _, _, _ in pending])
        for (i, _w, rule, code, cls), ns in zip(pending, names):
            seg = segs[i][0]
            ns = [n for n in ns if not _is_own_name(n, ctx)]
            if not ns:
                found.append(Detection("uncertain", f"{rule}:no_identifiable_brand", _snip(seg), promo_code=code))
                continue
            for n in ns[:3]:
                # the same brand's URL within one sentence either side: the name is that domain's alias, not a second brand
                near = next((d for d in found if d.domain and abs(d.extra.get("seg", -99) - i) <= 1 and d.cls in ("declared_sponsorship", "likely_sponsorship")
                             and compact(n) == compact(dm.label(d.domain))), None)
                if near is not None:
                    near.aliases = sorted(set(near.aliases) | {n})
                    if cls == "declared_sponsorship" and near.cls == "likely_sponsorship":
                        near.cls, near.rule = "declared_sponsorship", f"{rule}+url"
                    continue
                found.append(Detection(cls, rule, _snip(seg), brand_name=n, promo_code=code, extra={"seg": i}))
    if organic_windows:
        for (i, _w), ns in zip(organic_windows, organic_fn([w for _, w in organic_windows])):
            for n in ns:
                if not _is_own_name(n, ctx):
                    found.append(Detection("organic_mention", "name_no_commercial_cue", _snip(segs[i][0]), brand_name=n))
    seen: set[tuple[str, str]] = set()
    out = []
    for d in found:
        k = (d.cls, d.identity())
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out
