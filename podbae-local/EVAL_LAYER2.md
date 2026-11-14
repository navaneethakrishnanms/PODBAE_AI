# EVAL_LAYER2: Sponsor Intelligence, measured numbers

_Phase 3, 2026-11-14._
- Detector **`sponsor-rules-v1`** plus GLiNER `urchade/gliner_small-v2.1` (gliner 0.2.16, ran on cuda:0).
- Sponsor engine **`sponsor-draft-v1`**, status **draft-unapproved-by-founder**.
- No LLM was used for any value here.
- Regenerate: `npm run sponsors:scan` and then `npm run intel:eval2`. Raw data: `services/ai/eval/layer2.json`, `services/ai/eval/sponsor_scan.json`.

## 1. Corpus scanned
| | |
|---|---|
| Shows | 303 |
| Episodes (all stored show notes, not only the latest 20) | 35,877 |
| Transcripts | 422 |
| Events detected | 59,875 |
| Scan time | 322 s (GLiNER on GPU) |

## 2. Events by evidence class
| Class | Events | Counts as sponsorship history? |
|---|---|---|
| declared_sponsorship ("sponsored by", "thanks to our sponsor", ad headers) | 4,486 | yes |
| likely_sponsorship (promo code / vanity URL / offer language next to a brand) | 5,567 | yes |
| affiliate (amzn.to, ?ref=, affiliate disclosures) | 1,342 | no |
| podcast_promo (cross-promotion of another podcast) | 774 | no |
| self_promotion (own site, merch, Patreon, own socials) | 12,372 | no |
| network_disclosure (ad-choices / hosting boilerplate / regulatory disclaimers) | 12,953 | no |
| organic_mention (brand named without an ad cue) | 21,975 | no |
| uncertain (goes to the human review queue) | 406 | no, unless a reviewer confirms it |

## 3. Coverage
- **111 of 303 shows (36.6%)** have sponsorship history: at least one declared or likely event.
- **30 shows (9.9%)** have network disclosures only. These shows run ads (ad-choices or hosting boilerplate), but no brand appears in the text.
  - These are almost certainly dynamically inserted ads, which are invisible to text detection.
  - The real share of sponsored shows is therefore higher than 36.6%. Audio ad detection would be needed to see them; it is not built.
- The other ~162 shows show no sponsorship evidence in their notes or transcripts.

## 4. Brands
| | |
|---|---|
| Brands (not merged) | 988 |
| Active (an event within 180 days) | 260 |
| Inactive | 728 |
| **Active on ≥ 2 shows** | **57** (threshold for corpus expansion was 30, so no expansion was run) |
| Identity by domain / name only | 570 / 418 |
| Categories inferred (e5 + lexicon) / manual override | 979 / 9 |

Top active brands by show count:
- BetterHelp 11
- Quince 10
- Shopify 7
- Factor 7
- Uncommongoods 6
- Zocdoc 6
- Auraframes 5
- Rocket Money 5
- Buyraycon, Aquatru, AG1, Greenchef 4 each

Brands found only by domain get a name derived from the domain ("Uncommongoods", "Buyraycon"). These display names need a human rename in `/admin/sponsors/brands` or a seed alias.

**Category quality is weak for inferred categories.**
- Examples: Chime → "Fashion" / "Travel & auto"; Zenni → "Media & entertainment".
- Inferred categories carry confidence 0.35 and tier `inferred`, and the UI labels them as estimated.
- They should be corrected in `/admin/sponsors/brands` or in `seed/category_overrides.yaml`.
- The category_fit factor has a small weight for this reason.

## 5. Brand resolution (merge test, event level)
- 13 fixed cases (11 contain a brand), 55 pairs.
- Results: **3 true merges, 0 false merges, 0 missed merges** (precision 1.0, recall 1.0).
- Covered:
  - same domain via www. / shop. subdomains
  - a name next to its domain becomes an alias
  - a different domain with a similar name is not merged
  - two name-only spellings are never auto-merged
  - two advertisers on a tenant link platform (onelink.me) stay separate
  - a regulatory gambling disclaimer is not a brand
  - a denylisted platform is not a brand
  - a product brand gets a seeded parent
- This is a small hand-built test set, not a corpus-wide measure.

## 6. Detection precision vs human review: NOT MEASURED YET
- **0 human reviews exist**, so per-class precision is **unmeasured** for every class.
- The review queue is at `/admin/sponsors/review`. It is a stratified sample over classes (`sample_bucket`). Claude cannot act as a reviewer: the API rejects reviewer names that look like Claude.
- Agreement (Cohen's kappa and exact agreement) is computed per pair of reviewers once two or more people have reviewed the same events.
- Until reviews exist, read every class count above as "what the rules fired on", not as "what is true".

## 7. Privacy
- **59,875 stored snippets, 0 contain an email address.**
- 6,328 contact lines ("email me at…", "booking: …", "call …") were removed from snippets before storage.
- No person names are stored as brands: name-only brands come only from ad-cue windows, and contact lines are redacted first.
- Public "Sponsors seen" shows only declared or reviewed events.

## 8. Sponsor opportunities (every store show treated as a hypothetical member, read-only)
| | |
|---|---|
| Shows with ≥ 1 qualifying sponsor | **282 / 303** |
| Shows with ≥ 3 | 249 / 303 |
| No match | 21 / 303 (6.9%) |
| Median qualifying per show | 6 |
| Readiness: potential lead / discovery lead / verified | 1,458 / 760 / **0** |
| Confidence: High / Medium / Low | 273 / 836 / 1,109 |
| Gate rejections | inactive_brand 31,609 · insufficient_evidence 931 · already_sponsors_member 63 |
| Faithfulness problems (explanation numbers not traceable to a slot) | **0** |
| Latency p50 / p95 | 73 ms / 176 ms |

Notes:
- **0 Verified** is expected. "Verified" requires a brand registration matched by domain. The MVP advertisers in the Express database have no website, so `syncAdvertisers()` links 0 of them.
- Half the qualifying sponsor opportunities are Low confidence. This is mostly because two factors are disabled (audience_size_fit and geo_fit, which need audience data) and many brands have few events.
- Quality vs human judgement is **unmeasured**: no sponsor pair labels exist yet.
