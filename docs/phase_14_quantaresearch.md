# Phase 14 — QuantaResearch (idea sourcing pipeline)

Status: 📋 sketch — new sibling project. ~1-2 days for v1.

The factor-mining loop today starts from text the user types into the
home-page chat input. That text is the bottleneck for novelty —
hypotheses are limited by what the user thought of last. Real quant
teams spend significant time reading academic papers, sell-side research,
news, and conference talks to source ideas. This phase automates that.

**Goal**: every morning, a queue of 5-10 candidate hypotheses sourced
from current academic flow, formalized into structured QA objectives,
filtered against available data, ready to feed into mining.

## What gets built

A new sibling project `repos/QuantaResearch/` with the same structure as
QA/QC (separate repo so QA stays scoped to factor mining + so research
ideas can feed multiple downstream consumers later).

```
repos/QuantaResearch/
├── README.md
├── docs/
│   ├── roadmap.md
│   └── how_to_add_a_source.md
├── quantaresearch/
│   ├── __init__.py
│   ├── sources/
│   │   ├── arxiv.py             # daily q-fin q-fin.PM/.ST/.TR papers
│   │   ├── semantic_scholar.py  # citation graph + abstracts
│   │   ├── nber_rss.py          # NBER working papers
│   │   ├── alpha_architect.py   # weekly anomaly summaries (RSS)
│   │   └── quantocracy.py       # daily aggregator (RSS)
│   ├── pipeline/
│   │   ├── formalize.py         # LLM: free-text abstract → structured hypothesis
│   │   ├── readiness.py         # data-readiness check vs QA qlib bundle
│   │   ├── novelty.py           # de-dup vs QuantaAlphaFindings
│   │   └── feed_to_qa.py        # POST to QA's mining/start
│   ├── store/
│   │   ├── ideas_raw/<YYYY-MM-DD>.jsonl   # daily snapshot from each source
│   │   ├── ideas_formalized/<id>.json     # post-LLM, structured
│   │   ├── ideas_ready/<id>.json          # passed data-readiness + novelty
│   │   └── ideas_history.jsonl            # everything we've ever proposed (for novelty dedup)
│   └── llm/
│       ├── prompts/
│       │   ├── formalize.yaml   # system prompt for hypothesis formalization
│       │   └── novelty.yaml     # system prompt for "have we already tried this?"
│       └── client.py            # thin wrapper around Claude Code (mirrors QA's pattern)
├── scripts/
│   ├── daily_fetch.py           # cron-friendly: run all sources, formalize, check, queue
│   └── feed_top_n_to_qa.py      # take top-N ready ideas, kick off mining
└── tests/
```

## Stage 0 — Idea sourcing (where the candidates come from)

Free / ethical sources only. No SSRN scraping (TOS issues).

| Source | API | Coverage |
|---|---|---|
| **arXiv q-fin** | [export.arxiv.org/api](http://export.arxiv.org/api) | Daily new papers tagged q-fin.PM, q-fin.ST, q-fin.TR. 5-15 new papers/day. |
| **Semantic Scholar** | [api.semanticscholar.org](https://api.semanticscholar.org) | Citation graph + abstracts. Use for "papers citing X" queries. |
| **NBER** | RSS at [www.nber.org/rss](https://www.nber.org/rss) | Weekly working papers; finance + economics |
| **AlphaArchitect** | RSS at [alphaarchitect.com/feed](https://alphaarchitect.com/feed) | Weekly factor-research summaries |
| **Quantocracy** | RSS at [quantocracy.com/feed](https://quantocracy.com/feed) | Daily aggregator of practitioner blogs |

Each source module emits `IdeaRaw` records:

```json
{
  "id": "arxiv-2510.12345",
  "source": "arxiv",
  "title": "Cross-asset momentum spillovers via news sentiment",
  "abstract": "We document a novel cross-asset momentum factor where ...",
  "authors": ["Smith, J.", "Doe, A."],
  "url": "https://arxiv.org/abs/2510.12345",
  "fetched_at": "2026-05-09T06:00:00",
  "tags_raw": ["q-fin.ST"],
  "category_hint": "cross-sectional momentum"
}
```

## Stage 1 — Formalization (LLM converts text → structured hypothesis)

The LLM reads the abstract and emits a structured spec QA can mine on:

```json
{
  "id": "arxiv-2510.12345",
  "title": "News-sentiment cross-asset momentum",
  "objective_text": "Mine a factor combining sector-level news sentiment delta with cross-asset momentum. Use 5-day forward horizon, sp500 universe.",
  "mechanism": "cross-sectional",
  "primary_features": ["close", "volume", "sentiment"],
  "horizon_days": 5,
  "universe": "sp500",
  "expected_sign": "positive",
  "expected_effect_size": "low (RankICIR 0.03-0.05)",
  "novelty_vs_existing": "Different from AlphaAgent's intra-asset momentum: this uses cross-asset spillover via news.",
  "data_required": ["price_history", "news_sentiment_proxy"],
  "feasibility": "needs_news_sentiment_feature"
}
```

System prompt (`prompts/formalize.yaml`):

```
You are a senior quant researcher formalizing an academic paper abstract
into a concrete factor-mining objective for the QuantaAlpha system. Given
an abstract, produce a STRICT JSON record with fields:
  - title (≤80 chars human-readable name)
  - objective_text (2-3 sentence directive the QA mining loop can run on)
  - mechanism (one of: value-anchor, momentum, mean-reversion,
    volatility-derived, volume-derived, cross-sectional, regime-conditioned,
    calendar-effect, sector-neutral-composite, fundamental-proxy)
  - primary_features (subset of: close, open, high, low, volume, change,
    sentiment, return)
  - horizon_days (int)
  - universe (sp500 | nasdaq100 | commodities)
  - expected_sign (positive | negative)
  - expected_effect_size (low | medium | high) and what RankICIR range
  - novelty_vs_existing (1 sentence — what differs from common factor
    families)
  - data_required (list of data sources)
  - feasibility (ok | needs_X | infeasible)

Be honest about feasibility. If the paper uses minute-bar VWAP or
proprietary news sentiment, mark it needs_X.
```

## Stage 2 — Data readiness check

Auto-rejects infeasible hypotheses before they hit QA mining (saves LLM
tokens). Cross-checks:

| Check | Reject if |
|---|---|
| `universe` exists | Not in `data/qlib/us_data/instruments/*.txt` |
| `primary_features` exist | Not in `data/qlib/us_data/features/<ticker>/` per ticker |
| Date range covers test segment | Calendar `day.txt` doesn't include needed dates |
| Required external data | `feasibility != ok` and we can't auto-resolve |

Returns `ideas_ready/<id>.json` for passes, logs rejections to
`ideas_rejected/<id>.json` with reason.

## Stage 2.5 — Novelty check vs existing findings

Compare formalized hypothesis against everything already in
QuantaAlphaFindings (the auto-publish target):

```python
def is_novel(formalized_idea, findings_dir):
    # Read all factors/<slug>/factor.json from findings repo
    existing = load_existing_factor_jsons(findings_dir)

    # LLM judge: does this idea materially differ from existing?
    prompt = f"""
    New idea: {formalized_idea['objective_text']}
    Existing factors:
    {existing_summaries}
    Question: is the new idea materially different in MECHANISM or
    DATA SOURCE? Answer JSON: {{"novel": bool, "reason": str}}
    """
    ...
```

Drops near-duplicates of already-mined factors before they hit the queue.

## Stage 2.75 — Auto-feed to QA

For each ready+novel idea (top N per day, default N=3 to control LLM costs):

```python
import requests
res = requests.post(
    "http://localhost:8000/api/v1/mining/start",
    json={
        "direction": idea["objective_text"],
        "displayName": f"auto: {idea['title'][:60]}",
        "universe": idea["universe"],
        "numDirections": 3,    # smaller for auto-runs
        "maxRounds": 3,
    },
)
```

Stamp the resulting QA run with the idea ID via the manifest writer
(Phase 6) so we can trace `idea → run → factor → bundle → strategy`
end-to-end later.

## Build order within this phase

1. **arxiv source + LLM formalizer** (~half day) — `sources/arxiv.py` +
   `pipeline/formalize.py` + a CLI script that takes a paper ID and
   prints the structured idea. Validates the prompt before adding more
   sources.
2. **Data readiness check** (~3 hours) — minimal validation.
3. **Novelty check** (~3 hours) — LLM judge against findings repo.
4. **Auto-feed** (~2 hours) — POST to QA's mining/start with proper
   `displayName` traceability.
5. **Add NBER + AlphaArchitect + Quantocracy + Semantic Scholar
   sources** (~half day). Each is ~30 lines once arxiv is working.
6. **Cron / Task Scheduler integration** (~30 min) — Windows Task
   Scheduler hits `scripts/daily_fetch.py` at 06:00.

Total: 1.5-2 days.

## Operational decisions

- **Where do raw ideas live?** Local JSONL files (gitignored). Move to
  SQLite if scale grows >10K ideas.
- **Auto-flow vs human review queue?** Default: human-review queue.
  Daily fetch produces the queue; user reviews + approves before
  mining kicks off. After 30 days of stable queue quality, can flip a
  flag to auto-feed top-N.
- **How aggressive is novelty dedup?** Day 1: hypothesis-text
  similarity (LLM judge). Phase 2: also factor-expression-AST
  equivalence (after formalization).
- **Token budget?** ~5K tokens per day for fetch + formalize across all
  sources. Trivial.

## Acceptance

- Run `python scripts/daily_fetch.py` once → produces ~5-10 ready ideas
  in `ideas_ready/` from yesterday's arXiv q-fin papers
- Each ready idea has all required fields populated
- Novelty check correctly flags duplicates of existing findings
- Manual `feed_top_n_to_qa.py` POSTs successfully start a QA mining
  run with `displayName` containing the idea ID

## Cross-references

- [research_pipeline.md](research_pipeline.md) — full lifecycle context
- [phase_6_manifest_and_naming.md](phase_6_manifest_and_naming.md) — the
  manifest schema we'll stamp idea IDs into
- [phase_4_auto_publish.md](phase_4_auto_publish.md) — what gets compared
  against in stage 2.5 (the findings repo)
