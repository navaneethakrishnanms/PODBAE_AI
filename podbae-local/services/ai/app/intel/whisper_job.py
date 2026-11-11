"""OPTIONAL transcription job (faster-whisper on GPU). OFF by default (INTEL_WHISPER_ENABLED=false). Only runs for a
show the requesting user has claimed, only when they explicitly opt in, only for the latest 3 episodes, and only inside
the budget. NOTE: the model/runtime path is not exercised by the automated tests (no audio fixtures, no model download);
the gating (disabled / not opted in / not owner) is tested."""
from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
from sqlalchemy import select

from .config import get_settings
from .connectors.base import make_client
from .db import session_scope
from .models import Episode, ShowClaim, Transcript
from .trust import budget
from .trust.audit import audit
from .trust.jobs import JobContext, register
from .understanding.quality import transcript_quality

MAX_AUDIO_BYTES = 200_000_000
LATEST = 3


class NotAllowed(PermissionError):
    pass


def check_allowed(show_id: str, user_id: str | None, opt_in: bool) -> None:
    cfg = get_settings()
    if not cfg.whisper_enabled:
        raise NotAllowed("transcription is disabled (set INTEL_WHISPER_ENABLED=true)")
    if not opt_in:
        raise NotAllowed("the creator has not opted in to transcription")
    with session_scope() as s:
        if not user_id or not s.scalar(select(ShowClaim.id).where(ShowClaim.show_id == show_id, ShowClaim.user_id == user_id)):
            raise NotAllowed("only the creator of this show can request transcription of its audio")


@register("transcribe")
def job_transcribe(ctx: JobContext) -> dict:
    p = ctx.payload
    check_allowed(p["show_id"], p.get("user_id"), bool(p.get("opt_in")))
    cfg = get_settings()
    from faster_whisper import WhisperModel  # heavy import, only when actually used
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = WhisperModel("small", device=device, compute_type="float16" if device == "cuda" else "int8")
    done = 0
    with session_scope() as s:
        eps = list(s.scalars(select(Episode).where(Episode.show_id == p["show_id"], Episode.removed.is_(False), Episode.audio_url.is_not(None))
                             .order_by(Episode.published_at.desc()).limit(LATEST)))
    for ep in eps:
        if ctx.done(f"ep:{ep.id}"):
            continue
        minutes = (ep.duration_sec or 1800) / 60
        with session_scope() as s:
            dec = budget.check(s, minutes * cfg.cost_whisper_audio_minute, podcast_id=p["show_id"])
            if not dec.ok:
                budget.skip(s, "whisper", "faster-whisper", dec.reason or "budget", p["show_id"])
                break
        with tempfile.TemporaryDirectory() as td, make_client() as client:
            f = Path(td) / "a.mp3"
            size = 0
            with client.stream("GET", ep.audio_url) as r, f.open("wb") as fh:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise RuntimeError("audio too large")
                    fh.write(chunk)
            segs, _info = model.transcribe(str(f), vad_filter=True)
            text = " ".join(sg.text.strip() for sg in segs)
        q = transcript_quality(text, ep.duration_sec)
        with session_scope() as s:
            s.merge(Transcript(episode_id=ep.id, url=None, fmt="whisper", text=text[:200_000], word_count=q["words"], quality=q, origin="whisper"))
            budget.charge(s, "whisper", "faster-whisper", minutes, cfg.cost_whisper_audio_minute, podcast_id=p["show_id"])
            audit(s, f"user:{p.get('user_id')}", "transcribed", "show", p["show_id"], {"episode": ep.id, "device": device})
        ctx.mark(f"ep:{ep.id}")
        done += 1
    return {"transcribed": done}
