# Full Research Pipeline — Real Quant Workflow as Code

Status: 📋 plan (no code yet) — 2026-05-09

QuantaAlpha + QuantaQC implement two pieces of a real quant team's
process: factor mining (QA) and strategy mining (QC). This doc maps the
remaining stages — idea sourcing, hypothesis formalization, data
readiness, risk decomposition, live monitoring, knowledge persistence —
into a concrete buildable plan.

The aim: turn "we have factor mining + strategy mining" into "we have a
quant research firm in code."

---

## The full quant research lifecycle (10 stages)

What a working quant team actually does, in order. Each stage feeds
the next; the loop closes at stage 10 → stage 0.

| # | Stage | What happens in a real team | Where we are today |
|---|---|---|---|
| 0 | **Idea sourcing** | Read arXiv q-fin / SSRN / sell-side notes / news; surface candidate hypotheses to test | ❌ no tool — user types objectives by hand into the QA chat input |
| 1 | **Hypothesis formalization** | "Intuition" → spec: feature + universe + horizon + expected sign + magnitude | ⚠️ partial — QA's planner does this implicitly inside the mining loop, but no upstream filter / queue |
| 2 | **Data readiness check** | Do we have the features this hypothesis needs? Survivorship bias? Point-in-time? | ❌ no pre-flight — bad hypotheses waste mining LLM tokens |
| 3 | **Factor mining** | Build the signal, score it cross-sectionally, evolve via mutation/crossover | ✅ QA |
| 4 | **Walk-forward validation** | Test factor stability across regimes / time windows | 📋 sketched ([walk_forward_validation.md](walk_forward_validation.md)) — not built |
| 5 | **Risk decomposition** | What's the alpha *after* factor exposure (FF3/5, Barra)? Sector tilts? Correlation with existing book? | ❌ not built — we don't know if mined factors are just style tilts |
| 6 | **Strategy construction** | Wrap signal in entry/exit/sizing rules, position management | ✅ QC |
| 7 | **Parameter optimization** | Walk-forward optimization, hyperparameter robustness | ✅ QC Phase 6 (shipped) |
| 8 | **Live / paper deployment** | Real-money OOS test on QC paper-trading | 📋 sketched (QC Phase 11/12) |
| 9 | **Monitoring + decay detection** | Watch for performance erosion vs IS; trigger refresh when alpha decays | ❌ not built |
| 10 | **Knowledge persistence** | "What worked, what didn't, why" — feed back into stage 0 next cycle | ⚠️ partial — auto-publish to QuantaAlphaFindings captures factors but not lessons |

**Solid: 3, 6, 7. Sketched: 4, 8. Missing: 0, 1, 2, 5, 9, 10.**

That gap is what makes "real quant" different from "factor miner + strategy miner."

---

## The user's proposed flow vs the full picture

User originally proposed:
**research pipeline → QA → build model → QC**

That maps to stages 0/1 → 3 → (Phase 5/6 model bundle) → 6/7. Missing:
- Stage 2 (data readiness)
- Stage 4 (walk-forward validation)
- Stage 5 (risk decomposition — biggest honest-alpha blind spot)
- Stage 8 (live deployment)
- Stage 9 (decay monitoring)
- Stage 10 (the feedback loop that closes the cycle)

The middle 3 → 7 is the shiny part most papers focus on. The flanking stages (0, 1, 2 upstream; 5, 9, 10 downstream) are where most real-quant work actually happens.

---

## Architecture — proposed end state

```
┌─────────────────────────────────────────────────────────────────┐
│ QuantaResearch (NEW project, sibling of QA/QC)                  │
│                                                                 │
│  Stage 0: Idea sourcing                                         │
│   ├─ arxiv_crawler.py    (daily q-fin paper fetch)             │
│   ├─ semantic_scholar.py (citation graph + abstracts)          │
│   ├─ nber_rss.py         (NBER working papers feed)            │
│   ├─ alpha_architect.py  (weekly anomaly summaries — RSS)      │
│   └─ → ideas/raw/<date>.json (queue of candidate ideas)        │
│                                                                 │
│  Stage 1: Hypothesis formalization                              │
│   ├─ LLM extracts: feature, universe, horizon, expected effect │
│   ├─ De-dups against existing QuantaAlphaFindings              │
│   ├─ Optional human review queue                                │
│   └─ → ideas/formalized/<id>.json (structured hypotheses)      │
│                                                                 │
│  Stage 2: Data readiness                                        │
│   ├─ Verify required features exist (close, volume, vwap, ...)  │
│   ├─ Verify universe covers required tickers                    │
│   ├─ Survivorship-bias check (point-in-time membership)         │
│   └─ → ideas/ready/<id>.json (data-ready hypotheses)           │
│                                                                 │
│  Stage 2.5: Auto-feed into QA                                   │
│   └─ POST /api/v1/mining/start (with displayName = idea_id)    │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                          QuantaAlpha (built — stages 3, partial 4)
                               │
                               ▼
                          QuantaAlphaFindings (built — partial 10)
                               │
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
           Stage 4: WF    Stage 5: Risk    Stage 6: Strategy
           validation     decomp (NEW)     (QC, built)
           (sketched)     │
                  │       │            │
                  └───────┴────────────┘
                               │
                               ▼
                       Stages 7→9 (QC + monitoring)
                       Stage 7: ✅ optimization
                       Stage 8: 📋 paper trading
                       Stage 9: ❌ decay monitor (NEW)
                               │
                               ▼
                       Stage 10: feedback to stage 0
                       (NEW: enrich QuantaAlphaFindings with
                        "lessons" — what worked / didn't / why)
```

---

## Tools available for stage 0 (idea sourcing)

Free / ethical sources only (no SSRN scraping — TOS issues):

| Source | Access | What it gives | Refresh rate |
|---|---|---|---|
| **arXiv q-fin** | Free API ([export.arxiv.org/api](http://export.arxiv.org/api)) | Daily new papers tagged q-fin.PM, q-fin.ST, q-fin.TR | Daily |
| **Semantic Scholar API** | Free | Citation graph, abstracts, related-work links | Real-time |
| **NBER working papers** | Free RSS | Top finance/economics WPs | Weekly |
| **Federal Reserve papers** | Free | FEDS papers | Weekly |
| **AlphaArchitect blog** | Free RSS | Curated weekly factor summaries | Weekly |
| **Twitter/X quant accounts** | API limited | Noisy but timely | Real-time |
| **Quantpedia** | Paid (~$300–500/yr) | ~500 curated anomaly factors with PDFs + replication code | Weekly |

Free baseline coverage: arXiv + Semantic Scholar + NBER + AlphaArchitect = ~80% of academic factor flow. Buildable in 1–2 days.

---

## Concrete build proposal

A new project `QuantaResearch` (sibling repo, mirroring QA/QC layout):

```
repos/QuantaResearch/
├── .gitignore
├── README.md
├── pyproject.toml
├── docs/
│   ├── roadmap.md
│   └── stage_<n>_<name>.md (per-stage specs as built)
├── quantaresearch/
│   ├── __init__.py
│   ├── sources/
│   │   ├── arxiv.py
│   │   ├── semantic_scholar.py
│   │   ├── nber_rss.py
│   │   └── alpha_architect.py
│   ├── pipeline/
│   │   ├── formalize.py        # LLM: free-text abstract → structured hypothesis
│   │   ├── readiness.py        # data-readiness check vs QA qlib bundle
│   │   └── feed_to_qa.py       # POST to QA's mining/start
│   └── store/
│       ├── ideas_raw/<date>/   # daily snapshot from each source
│       ├── ideas_formalized/   # post-LLM, structured
│       └── ideas_ready/        # post-readiness check
├── scripts/
│   ├── daily_fetch.py          # cron-friendly: run all sources
│   └── feed_top_n_to_qa.py     # take top-N ready ideas, kick off mining
├── frontend-v2/                # optional FE — Vite/React/Tailwind matching QA/QC pattern
│   └── (similar structure to QA's)
└── tests/
```

### Effort + value matrix

| Component | Effort | Value | Build order |
|---|---|---|---|
| Stage 0/1: arXiv + LLM formalizer + auto-feed to QA | **1–2 days** | High — replaces "user thinks of objective" with "system proposes from current academic flow" | **First.** Biggest leverage. |
| Stage 2: Data readiness pre-flight | **4 hours** | Medium — saves wasted mining runs (~$5–20 LLM tokens each) | **Second.** Cheap, immediate cost saver. |
| Stage 5: Risk decomposition (Fama-French) | **1–2 days** | High for honest alpha estimation | **Third.** Reveals if mined factors are pure style tilts (sector, size, value). |
| Stage 9: Live decay monitor | 2–3 days | Only valuable AFTER live deployment exists | **Defer** — gated by QC Phase 11/12 |
| Stage 10: Knowledge persistence + feedback loop | 1–2 days | High long-term, low immediate | **Defer** — needs critical mass of runs first |

---

## Recommended build sequence

### Step 1 — Minimal QuantaResearch (stages 0 + 1)

`arxiv_crawler.py` + `formalize_hypothesis.py` + integration that POSTs
to QA's `/api/v1/mining/start`. ~1–2 days.

**Outputs**: every morning, a queue of 5–10 candidate hypotheses ranked
by novelty + data feasibility. User reviews, approves, mining kicks off.

### Step 2 — Stage 2 (data readiness)

Small validator that checks: do we have the tickers? do we have the
features? does the test_end exceed our calendar? Auto-rejects infeasible
hypotheses before they hit QA. ~4 hours.

**Outputs**: `ideas_ready/` only contains hypotheses that QA can actually
test. No more wasted runs on missing $vwap, etc.

### Step 3 — Stage 5 (risk decomposition)

Once a QA bundle exists, regress its daily predictions against
Fama-French factors (Mkt-Rf, SMB, HML, MOM, RMW, CMA). The "true alpha"
is the regression intercept (residual return). Cheap with statsmodels.
~1 day.

**Outputs**: per-bundle `risk_decomp.json` saying "this factor's
'alpha' is 80% explained by SMB + MOM" or "this factor's residual
alpha is 0.3% annualized after FF5 — real edge."

### Step 4 — Defer stages 9 + 10

They need accumulated runs + live deployment first. Build when:
- 9: QC Phase 11 (paper trading) actually runs — i.e., we have a live
  strategy to monitor
- 10: We have ~50+ QA runs and need an organized memory of "what worked
  / what didn't" beyond the raw findings repo

---

## Human oversight design (decide before building)

The temptation with auto-research is to build a giant pipeline and let
it run unattended. **That's how you produce many bad factors fast.**
Real quant teams have a *lot* of human review at stages 1, 5, 10. Three
oversight modes worth picking between:

| Mode | Pattern | Trade-off |
|---|---|---|
| **Human-in-loop at every transition** | Each stage emits a queue. User approves before next stage runs. | Slow but safest. Recommended early. |
| **Auto-flow with halts on red flags** | Runs end-to-end automatically but pauses if: (a) data-readiness fails, (b) factor doesn't pass walk-forward, (c) risk decomp shows pure beta. User reviews halted runs only. | Good middle ground once we trust each stage. |
| **Full auto with daily summary** | Pipeline runs end-to-end, daily summary email/dashboard of what was attempted + what passed gates. | Lowest oversight; risk of bad factors slipping through to live trading. Avoid until very mature. |

**Recommended**: start with mode 1 (human-in-loop), graduate to mode 2
once stages 0–5 each demonstrate they make sensible decisions on
several dozen ideas, never go to mode 3.

---

## Honest scope notes

- **This is a large project.** A real-quant-process replica is months
  of work, not weeks. The plan above breaks it into ~5 person-days of
  high-leverage work (stages 0, 1, 2, 5) + open-ended ongoing work for
  stages 9, 10. Don't try to build it all in one go.
- **Quality > quantity for ideas.** A daily flow of 100 mediocre
  hypotheses is worse than a weekly flow of 5 well-formalized ones.
  The LLM filter at stage 1 is what determines this — invest in the
  prompt.
- **Risk decomp is more valuable than walk-forward in practice.** If a
  factor is just MOM exposure, walk-forward will say "yes it works"
  because MOM works. Risk decomp says "no, this is just MOM rebadged."
  Build stage 5 before getting fancy with stage 4.
- **Don't auto-deploy to live.** Even with a good pipeline, the gap
  between "passes our 5 gates" and "real money OOS" is large. Keep
  stages 8/9 manual until you've verified ≥3 strategies survive 6+
  months of paper trading.

---

## Cross-references

- QA's existing roadmap: [roadmap.md](roadmap.md)
- QA bundle format (what stage 5 will consume): [phase_5_6_and_quantconnect.md](phase_5_6_and_quantconnect.md)
- Walk-forward sketch (stage 4): [walk_forward_validation.md](walk_forward_validation.md)
- QC strategy mining (stage 6): [QC's roadmap](../../QuantaQC/docs/roadmap.md)
- QC integration (stage 6 ←→ QA bundle): [qc_multi_strategy_architecture.md](qc_multi_strategy_architecture.md), [QC phase_11](../../QuantaQC/docs/phase_11_qa_integration.md)
- Auto-publish (partial stage 10): [phase_4_auto_publish.md](phase_4_auto_publish.md)

---

## Open decisions before any code

1. Sibling repo `QuantaResearch` or fold into QA's existing repo as a `quantaresearch/` package?
   - **Recommend separate repo** — keeps QA scoped to factor mining; lets QuantaResearch evolve independently and feed multiple downstream consumers (not just QA).
2. Where do raw ideas live before formalization?
   - **Recommend** local JSON queue files (gitignored), not a database. Move to SQLite if scale demands.
3. How aggressive is the de-dup against QuantaAlphaFindings?
   - Day 1: by hypothesis text similarity (LLM judge).
   - Later: also by factor expression (qlib AST equivalence after formalization).
4. Schedule for daily fetch?
   - Cron / Windows Task Scheduler hitting `scripts/daily_fetch.py` at, say, 06:00. Outputs to a queue file the user reviews.
