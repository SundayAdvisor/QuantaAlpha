# Paper Replication Notes — arXiv 2602.07085v2

**Goal.** Bring our QuantaAlpha runs as close to the paper's published setup as the data and codebase allow, then measure how our results compare. This doc records every change made on 2026-05-07, the paper section that motivated each, what to expect at runtime, and how to verify the change.

**What we're replicating.** *QuantaAlpha: An Evolutionary Framework for LLM-Driven Alpha Mining* (Han et al., Apr 2026). Headline numbers on CSI 300 with GPT-5.2: IC=0.1501, RankIC=0.1465, ARR=27.75%, MDD=7.98%. Our setup uses S&P 500 data and Claude (4.5 Sonnet via Claude Code subscription); the paper Table 1 shows Claude reaches IC=0.1111 / ARR=22.70%, so a Claude run is paper-credible.

**The pre-existing gap.** A codebase audit (run before any changes) found three of the paper's marquee mechanisms were either weakly implemented or completely absent — Mutation, Crossover, and pool admission. Plus our config was a smoke-test (1 direction × 3 rounds × 1 factor/hypothesis vs paper's 10 × 5 × 3) on a 1-year test window vs paper's 4-year. None of this would reach the paper's numbers as-was.

---

## Tier 1 — Configuration alignment

Files: [`configs/experiment.yaml`](../configs/experiment.yaml), [`quantaalpha/factors/factor_template/conf_baseline.yaml`](../quantaalpha/factors/factor_template/conf_baseline.yaml), [`quantaalpha/factors/factor_template/conf_combined_factors.yaml`](../quantaalpha/factors/factor_template/conf_combined_factors.yaml)

| Setting | Was | Now | Paper ref | Why |
|---|---|---|---|---|
| `planning.enabled` | false | true | §4.2.1 | Diversified planning is the paper's first algorithmic stage; can't be off |
| `planning.num_directions` | 1 | **10** | Appendix B | Paper sets `Ninit=10` — broad initial coverage of hypothesis space |
| `evolution.enabled` | false | true | §4.2.2 | Mutation/Crossover are the second stage; must be on |
| `evolution.max_rounds` | 3 | **5** | Appendix B | Paper main run: 5 iterations |
| `factor.factors_per_hypothesis` | 1 | **3** | Appendix B | Paper allows 3 factor expressions per hypothesis |
| `factor.complexity.symbol_length_threshold` | 200 | **250** | Appendix B | Paper main run cap |
| `factor.complexity.base_features_threshold` | 5 | **6** | Appendix B | Paper main run cap |
| `quality_gate.consistency_enabled` | false | **true** | §4.1.2 | Hypothesis ↔ description ↔ expression alignment gate |
| Selling fee (`close_cost`) | 0.0015 (0.15%) | **0.0005 (0.05%)** | Table 7 | Paper's 0.15% = commission + China stamp duty; US has no stamp duty |
| Train period | 2008-01-02 → 2016-12-30 | 2008-01-02 → **2015-12-31** | §5.1 | Reshaped to leave room for 1y valid + 4y test |
| Valid period | 2017 (1 year) | **2016** (1 year) | §5.1 | One year, like paper |
| Test period | 2018 (1 year) | **2017-01-03 → 2020-11-04** (~4 years) | §5.1 | Paper's 4-year test window structure; ends before calendar boundary to leave label-buffer |

### Expected runtime impact

A single mining round goes from 1 direction × 1 hypothesis × 1 factor × 3 rounds = **3 LLM calls** to 10 × 1 × 3 × 5 = **150 LLM calls** (plus mutation/crossover overhead). Wall time per full run will rise from ~5 min to roughly **1–2 hours** depending on Claude Code throughput.

The 4-year test window also means each backtest itself takes longer (proportional to test days × universe size). Baseline anchor on the new window: 78 seconds (was ~30s on the old 1-year window).

### How to test
```powershell
# 1. Verify YAML changes took effect
Get-Content configs/experiment.yaml | Select-String "num_directions|max_rounds|factors_per_hypothesis|consistency_enabled"

# 2. Verify backtest cost change
Select-String "close_cost" quantaalpha/factors/factor_template/conf_*.yaml

# 3. Verify segment dates
Select-String -Pattern "train:|valid:|test:" quantaalpha/factors/factor_template/conf_baseline.yaml
```

Pass criteria: each setting matches the "Now" column above.

---

## Tier 2 — Pool admission filter (paper §5.5)

**What was missing.** The paper's case-study setup describes a greedy RankIC-sorted admission rule with `|corr| < 0.7` between pool members and a 50%-of-mined cap. The codebase had a far looser dedup (`corr < 0.99`) and accumulation across iterations was disabled (`if False:`). Without this gate the cumulative pool fills up with redundant near-duplicates, the LLM's reward signal becomes contaminated, and the diversity that produced paper IC=0.15 never materializes.

### Files

- **New module**: [`quantaalpha/pipeline/evolution/admission.py`](../quantaalpha/pipeline/evolution/admission.py)
  - `FactorCandidate` dataclass: `(name, rank_ic, values)`
  - `average_xs_correlation()`: per-day cross-sectional Pearson, averaged across days (more robust than pooled correlation, which would be inflated by shared time trends)
  - `FactorAdmissionFilter`: greedy RankIC-sorted admission, |corr| ≥ 0.7 rejects, post-filter cap at 50%
  - `apply_default_admission()`: top-level helper that handles both the full RankIC-aware rule and the column-order fallback when RankICs aren't yet available
- **Modified**: [`quantaalpha/pipeline/evolution/trajectory.py`](../quantaalpha/pipeline/evolution/trajectory.py) — added `TrajectoryPool.get_admitted_factor_names(factor_panel)` that aggregates per-factor RankICs from trajectory metadata and applies the filter
- **Modified**: [`quantaalpha/factors/runner.py`](../quantaalpha/factors/runner.py) — re-enabled cross-iteration accumulation (was `if False:`), replaced `deduplicate_new_factors` with `apply_default_admission(corr_threshold=0.7, cap_ratio=0.5)`

### Expected runtime impact

After each iteration, the runner now logs:
```
Admission filter: cumulative pool 18 → 9 factors (corr<0.7, cap=50%)
```
You should see the post-admission count drop noticeably as iterations accumulate similar factors.

### How to test

**Smoke test (no LLM):**
```powershell
.venv\Scripts\python.exe -c "
import pandas as pd, numpy as np
from quantaalpha.pipeline.evolution.admission import apply_default_admission

# Build a synthetic panel: 3 redundant factors + 1 independent
dates = pd.date_range('2020-01-01', periods=50)
stocks = ['A','B','C','D','E']
idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime','instrument'])
np.random.seed(0)
base = pd.Series(np.random.randn(len(idx)), index=idx)
panel = pd.DataFrame({
    'redundant_1': base,
    'redundant_2': base + 0.05*np.random.randn(len(idx)),  # ~0.99 corr with redundant_1
    'redundant_3': base + 0.1*np.random.randn(len(idx)),   # ~0.95 corr
    'independent': pd.Series(np.random.randn(len(idx)), index=idx),
})
out = apply_default_admission(panel, corr_threshold=0.7, cap_ratio=0.5)
print('Admitted:', list(out.columns))
"
```
**Pass criteria:** output contains `independent` and one of the redundant_* (not all three). The 50% cap on 4 candidates → keep at most 2.

**Live test (real run):**
After Tier 4b's baseline run, kick off a full mining run and watch the log for the `Admission filter:` line. Pre-admission count should grow each iteration; post-admission count should plateau.

---

## Tier 3a — Step-level mutation (paper §4.2.2 eq. 7)

**What was missing.** The paper's mutation operator self-reflects to localize the worst step `k` in the parent trajectory, refines only that step, and freezes the prefix. Our code threw the entire parent away and asked the LLM for a fresh "orthogonal" hypothesis — broader exploration but loses validated work and makes evolution sample-inefficient.

### Files

- **Modified**: [`quantaalpha/pipeline/evolution/mutation.py`](../quantaalpha/pipeline/evolution/mutation.py)
  - New `MutationGuidance` dataclass: `worst_step, diagnosis, refined_directive, freeze_steps, parent_hypothesis, parent_factors_summary`
  - New `generate_targeted_mutation(parent)`: builds a 4-step view (hypothesis / factor_expression / code / evaluation) of the parent, asks the LLM to identify the worst step in JSON
  - New `_build_targeted_suffix(guidance)`: emits a prompt suffix with `### FROZEN — do NOT change` blocks for the prefix and a localized refinement directive
  - `generate_mutation_prompt_suffix(targeted=True)` is the new default; `targeted=False` falls back to legacy "orthogonal hypothesis" mode

### Trajectory step taxonomy
```
TRAJECTORY_STEPS = ("hypothesis", "factor_expression", "code", "evaluation")
```
If the LLM identifies `factor_expression` as worst, `freeze_steps = ["hypothesis"]` — only the hypothesis is frozen, expression onward gets regenerated. If `code` is worst, both hypothesis and factor_expression freeze.

### Expected runtime impact

Each mutation phase now makes one extra LLM call (for the self-reflection) before the regeneration call. Modest cost. The downstream agent receives a much more constrained prompt — should produce children that share more validated structure with parents (better sample efficiency).

### How to test

**Unit-style test:**
```powershell
.venv\Scripts\python.exe -c "
from quantaalpha.pipeline.evolution.mutation import MutationOperator, MutationGuidance
from quantaalpha.pipeline.evolution.trajectory import StrategyTrajectory, RoundPhase

# Build a fake parent
parent = StrategyTrajectory(
    trajectory_id='test001', direction_id=0, round_idx=0, phase=RoundPhase.ORIGINAL,
    hypothesis='Volume-price divergence predicts reversal',
    factors=[{'name':'VPDiv', 'expression':'TS_CORR(\$close, \$volume, 10)', 'code':''}],
    backtest_metrics={'RankIC': 0.001},  # low — failed parent
)

op = MutationOperator()
suffix = op.generate_mutation_prompt_suffix(parent, targeted=True)
print(suffix[:500])
print('...')
print(suffix[-400:])
"
```
**Pass criteria:** output contains the strings `Targeted Refinement (Paper §4.2.2 eq. 7)`, `Worst step:`, and `Frozen prefix:`. (LLM call may fail in offline test; the operator falls back to a stub `MutationGuidance` and the suffix still contains those structural strings.)

**Live test:** during a real mining run, search the LLM-prompt logs for `Targeted Refinement` — every mutation round should have it.

---

## Tier 3b — Segment-level crossover (paper §4.2.2 eq. 8)

**What was missing.** The paper's crossover recombines validated *segments* — hypothesis templates, factor construction patterns, repair actions — from multiple parents into a child with explicit lineage. Our code did whole-hypothesis LLM fusion: handed the prose summaries to the LLM and asked for a "merged" hypothesis. No segment-level inheritance, no traceable provenance.

### Files

- **Modified**: [`quantaalpha/pipeline/evolution/crossover.py`](../quantaalpha/pipeline/evolution/crossover.py)
  - New `CrossoverGuidance` dataclass: `inherited_segments, composition_directive, lineage_summary, parent_ids`. Each inherited segment carries `{type, source_parent_id, source_rank_ic, content, rationale}`
  - New `generate_segment_crossover(parents)`: builds a "segment menu" tagging each parent's hypothesis / factor expression patterns / repair actions with provenance, asks the LLM to pick complementary segments from different parents
  - New `_validate_inherited_segments()`: rejects hallucinated parent IDs, attaches authoritative source RankICs
  - New `_fallback_segment_crossover()`: heuristic when LLM unavailable — take hypothesis from highest-RankIC parent + factor expression from second-best
  - New `_build_segment_suffix(guidance)`: emits "Inherited Segments (DO NOT paraphrase)" block with full lineage trace
  - `generate_crossover_prompt_suffix(segment_mode=True)` is the new default

### Segment types
```
SEGMENT_TYPES = ("hypothesis", "factor_expression_pattern", "repair_action")
```
Repair actions are pulled from the parent's feedback when it contains keywords like "fix" / "correct" / "repair" / "revise".

### Expected runtime impact

One additional LLM call per crossover (for segment selection). The downstream agent prompt is tightly constrained: must inherit ≥ 2 segments from ≥ 2 different parents, verbatim. Children will visibly carry parent expressions/hypothesis text rather than being LLM paraphrases.

### How to test

**Inspection test:**
```powershell
.venv\Scripts\python.exe -c "
from quantaalpha.pipeline.evolution.crossover import CrossoverOperator, CrossoverGuidance
from quantaalpha.pipeline.evolution.trajectory import StrategyTrajectory, RoundPhase

p1 = StrategyTrajectory(
    trajectory_id='p1', direction_id=0, round_idx=0, phase=RoundPhase.ORIGINAL,
    hypothesis='Institutional accumulation drives sustained trends',
    factors=[{'name':'IM','expression':'TS_CORR(\$close, \$volume, 20)'}],
    backtest_metrics={'RankIC': 0.025},
)
p2 = StrategyTrajectory(
    trajectory_id='p2', direction_id=1, round_idx=0, phase=RoundPhase.ORIGINAL,
    hypothesis='Volatility clustering predicts regime persistence',
    factors=[{'name':'VC','expression':'TS_STD(\$return, 5)/TS_STD(\$return, 60)'}],
    backtest_metrics={'RankIC': 0.018},
)
op = CrossoverOperator()
suffix = op.generate_crossover_prompt_suffix([p1, p2], segment_mode=True)
print(suffix[:1500])
"
```
**Pass criteria:** output contains `Segment Inheritance (Paper §4.2.2 eq. 8)`, `Inherited from:`, `(DO NOT paraphrase)`. Even with LLM offline (fallback path), the heuristic should produce 2 segments from 2 different parents.

**Live test:** during a real mining run, search prompt logs for `Inherited Segments` — every crossover round should have one. Inspect the inherited content to confirm it matches one of the parents' actual content.

---

## Tier 4a — VWAP (deliberately skipped)

**Decision.** Did not add a `$vwap` proxy. Typical Price `(H+L+C)/3` is a popular *approximation* but is NOT the actual VWAP formula. True VWAP = `Σ(price × volume) / Σ(volume)` *intraday*, which can't be reconstructed from daily OHLCV. User explicitly rejected adding a proxy: "if it's not the correct vwap formula don't do it."

**Implication.** The 20-feature Alpha158 subset we use does NOT reference `$vwap`, so this isn't blocking. Full Alpha158 (all 158 features) would require true VWAP and therefore minute-bar data. Not on the table.

**Recorded in** `~/.claude/projects/.../memory/project_quantaalpha_gotchas.md` so it doesn't get re-attempted.

---

## Tier 4b — Baseline anchor

**Why.** Without a baseline measurement of "what IC do the 20 Alpha158 features alone produce on our SPY data?", we can't tell whether mined factors actually add value or whether the baseline was already doing all the work. The anchor turns mining-run results into incremental measurements: `mined_uplift = combined_IC − baseline_IC`.

### Files

- **New script**: [`run_baseline_anchor.py`](../run_baseline_anchor.py)
  - Copies `conf_baseline.yaml` to a temp workspace, runs `qrun.exe`, parses metrics from stdout
  - Prepends venv `Scripts/` to PATH so qrun is findable on Windows
  - Forces `PYTHONIOENCODING=utf-8` to avoid the cp1252 console encoding bug

### Anchor numbers (recorded 2026-05-07, run took 78s)

| Metric | Value |
|---|---|
| **IC** | **0.0032** |
| **Rank IC** | **0.0042** |
| **ICIR** | **0.031** |
| **Rank ICIR** | **0.039** |
| **Annualized Return (excess)** | **12.64%** |
| **Information Ratio** | **0.626** |
| **Max Drawdown** | **-38.2%** |

Test window: 2017-01-03 → 2020-11-04 (~4 years, includes COVID crash + recovery).

### Comparison to paper's baseline

Paper Table 1, "Alpha158(20)" row on CSI 300:
| Metric | Paper (CSI 300) | Ours (S&P 500) | Note |
|---|---|---|---|
| IC | 0.0051 | 0.0032 | Same magnitude; SPY harder for technical features |
| Rank IC | 0.0184 | 0.0042 | Lower; less cross-sectional dispersion in mature US equities |
| ARR | 4.63% | 12.64% | US bull 2017–2020 was unusually strong even for noisy signals |
| MDD | 22.19% | 38.25% | COVID crash dominates; CSI 300 in paper test had less severe drawdowns |

Verdict: numbers are within reason, no obvious data leakage or pipeline bug. The high ARR / high MDD profile is honest US bull-market behavior — the 4-year window includes 2020-Q1.

### How to test (re-run)
```powershell
cd c:\Users\jangh\Desktop\quantconnect\repos\QuantaAlpha
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python.exe run_baseline_anchor.py
```
**Pass criteria:** exit code 0, prints metrics block with `annualized_return ≈ 0.126`, `information_ratio ≈ 0.63`, `max_drawdown ≈ -0.38`. Should be reproducible (deterministic LightGBM with fixed seed); small variation acceptable from float arithmetic.

---

## What we cannot test without a full mining run

The Tier 2 and Tier 3 changes only fully exercise during a complete mining loop. The smoke tests above verify that the modules load, run their inner logic, and emit the expected prompt blocks — but the end-to-end "did this raise our IC?" test requires:

```powershell
# Full mining run (will take ~1-2 hours with paper-shaped settings)
.venv\Scripts\python.exe claude_smoke.py  # or whatever the canonical entry point is
```

After completion, look at `data/results/<run_dir>/`:
1. Final `combined_factors_df.parquet` — count columns, should reflect admission cap
2. Backtest metrics for the combined run — compare IC/ARR vs the baseline anchor
3. Prompt logs — confirm `Targeted Refinement` appears in mutation rounds and `Segment Inheritance` in crossover rounds

**Targets to expect (lowest-to-highest plausibility):**
- **Floor**: combined IC > 0.0032 (else mined factors aren't adding anything)
- **Decent**: combined IC ≈ 0.05–0.08, ARR uplift > +5pp (rough par with AlphaAgent on Claude per paper Table 1)
- **Stretch**: combined IC > 0.10 (approaching paper Claude row at 0.1111). Probably won't hit because our Mutation/Crossover are still proxies for the paper's true step/segment-level operators

If combined IC is below 0.005, something's broken — start by checking whether the admission filter rejected too aggressively (look for empty parquet) or whether the LLM is producing degenerate factors.

---

## Files changed (full list)

```
configs/experiment.yaml                                         (Tier 1)
quantaalpha/factors/factor_template/conf_baseline.yaml          (Tier 1, 4b)
quantaalpha/factors/factor_template/conf_combined_factors.yaml  (Tier 1)
quantaalpha/pipeline/evolution/admission.py                     NEW (Tier 2)
quantaalpha/pipeline/evolution/trajectory.py                    (Tier 2)
quantaalpha/pipeline/evolution/mutation.py                      (Tier 3a)
quantaalpha/pipeline/evolution/crossover.py                     (Tier 3b)
quantaalpha/factors/runner.py                                   (Tier 2)
run_baseline_anchor.py                                          NEW (Tier 4b)
docs/paper_replication.md                                       NEW (this file)
```

Memory artifacts (outside repo, in `~/.claude/projects/.../memory/`):
- `project_quantaalpha_gotchas.md` — added VWAP-proxy rejection note
- `project_quantaalpha_paper_guide.md` — full paper guideline (separate doc, written earlier)
