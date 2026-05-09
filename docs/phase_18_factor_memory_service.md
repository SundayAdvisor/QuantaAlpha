# Phase 18 — Factor memory service (MemGovern-inspired)

Status: 📋 next-up — high ROI. ~1-2 days.

Adopt the architecture pattern from MemGovern (arXiv 2601.06789, ACL 2026)
to make our factor pool a **queryable experience service** instead of a
JSON file the LLM never reads. The goal: stop re-discovering failed
factors every iteration.

## The problem today

QA's factor pool lives at `log/<run_id>/trajectory_pool.json` — written
to disk by the mining loop, never read back by the LLM. So the LLM
proposes near-duplicate factors across iterations because:

1. It has no memory of what *already failed* in this run
2. It has no memory of what worked / didn't in *previous* runs
3. The hypothesis_details + feedback_details fields we recently added
   to `factor.json` exist but only get written *out* to the findings
   repo — nothing reads them *into* the next mining iteration

Concretely from your live run: we've seen `Rolling_5D_Return_TimeSeries_Rank_20D`
and `Downside_Spike_Vol_Normalized_5D20D` and `VWAP_Deviation_Sharpe_5D20D`
all get proposed in round 0 — these all live in roughly the same
"vol-conditional reversal" subspace. The LLM is wandering, not learning.

## The MemGovern pattern (what we're stealing)

MemGovern wraps SWE-Agent with a **separate memory server** the agent
queries via tool calls during reasoning:

```
                        ┌──────────────────┐
                        │ Experience Server│
                        │  (ChromaDB)      │
                        │                  │
                        │  curated cards:  │
                        │  - bug type      │
                        │  - fix pattern   │
                        │  - context       │
                        └────────┬─────────┘
                                 │
                                 │  /search, /get_card
                                 ▼
              ┌──────────────────────────────────┐
              │ SWE-Agent                        │
              │   tools: read/write/run/...      │
              │   NEW tools: /search /get_card   │
              └──────────────────────────────────┘
```

The agent calls `/search` mid-reasoning to find prior fixes for similar
bugs, then `/get_card` to retrieve the full context. Curated cards
(not raw history) — quality over quantity.

## Adapting it to QA

```
                        ┌────────────────────────────┐
                        │ QA Factor Memory Service   │
                        │   (ChromaDB + sqlite)      │
                        │                            │
                        │  factor cards:             │
                        │  - expression              │
                        │  - hypothesis              │
                        │  - mechanism family        │
                        │  - test metrics            │
                        │  - decision (passed/       │
                        │    rejected/regime-fit)    │
                        │  - lessons learned         │
                        └─────────────┬──────────────┘
                                      │
                                      │  HTTP (port 8002)
                                      │
              ┌───────────────────────┴────────────┐
              │ QA Factor Mining Loop              │
              │   tools: factor.py / runner / ...  │
              │   NEW tools given to the LLM:      │
              │     /search_factor_experience      │
              │     /get_factor_card               │
              └────────────────────────────────────┘
```

When the LLM is proposing a new factor, it can:
- Call `/search_factor_experience` with the *current hypothesis embedding*
  → returns top-K most-similar past factors with their outcomes
- Call `/get_factor_card` with a specific factor name → returns full card

The LLM is then told in its system prompt: *"Before proposing a factor,
search for similar prior factors. If similar factors failed, propose a
materially different mechanism. If similar factors succeeded, propose a
non-redundant variation."*

## What gets stored (the "card" schema)

Each factor that completes a trajectory writes a card:

```python
@dataclass
class FactorCard:
    factor_id: str                # e.g. "VWAP_Deviation_Sharpe_5D20D"
    expression: str               # the qlib expression
    hypothesis: str               # what was the hypothesis
    mechanism: str                # value-anchor / momentum / mean-reversion / ...
    primary_features: list[str]   # close, volume, ...
    horizon_days: int

    # Outcome
    test_rank_icir: float | None
    test_ir: float | None
    test_max_dd: float | None
    decision: str                 # "promoted" / "rejected" / "regime-fit" / "marginal"

    # The lessons (from feedback_details + manual curation)
    why_it_worked_or_failed: str  # 1-2 sentence summary from feedback_details
    do_not_retry_pattern: str | None  # if rejected, what mutation pattern to avoid

    # Provenance
    run_id: str
    trajectory_id: str
    parent_factor_ids: list[str]
    created_at: str

    # Vector embedding (for semantic search)
    hypothesis_embedding: list[float]   # via sentence-transformers
```

## Architecture: 3 components

### 1. The memory service (`quantaalpha/memory/server.py`)

Standalone FastAPI service on port 8002 (separate from the main backend
on 8000 so it can survive backend restarts). Endpoints:

```
POST  /factor_cards                  add a card (called by mining loop)
GET   /factor_cards/<id>             get one card
POST  /factor_cards/search           {hypothesis_text, k=5} → top-K
POST  /factor_cards/search_by_expr   {expression, k=5}      → AST-similar
GET   /factor_cards/by_mechanism/<m> all cards in family
GET   /factor_cards/by_decision/<d>  filter by promoted/rejected/etc
GET   /health
```

Backend: ChromaDB for embeddings, SQLite for structured fields.

### 2. The card writer (hooks into the existing mining loop)

After every trajectory completes (success or fail), write a card via
`POST /factor_cards`. Hook into `quantaalpha/factors/runner.py` where
trajectory metrics are computed.

For "lessons learned" / "do not retry" fields: use a small LLM call
post-trajectory to distill the feedback_details into curated text.
~30 tokens per trajectory; cheap.

### 3. The LLM tool wiring

Two new tools exposed to the planner / factor-generation prompt:

```yaml
# planning_prompts.yaml additions
tools:
  - name: search_factor_experience
    description: |
      Find prior factors similar to the hypothesis you're considering.
      Use this BEFORE proposing a factor expression. If similar factors
      failed (decision=rejected), propose a materially different
      mechanism. If similar factors succeeded (decision=promoted),
      propose a non-redundant variation.
    parameters:
      hypothesis: string
      k: int (default 5)

  - name: get_factor_card
    description: |
      Get full details on a specific past factor (expression, metrics,
      lessons learned).
    parameters:
      factor_id: string
```

Implementation: small Python wrappers around the HTTP endpoints, exposed
via QA's existing tool-call mechanism (look at `quantaalpha/llm/`).

## Build sequence

1. **Server skeleton** (~3 hr) — FastAPI + ChromaDB + SQLite + the 6
   endpoints. Stub responses for everything except add + search.
2. **Embedding pipeline** (~2 hr) — sentence-transformers `all-MiniLM-L6-v2`
   for the hypothesis embeddings. Local model, no API calls. Initialize
   ChromaDB on first run.
3. **Card writer hook** (~3 hr) — modify `runner.py` to write a card
   after each trajectory. Backfill cards from existing `trajectory_pool.json`
   files via a one-shot script.
4. **LLM tool wiring** (~3 hr) — add `search_factor_experience` and
   `get_factor_card` to the prompt template + provide the Python tool
   handlers.
5. **Test on the live mining run** (~half day) — run two sessions
   side-by-side: one with memory service on, one without. Compare
   factor pool diversity (mechanism distribution, AST-similarity
   distribution).

Total: 1-2 days.

## Service deployment

- Port 8002 (8000 = QA backend, 8001 = QC backend, 8002 = QA memory)
- Started independently of QA backend; survives QA restarts. Can run
  on a separate host eventually.
- Docker image planned (Phase 18.5) but not blocker for v1.

## Acceptance

- Memory service responds on `:8002/health`
- Manual `POST /factor_cards/search` with a hypothesis returns prior
  similar cards from the existing `trajectory_pool.json` runs
- A new mining run that has the memory tools enabled produces factors
  with materially different mechanisms vs a run without them (measure
  via mechanism-family entropy or AST-similarity histogram)

## Why now (not later)

The user just observed the live mining run is proposing 3 closely-related
"vol-conditional reversal" factors in round 0 alone. That's exactly the
mode-collapse this phase fixes. Highest ROI of the next-up plan.

## Caveats

- **Curation, not raw dump.** MemGovern's edge over plain RAG is the
  *governance*: a small LLM step distills feedback into a clean "card"
  before storage, instead of dumping the entire trajectory pool. Skipping
  this step turns the service into noise.
- **Cold start.** The first 5-10 mining iterations will have an empty
  memory; tools should gracefully no-op when search returns nothing.
- **Cross-run vs in-run scope.** v1 stores cards across all runs (global
  experience). Optionally add a `run_id` filter for per-run scoped search
  if cross-run noise becomes a problem.

## File-level deliverables

```
quantaalpha/memory/
  __init__.py
  server.py             # FastAPI service on :8002
  schema.py             # FactorCard dataclass + sqlite migrations
  embeddings.py         # sentence-transformers wrapper
  search.py             # ChromaDB query helpers
  tools.py              # /search and /get_card LLM-tool handlers
  curate.py             # LLM-based card curation (distills feedback)

quantaalpha/factors/runner.py
  - hook write_factor_card() after each trajectory completes

quantaalpha/pipeline/prompts/planning_prompts.yaml
  - add tool descriptions for search_factor_experience + get_factor_card

scripts/
  start_memory_service.py   # uvicorn launcher for :8002
  backfill_factor_cards.py  # one-shot: walk log/*/trajectory_pool.json,
                            #           write cards to memory service

docs/
  phase_18_factor_memory_service.md   # this file
```

## Cross-references

- Source paper: MemGovern, arXiv 2601.06789, ACL 2026
- [phase_4_auto_publish.md](phase_4_auto_publish.md) — already extracts
  hypothesis_details + feedback_details into findings/factor.json; this
  phase makes them queryable in-loop too
- [phase_13_admission_gate_upgrades.md](phase_13_admission_gate_upgrades.md)
  — AST-similarity dedup is complementary (gates duplicates at admission;
  this phase prevents duplicates at proposal time)
- [phase_19_slot_based_mutation.md](phase_19_slot_based_mutation.md) —
  EvoControl-inspired sibling phase that operates on a different axis
  (mutation efficiency, not memory)
