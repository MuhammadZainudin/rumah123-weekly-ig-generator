# Architecture

```mermaid
flowchart TD
    A[GitHub Actions cron<br/>Mon 08:00 WIB] --> B[fetch_news<br/>Google News RSS, 6 queries, last 7 days]
    B --> C[dedupe<br/>difflib headline similarity >= 0.8]
    C --> D[heuristic_rank<br/>keyword score, keep top 25]
    D --> E[Curator LLM call<br/>pick 3 stories + extract facts from snippet only]
    E --> F[Writer LLM call per story<br/>hook, slides, caption, hashtags, visual idea]
    F --> G{guardrails.check_post}
    G -- violations --> H[Repair call:<br/>violations fed back to the model, 1 retry]
    H --> G
    G -- pass --> I[outputs/YYYY-Www/posts.json + posts.md]
    G -- still failing --> J[saved with needs_human_fix = true]
    I --> K[Pull request for human review]
    J --> K
    K --> L[Editor checks numbers vs sources, then posts manually]
```

## Why it is built this way

| Decision | Reason |
|---|---|
| Two LLM stages (curate, then write) | Story choice and copywriting need different instructions. Curation also extracts the *only* facts the writer may use. |
| Facts are extracted before writing | Lets the guardrail verify that every number in the post exists in the facts list. |
| Guardrails are plain Python | A model can forget a rule; a regex does not. Brand rules are enforced after generation, not just requested. |
| One repair attempt, then flag | Feeding the exact violations back usually fixes them; if not, a human sees a clear "needs fix" label instead of a silently bad post. |
| Output is a pull request | A property brand should not auto-post unreviewed statistics. |
| Offline `--fixture` mode | Lets anyone run and test the pipeline without network access or an API key. |
