"""Deterministic guardrails for generated Instagram posts.

These checks run *after* the LLM and do not depend on it, so a post that
breaks a brand rule is caught even when the model "forgets" an instruction.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "data" / "config.json").read_text(encoding="utf-8"))
LIM = CFG["limits"]

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
HASHTAG_RE = re.compile(r"#\w+")


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _norm(tok: str) -> str:
    return tok.replace(",", ".")


def _numbers(text: str) -> set[str]:
    # Strip hashtags and the brand name ("Rumah123") so their digits are not read as statistics.
    text = re.sub(r"rumah123", "", HASHTAG_RE.sub("", text), flags=re.I)
    return {_norm(t) for t in NUM_RE.findall(text)}


def _has_term(text: str, term: str) -> bool:
    """Whole-word match. Short acronyms ("BI") are case-sensitive so "biaya" does not count."""
    flags = 0 if len(term) <= 3 else re.IGNORECASE
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags) is not None


def _is_free_number(tok: str) -> bool:
    """Small counts ("5 tips", slide numbers), years and evergreen rules need no source."""
    if tok in CFG["evergreen_numbers"]:
        return True
    if "." not in tok:
        value = int(tok)
        return value <= 10 or 2020 <= value <= 2030
    return False


def check_post(post: dict) -> list[str]:
    """Return a list of human-readable violations (empty list = pass)."""
    problems: list[str] = []
    fmt = post.get("format", "carousel")
    hook = post.get("hook", "")
    caption = post.get("caption", "")
    slides = post.get("slides", []) or []
    hashtags = post.get("hashtags", []) or []

    # --- structure -------------------------------------------------------
    if _words(hook) == 0 or _words(hook) > LIM["hook_words_max"]:
        problems.append(f"hook has {_words(hook)} words (max {LIM['hook_words_max']})")

    lo, hi = LIM["caption_words"]
    n = _words(HASHTAG_RE.sub("", caption))
    if not lo <= n <= hi:
        problems.append(f"caption has {n} words (allowed {lo}-{hi})")

    if len(EMOJI_RE.findall(caption)) > LIM["emoji_max"]:
        problems.append(f"caption has more than {LIM['emoji_max']} emojis")

    h_lo, h_hi = LIM["hashtags"]
    if not h_lo <= len(hashtags) <= h_hi:
        problems.append(f"{len(hashtags)} hashtags (allowed {h_lo}-{h_hi})")
    if "#rumah123" not in [h.lower() for h in hashtags]:
        problems.append("missing #Rumah123 hashtag")

    if fmt == "carousel":
        s_lo, s_hi = LIM["slides"]
        if not s_lo <= len(slides) <= s_hi:
            problems.append(f"{len(slides)} slides (allowed {s_lo}-{s_hi})")
        for i, s in enumerate(slides, 1):
            t = s.get("title", "")
            if i == 1:  # the cover repeats the hook, which has its own (longer) limit
                continue
            if _words(t) > LIM["slide_title_words_max"]:
                problems.append(f"slide {i} title has {_words(t)} words (max {LIM['slide_title_words_max']})")

    # --- brand safety ----------------------------------------------------
    blob = " ".join(
        [hook, caption, post.get("visual_idea", "")]
        + [f"{s.get('title', '')} {s.get('body', '')}" for s in slides]
    )
    low = blob.lower()
    for pat in CFG["banned_patterns"]:
        if re.search(pat, low):
            problems.append(f"banned phrase matches /{pat}/")
    for name in CFG["competitors"]:
        if _has_term(blob, name):
            problems.append(f"mentions competitor '{name}'")

    # --- factual grounding ----------------------------------------------
    facts_text = " ".join(post.get("facts", []))
    allowed = _numbers(facts_text)
    claim_text = " ".join([hook, caption] + [f"{s.get('title', '')} {s.get('body', '')}" for s in slides])
    used = _numbers(claim_text)
    unsupported = sorted(t for t in used if t not in allowed and not _is_free_number(t))
    if unsupported:
        problems.append(f"numbers not found in sourced facts: {', '.join(unsupported)}")

    sourced_numbers = [t for t in used if t in allowed and not _is_free_number(t)]
    if sourced_numbers:
        if not any(_has_term(claim_text, term) for term in CFG["attribution_terms"]):
            problems.append("uses sourced numbers but never names the source (e.g. Bank Indonesia)")
        if not post.get("sources"):
            problems.append("no source URLs attached to the post")

    return problems
