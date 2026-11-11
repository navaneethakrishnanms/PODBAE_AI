"""Transcript quality: length vs duration plus garbage ratio. Low quality lowers confidence downstream."""
from __future__ import annotations

import re


def transcript_quality(text: str, duration_sec: int | None) -> dict:
    words = re.findall(r"\w+", text or "", flags=re.U)
    n = len(words)
    alpha = sum(ch.isalpha() or ch.isspace() for ch in text or "")
    garbage = 1 - (alpha / len(text)) if text else 1.0
    wpm = (n / (duration_sec / 60)) if duration_sec else None
    uniq = len(set(w.lower() for w in words)) / n if n else 0
    score, issues = 1.0, []
    if n < 150:
        score -= 0.5; issues.append("very short")
    if wpm is not None:
        if wpm < 40:
            score -= 0.4; issues.append(f"too short for episode length ({wpm:.0f} wpm)")
        elif wpm > 400:
            score -= 0.3; issues.append(f"implausibly dense ({wpm:.0f} wpm)")
    if garbage > 0.3:
        score -= 0.4; issues.append(f"garbage ratio {garbage:.2f}")
    if n > 200 and uniq < 0.08:
        score -= 0.3; issues.append("highly repetitive")
    score = round(max(0.0, min(1.0, score)), 2)
    return {"score": score, "usable": score >= 0.5, "words": n, "wpm": round(wpm, 1) if wpm else None,
            "garbage_ratio": round(garbage, 3), "issues": issues}
