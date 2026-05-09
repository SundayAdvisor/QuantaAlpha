# Phase 4 — Auto-publish to QuantaAlphaFindings

Status: ✅ shipped 2026-05-09

After every successful mining run, the top gate-passing factors get
auto-pushed to a sibling git repo as a public, browsable factor catalog.

## What shipped

### Publisher script

[scripts/publish_findings.py](../scripts/publish_findings.py) reads a
mining run's `trajectory_pool.json`, applies hard gates, and writes the
top-N as committed-ready files into the findings repo.

**Default gates** (lines 46–51 of the publisher):
- `min_rank_icir`: 0.05
- `min_information_ratio`: 0.0
- `max_drawdown_cutoff`: -0.40 (drawdown shallower than -40%)
- `top_n`: 5

**Output layout** (per factor):
```
factors/<slug>/
  factor.json       # canonical machine-readable record:
                    #   - factors[] with name + expression + description + full Python code
                    #   - hypothesis (the economic rationale text)
                    #   - hypothesis_details (LLM's concise reason / observation /
                    #     justification / domain knowledge)
                    #   - feedback + feedback_details (post-backtest analysis +
                    #     decision + new_hypothesis going forward)
                    #   - parent_ids + parents[] (DENORMALIZED — for each parent
                    #     id, includes its hypothesis, primary expression, metrics)
                    #   - backtest_metrics (RankICIR / IR / ARR / MaxDD)
                    #   - phase / round_idx / direction_id / created_at
  spec.md           # human-readable: hypothesis, full LLM rationale (Why /
                    # Observation / Justification / Domain knowledge), each
                    # factor expression in code blocks with description, what
                    # we learned post-backtest, lineage (with parent expressions
                    # inline). Designed so a downstream LLM (QC's QAAlphaModel,
                    # paper trial) can use the factor without further lookup.
  results.md        # backtest metrics table
  provenance.json   # source run_id, trajectory_id, slug, lineage
```

**What this means for QC integration (phase 11)**: a QC strategy proposing
LLM only needs to read `factor.json` for one factor and gets:
- the qlib expression to compute the factor
- the actual Python implementation if Lean's expression evaluator falls short
- the hypothesis + LLM rationale → context for why/when this factor works
- the parents → lineage so the LLM understands what mutations led here
- the post-backtest decision → "this passed because of X but watch out for Y"

### Backend auto-trigger

Mining task completion calls `_auto_publish_qa_run(run_id)` which
fire-and-forget runs the publisher as a subprocess. Default-on if the
findings repo exists; opt out with `QA_FINDINGS_AUTO_PUBLISH=0` in `.env`.

The findings repo is auto-detected at:
1. `$QA_FINDINGS_REPO` env var
2. `<repos>/QuantaAlphaFindings/` (CamelCase, current convention)
3. `<repos>/quantaalpha-findings/` (legacy hyphen-lowercase)

Files: [_resolve_findings_repo_qa](../frontend-v2/backend/app.py), endpoint
`GET /api/v1/findings-config`.

### FE surfacing

Home page does not yet show "your last factor was published." Findings
state is exposed via `GET /api/v1/findings-config` (read-only):

```json
{
  "repo_path": ".../QuantaAlphaFindings",
  "repo_exists": true,
  "auto_publish_enabled": true
}
```

## Setup

```bash
# 1. Clone the (initially empty) findings repo next to QuantaAlpha
cd /path/to/quantconnect/repos
git clone https://github.com/SundayAdvisor/QuantaAlphaFindings.git

# 2. (Optional) seed a README + findings_config.json mirroring quantqc-findings
cd QuantaAlphaFindings
git commit -am "init"; git push

# 3. Verify backend detects it
curl http://localhost:8000/api/v1/findings-config
# Expect: auto_publish_enabled: true
```

## Acceptance

- Manual run of `publish_findings.py` against an existing log dir produces
  factors/ entries (ungated runs publish 0; gated ones publish ≤5)
- Auto-publish fires after a real mining task completes — verified by
  log line `_auto_publish_qa_run` appearing in backend stdout
- The QuantaAlphaFindings repo on GitHub receives commits

## Open follow-ups (not blocking)

- **Manual unpublish** — no UI to remove a factor from findings if you
  decide it was a mistake. Currently you'd `git rm` manually.
- **Findings dashboard in QA FE** — read the local clone, render a list,
  link out to GitHub. Currently you have to browse the repo on GitHub.
- **Cross-run dedup** — if two runs produce the same factor expression,
  publisher creates two slugs with overlapping metrics. Should keep the
  best-RankICIR one. Tracked separately.
