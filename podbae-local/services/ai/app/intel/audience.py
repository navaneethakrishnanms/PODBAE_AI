"""Creator-provided audience data: the main path to VERIFIED audience facts.

Two-step upload: (1) POST the CSV with no mapping -> we return columns, a suggested mapping and sample rows;
(2) POST again with the mapping -> we parse, validate (flagging implausible numbers; never silently rejecting or
silently accepting), store as data_tier=creator_provided with the file as evidence."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .config import REPO_ROOT
from .models import AudienceUpload
from .trust.audit import audit
from .trust.provenance import add_evidence, get_source, record

KINDS = {"countries": "audience.top_countries", "cities": "audience.top_cities", "age_bands": "audience.age_bands",
         "totals": "audience.totals"}
MAX_ROWS, MAX_BYTES = 5000, 2_000_000
AGE_BAND = re.compile(r"^\s*(?:under\s*\d{1,2}|<\s*\d{1,2}|\d{1,2}\s*[-–to]+\s*\d{1,2}|\d{1,2}\s*\+|\d{1,2}\s*(?:and|&)\s*(?:over|older|up))\s*$", re.I)


class UploadError(ValueError):
    pass


def read_csv(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if len(raw) > MAX_BYTES:
        raise UploadError(f"file too large (max {MAX_BYTES // 1_000_000} MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rdr = csv.DictReader(io.StringIO(text), dialect=dialect)
    cols = [c.strip() for c in (rdr.fieldnames or []) if c and c.strip()]
    if len(cols) < 1:
        raise UploadError("could not find a header row; export the CSV with column names in the first row")
    rows = []
    for i, r in enumerate(rdr):
        if i >= MAX_ROWS:
            raise UploadError(f"too many rows (max {MAX_ROWS})")
        rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items() if k})
    if not rows:
        raise UploadError("the file has a header but no data rows")
    return cols, rows


def suggest_mapping(cols: list[str]) -> dict[str, Any]:
    low = {c: c.lower() for c in cols}
    find = lambda *keys, skip=(): next((c for c, l in low.items() if c not in skip and any(k in l for k in keys)), None)  # noqa: E731

    def dim(kind: str, key: str) -> dict[str, Any]:
        label = find(key)
        return {"kind": kind, "label_col": label, "value_col": find("download", "listen", "plays", "streams", "count", skip=(label,)),
                "percent_col": find("percent", "%", "share", skip=(label,))}

    if find("country"):
        return dim("countries", "country")
    if find("city"):
        return dim("cities", "city")
    if find("age"):
        return dim("age_bands", "age")
    return {"kind": "totals", "columns": {c: c for c in cols if find("download", "listen", "follower", "subscriber", "plays") and any(k in low[c] for k in ("download", "listen", "follower", "subscriber", "plays"))}}


def _num(s: str) -> float | None:
    t = re.sub(r"[,%\s]", "", s or "")
    try:
        return float(t)
    except ValueError:
        return None


def parse_with_mapping(kind: str, mapping: dict, rows: list[dict[str, str]]) -> tuple[Any, list[dict]]:
    warns: list[dict] = []
    warn = lambda code, msg, **kw: warns.append({"code": code, "message": msg, **kw})  # noqa: E731
    if kind not in KINDS:
        raise UploadError(f"mapping.kind must be one of {sorted(KINDS)}")
    if kind == "totals":
        cols = mapping.get("columns") or {}
        if not cols:
            raise UploadError("totals mapping needs columns: {metric_name: csv_column}")
        out: dict[str, float] = {}
        for metric, col in cols.items():
            vals = [v for v in (_num(r.get(col, "")) for r in rows) if v is not None]
            if not vals:
                warn("no_numbers", f"column {col!r} has no numeric values", column=col)
                continue
            out[re.sub(r"\W+", "_", metric.lower()).strip("_")] = vals[-1] if len(vals) == 1 else sum(vals)
        for k, v in out.items():
            if v < 0:
                warn("negative", f"{k} is negative", metric=k)
            if v > 2_000_000_000:
                warn("implausible", f"{k}={v:,.0f} is implausibly large", metric=k)
            if v != int(v):
                warn("non_integer", f"{k} should be a whole number", metric=k)
        if not out:
            raise UploadError("no numeric totals could be read with that mapping")
        return out, warns
    lc, vc, pc = mapping.get("label_col"), mapping.get("value_col"), mapping.get("percent_col")
    if not lc or (not vc and not pc):
        raise UploadError("mapping needs label_col and at least one of value_col / percent_col")
    items = []
    for i, r in enumerate(rows, start=2):
        label = r.get(lc, "").strip()
        if not label:
            continue
        item: dict[str, Any] = {"label": label[:80]}
        if vc:
            v = _num(r.get(vc, ""))
            item["count"] = v
            if v is None:
                warn("not_numeric", f"row {i}: {r.get(vc)!r} is not a number", row=i)
            elif v < 0:
                warn("negative", f"row {i}: negative count for {label!r}", row=i)
        if pc:
            p = _num(r.get(pc, ""))
            item["percent"] = p
            if p is None:
                warn("not_numeric", f"row {i}: {r.get(pc)!r} is not a number", row=i)
            elif not 0 <= p <= 100:
                warn("out_of_range", f"row {i}: percent {p} for {label!r} is outside 0-100", row=i)
        if kind == "age_bands" and not AGE_BAND.match(label):
            warn("age_label", f"row {i}: {label!r} does not look like an age band (e.g. 18-24, 65+)", row=i)
        items.append(item)
    if not items:
        raise UploadError("no usable rows with that mapping")
    pcts = [x["percent"] for x in items if x.get("percent") is not None]
    if pcts and sum(pcts) > 105:
        warn("percent_sum", f"percentages add up to {sum(pcts):.1f} (> 100)")
    cnts = [x["count"] for x in items if x.get("count") is not None]
    if cnts and len(cnts) > 1 and max(cnts) > 0 and sum(cnts) > 0 and max(cnts) / sum(cnts) > 0.995 and len(cnts) > 3:
        warn("single_dominant", "one row accounts for >99.5% of the total; check the export")
    if pcts and max(pcts) == 100 and len(pcts) > 1:
        warn("single_dominant", "one row has 100% while others are listed")
    return items, warns


def store_upload(s: Session, show_id: str, user_id: str | None, filename: str, raw: bytes, mapping: dict) -> dict:
    cols, rows = read_csv(raw)
    kind = mapping.get("kind")
    parsed, warns = parse_with_mapping(kind, mapping, rows)
    sha = hashlib.sha256(raw).hexdigest()
    up_dir = REPO_ROOT / "data" / "intel_uploads"
    up_dir.mkdir(parents=True, exist_ok=True)
    path = up_dir / f"{sha}.csv"
    path.write_bytes(raw)
    up = AudienceUpload(show_id=show_id, user_id=user_id, filename=filename[:200], file_sha256=sha, mapping=mapping,
                        parsed={"kind": kind, "data": parsed, "rows": len(rows), "file": str(Path("data/intel_uploads") / path.name)},
                        warnings=warns)
    s.add(up)
    s.flush()
    src = get_source(s, "creator_upload", "creator", "Analytics exported by the show's creator; unverified by us but first-party")
    flagged = any(w["code"] in ("negative", "implausible", "out_of_range", "percent_sum", "not_numeric", "single_dominant") for w in warns)
    prov = record(s, "show", show_id, KINDS[kind], {"data": parsed, "plausibility_flags": [w["code"] for w in warns]}, source=src,
                  tier="creator_provided", method="parsed", confidence=0.4 if flagged else 0.85,
                  source_ref=f"audience_upload:{up.id}:{filename}:{sha[:12]}")
    add_evidence(s, "show", show_id, KINDS[kind], f"Creator upload '{filename}' ({len(rows)} rows, sha256 {sha[:12]})",
                 {"url": f"audience_upload:{up.id}", "file_sha256": sha}, src)
    audit(s, f"user:{user_id or 'unknown'}", "audience_upload", "show", show_id, {"kind": kind, "rows": len(rows), "warnings": len(warns)})
    return {"upload_id": up.id, "kind": kind, "field": KINDS[kind], "rows_read": len(rows), "stored": True, "data_tier": "creator_provided",
            "flagged_implausible": flagged, "warnings": warns, "provenance_id": prov.id, "preview": parsed if kind == "totals" else parsed[:10]}


def save_creator_profile(s: Session, show_id: str, user_id: str | None, goals: list[str] | None, openness: str | None,
                         blocked: list[str] | None, blocked_flags: list[str] | None = None) -> list[str]:
    src = get_source(s, "creator_declared", "creator", "Self-declared by the creator in PodBae")
    written = []
    for f, v in (("creator.goals", goals), ("creator.collaboration_openness", openness), ("creator.blocked_categories", blocked),
                 ("creator.blocked_brand_safety_flags", blocked_flags)):
        if v is not None:
            record(s, "show", show_id, f, v, source=src, tier="creator_provided", method="manual", confidence=1.0,
                   source_ref=f"user:{user_id or 'unknown'}")
            written.append(f)
    audit(s, f"user:{user_id or 'unknown'}", "creator_profile", "show", show_id, {"fields": written})
    return written
