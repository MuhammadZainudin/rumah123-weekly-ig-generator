#!/usr/bin/env python3
"""Rumah123 Weekly IG Post Generator.

Pipeline:  fetch news -> dedupe -> curate (LLM) -> write posts (LLM) -> guardrails -> save for review.
Nothing is ever posted automatically; output is a markdown + JSON draft for a human editor.

Usage
  python src/generator.py run                      # live news + Claude API (needs ANTHROPIC_API_KEY)
  python src/generator.py run --dry-run            # live news, prints the curator prompt, no API call
  python src/generator.py run --dry-run --fixture data/sample_news.json   # fully offline
  python src/generator.py validate outputs/2026-W45/posts.json            # re-check saved drafts
  python src/generator.py render outputs/2026-W45/posts.json              # rebuild posts.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import html
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guardrails import check_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
OUTPUTS = ROOT / "outputs"
CFG = json.loads((ROOT / "data" / "config.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- news
@dataclass
class Article:
    title: str
    source: str
    link: str
    published: str  # ISO 8601
    summary: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def fetch_news(days: int) -> list[Article]:
    """Pull Google News RSS (Indonesian edition) for each configured query."""
    import feedparser

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    urls = [
        f"https://news.google.com/rss/search?q={quote_plus(f'{q} when:{days}d')}&hl=id&gl=ID&ceid=ID:id"
        for q in CFG["queries"]
    ] + CFG.get("extra_feeds", [])

    found: list[Article] = []
    for url in urls:
        feed = feedparser.parse(url)
        if not feed.entries:  # feedparser swallows network errors; make the failure visible
            print(f"warning: no entries from {url} ({getattr(feed, 'bozo_exception', 'empty feed')})", file=sys.stderr)
        for e in feed.entries:
            if getattr(e, "published_parsed", None):
                when = dt.datetime(*e.published_parsed[:6], tzinfo=dt.timezone.utc)
            else:
                when = dt.datetime.now(dt.timezone.utc)
            if when < cutoff:
                continue
            title = _clean(e.get("title", ""))
            source = (e.get("source") or {}).get("title", "")
            if not source and " - " in title:  # Google News appends " - Outlet"
                title, source = title.rsplit(" - ", 1)
            found.append(Article(title, source, e.get("link", ""), when.isoformat(), _clean(e.get("summary", ""))))
    return found


def load_fixture(path: Path) -> list[Article]:
    return [Article(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def dedupe(articles: list[Article], threshold: float = 0.8) -> list[Article]:
    """Drop near-identical headlines (the same wire story syndicated by several outlets)."""
    kept: list[Article] = []
    for a in articles:
        t = a.title.lower()
        if any(difflib.SequenceMatcher(None, t, k.title.lower()).ratio() >= threshold for k in kept):
            continue
        kept.append(a)
    return kept


def heuristic_rank(articles: list[Article]) -> list[Article]:
    """Cheap pre-filter so the LLM only sees the most relevant ~25 candidates."""

    def score(a: Article) -> int:
        text = f"{a.title} {a.summary}".lower()
        return sum(w for kw, w in CFG["keywords"].items() if kw in text)

    return sorted(articles, key=score, reverse=True)


# ---------------------------------------------------------------------------- LLM
def _fill(template: str, **values: str) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    return template


def build_curator_prompt(candidates: list[Article], n: int) -> str:
    listing = "\n".join(
        f"[{i}] {a.title} | {a.source} | {a.published[:10]}\n    {a.summary[:400]}" for i, a in enumerate(candidates)
    )
    return _fill(
        (PROMPTS / "curator.md").read_text(encoding="utf-8"),
        COUNT=str(len(candidates)),
        N=str(n),
        CANDIDATES=listing,
    )


def build_writer_prompt(article: Article, pick: dict, feedback: list[str] | None = None) -> str:
    fb = ""
    if feedback:
        fb = "FIX THESE PROBLEMS FROM YOUR PREVIOUS ATTEMPT:\n" + "\n".join(f"- {p}" for p in feedback)
    return _fill(
        (PROMPTS / "writer.md").read_text(encoding="utf-8"),
        TITLE=article.title,
        SOURCE=article.source,
        DATE=article.published[:10],
        ANGLE=pick.get("angle", ""),
        FORMAT=pick.get("format", "carousel"),
        FACTS="\n".join(f"- {f}" for f in pick.get("facts", [])),
        FEEDBACK=fb,
    )


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    return json.loads(raw)


def llm_json(user_prompt: str, max_tokens: int = 3000) -> dict:
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    resp = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", CFG["model"]),
        max_tokens=max_tokens,
        system=(PROMPTS / "system.md").read_text(encoding="utf-8"),
        messages=[{"role": "user", "content": user_prompt}],
    )
    return _extract_json("".join(b.text for b in resp.content if b.type == "text"))


def write_post(article: Article, pick: dict) -> dict:
    """Generate -> check -> one repair attempt with the violations fed back to the model."""
    feedback: list[str] | None = None
    post: dict = {}
    problems: list[str] = []
    for attempt in (1, 2):
        post = llm_json(build_writer_prompt(article, pick, feedback))
        post["facts"] = pick.get("facts", [])
        post["sources"] = [{"title": article.title, "outlet": article.source, "url": article.link}]
        problems = check_post(post)
        if not problems:
            break
        feedback = problems
    post["attempts"] = attempt
    post["violations"] = problems
    post["needs_human_fix"] = bool(problems)
    return post


# -------------------------------------------------------------------------- output
def iso_week(today: dt.date | None = None) -> str:
    y, w, _ = (today or dt.date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def render_markdown(data: dict) -> str:
    lines = [f"# Rumah123 Instagram drafts, {data['week']}", ""]
    if data.get("provenance"):
        lines += [f"> {data['provenance']}", ""]
    for i, p in enumerate(data["posts"], 1):
        lines += [f"## Post {i}: {p['hook']}  ({p.get('format', 'carousel')})", ""]
        if p.get("needs_human_fix"):
            lines += ["**NEEDS HUMAN FIX:** " + "; ".join(p["violations"]), ""]
        if p.get("slides"):
            lines.append("**Slides**")
            for n, s in enumerate(p["slides"], 1):
                lines.append(f"{n}. **{s['title']}**: {s['body']}")
            lines.append("")
        lines += ["**Caption**", "", p["caption"], "", " ".join(p["hashtags"]), ""]
        lines += [f"**Visual:** {p['visual_idea']}", ""]
        lines.append("**Facts used**")
        lines += [f"- {f}" for f in p.get("facts", [])]
        lines.append("")
        lines.append("**Sources**")
        lines += [f"- [{s['title']}]({s['url']})" for s in p.get("sources", [])]
        lines.append("")
    return "\n".join(lines)


def save(data: dict) -> Path:
    out_dir = OUTPUTS / data["week"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "posts.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "posts.md").write_text(render_markdown(data), encoding="utf-8")
    return out_dir


# ---------------------------------------------------------------------------- CLI
def cmd_run(args: argparse.Namespace) -> int:
    n = args.n or CFG["posts_per_week"]
    if args.fixture:
        articles = load_fixture(Path(args.fixture))  # fixtures skip the age filter
    else:
        articles = fetch_news(CFG["max_age_days"])
    print(f"fetched {len(articles)} articles")
    articles = dedupe(articles)
    print(f"{len(articles)} after dedupe")
    candidates = heuristic_rank(articles)[:25]
    if not candidates:
        print("no candidates found; nothing to do", file=sys.stderr)
        return 1

    curator_prompt = build_curator_prompt(candidates, n)
    if args.dry_run:
        print("\n----- CURATOR PROMPT (dry run, no API call) -----\n")
        print(curator_prompt)
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (use --dry-run to inspect prompts offline)", file=sys.stderr)
        return 2

    picks = llm_json(curator_prompt, max_tokens=2000).get("picks", [])[:n]
    posts = []
    for pick in picks:
        article = candidates[int(pick["id"])]
        print(f"writing post for: {article.title}")
        posts.append(write_post(article, pick))

    data = {"week": iso_week(), "model": os.environ.get("ANTHROPIC_MODEL", CFG["model"]), "posts": posts}
    out = save(data)
    flagged = sum(p["needs_human_fix"] for p in posts)
    print(f"saved {len(posts)} drafts to {out} ({flagged} need a human fix)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    failed = 0
    for i, p in enumerate(data["posts"], 1):
        problems = check_post(p)
        print(f"post {i} [{p['hook']}]: {'PASS' if not problems else 'FAIL'}")
        for prob in problems:
            print(f"   - {prob}")
        failed += bool(problems)
    return 1 if failed else 0


def cmd_render(args: argparse.Namespace) -> int:
    path = Path(args.path)
    data = json.loads(path.read_text(encoding="utf-8"))
    (path.parent / "posts.md").write_text(render_markdown(data), encoding="utf-8")
    print(f"wrote {path.parent / 'posts.md'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="generate this week's drafts")
    r.add_argument("--dry-run", action="store_true", help="print the curator prompt and stop (no API call)")
    r.add_argument("--fixture", help="read articles from a JSON file instead of live RSS")
    r.add_argument("-n", type=int, help="number of posts (default from config)")
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("validate", help="run guardrails on a saved posts.json")
    v.add_argument("path")
    v.set_defaults(fn=cmd_validate)

    m = sub.add_parser("render", help="rebuild posts.md from posts.json")
    m.add_argument("path")
    m.set_defaults(fn=cmd_render)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
