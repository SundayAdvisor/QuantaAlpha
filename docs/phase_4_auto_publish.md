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
  factor.json       # canonical record: name, expression, metrics, lineage
  spec.md           # human-readable spec: hypothesis, mechanism, params
  results.md        # backtest table: IC, RankICIR, IR, ARR, MDD by run
  provenance.json   # source run_id, trajectory_id, hashes
```

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
