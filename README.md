# Rumah123 Weekly Instagram Post Generator

Turns the week's Indonesian property news into ready-to-review Instagram drafts (carousel or single image) in Rumah123's brand voice: friendly, trustworthy, practical, never pushy.

**Option A** of the Rumah123 tool/workflow assignment. Built as a hybrid: designed and coded with Claude as the coding assistant, then tested and reviewed by hand.

## What it does

1. **Fetch** the last 7 days of news from Google News RSS (Indonesian edition, 6 configurable queries).
2. **Dedupe** near-identical headlines and pre-rank by keyword relevance (KPR, suku bunga, Bank Indonesia, harga rumah, ...).
3. **Curate** (LLM): pick 3 stories with different angles (market data, KPR education, engagement) and extract the only facts the writer may use.
4. **Write** (LLM): one post per story as JSON: hook, slides, caption, hashtags, visual idea.
5. **Guardrails** (plain Python): reject posts that break brand or fact rules, feed the exact violations back for one repair attempt, otherwise flag `needs_human_fix`.
6. **Deliver** as `outputs/<ISO week>/posts.md` + `posts.json`, opened as a pull request every Monday by GitHub Actions. Nothing is posted automatically.

Diagram and design rationale: [docs/architecture.md](docs/architecture.md).

## Guardrails (src/guardrails.py)

| Rule | How it is checked |
|---|---|
| Hook max 8 words, slide titles max 6 words, 5-7 slides, caption 70-140 words, max 6 emojis, 5-8 hashtags including `#Rumah123` | counts |
| No guarantees ("pasti disetujui", "dijamin", "bunga termurah", ...) | regex list in `data/config.json` |
| No competitor names | whole-word match |
| **Every number must exist in the sourced facts** (small counts, years and the "30%" rule of thumb are exempt) | number extraction vs `facts` |
| Statistics must be attributed (Bank Indonesia, Kontan, ...) and carry a source URL | whole-word match + field check |

## Run it

```bash
pip install -r requirements.txt

# 1. fully offline, no API key: inspect the curator prompt built from fixture news
python src/generator.py run --dry-run --fixture data/sample_news.json

# 2. check the saved sample drafts and run the unit tests
python src/generator.py validate outputs/2026-W45/posts.json
python -m unittest discover -s tests -v

# 3. real run (live RSS + Claude API)
export ANTHROPIC_API_KEY=...
python src/generator.py run
```

For the weekly schedule, add `ANTHROPIC_API_KEY` under *Settings > Secrets and variables > Actions*. `.github/workflows/weekly.yml` also supports manual runs from the Actions tab.

## Repo layout

```
src/generator.py          pipeline + CLI (run / validate / render)
src/guardrails.py         deterministic post checks
prompts/                  system.md, curator.md, writer.md (all prompts, plain text)
data/config.json          queries, keywords, limits, banned phrases, competitors
data/sample_news.json     offline fixture built from real 2026 articles
outputs/2026-W45/         sample drafts (posts.md is the readable version)
tests/                    negative tests for the guardrails
.github/workflows/        weekly cron + PR
```

## Sample output

[outputs/2026-W45/posts.md](outputs/2026-W45/posts.md): three drafts built from real Bank Indonesia and Kontan data (Q2 2026 residential property price survey, KPR outstanding of Rp852 trillion).

**Honest provenance:** these three drafts were written by Claude in a chat session using the same prompts and facts found through web search. They did **not** come from the `src/generator.py` API path, which I could not run end to end (see below). They do pass the same guardrails the pipeline uses.

## What was tested and what was not

Tested: guardrails on the sample drafts, 7 unit tests (including negative cases), dedupe and ranking, prompt building in `--dry-run --fixture` mode.

**Not tested end to end:**
- The live Google News fetch. From the build sandbox every request returned `403 Forbidden` from the network proxy, so the live path returned 0 articles. The original code failed silently here, which is why it now prints a warning per empty feed.
- The Claude API calls (curator and writer). No API key was available in the build environment. The first real run may need small fixes (for example JSON parsing of an unexpected reply). `_extract_json` strips code fences, but that is untested against real replies.

## Known limitations

- Google News RSS provides only a headline and short snippet, and its links are redirects. Facts are therefore limited to what the snippet says. The curator is told to skip thin stories rather than guess.
- The number check proves a number exists in the facts list, not that the facts list is correct. A human still has to check figures against the linked source.
- The latest property survey found on 7 Nov 2026 was Bank Indonesia's Q2 2026 release (7 Aug 2026). A Q3 release may be out soon, so the sample drafts need a freshness check before posting.

## What I would change next

1. Fetch full article text (or the Bank Indonesia press release page directly) so facts come from more than a snippet.
2. Add a second LLM pass that fact-checks each post against the full source text.
3. Add direct publisher RSS feeds in `extra_feeds` to reduce reliance on Google News redirects.
4. Generate the cover image from a brand template, and pull Instagram insights back in to learn which hooks earn comments.
5. Send the drafts to Slack for approve/reject instead of only a pull request.
