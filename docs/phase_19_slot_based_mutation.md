# Phase 19 — Slot-based mutation (EvoControl-inspired)

Status: 📋 sketch — buildable after Phase 18. ~3-5 days.

Adopt EvoControl's (arXiv 2601.07348) **slot-based mutation** pattern to
make QA's factor evolution loop more efficient. Instead of having the LLM
rewrite the entire factor expression on every mutation, identify the
specific slots in the expression that are most likely the cause of poor
performance, and mutate ONLY those. Tighter search, faster learning.

## The problem today

QA's mutation step prompts the LLM to "regenerate the factor with
improvements." The LLM tends to rewrite everything — keeping the spirit
but changing dozens of subtle details. The result: each mutation is a
small rebuild rather than a targeted fix. Across 5 rounds × 10
directions × 3 factors per hypothesis, this means a lot of wasted LLM
search.

EvoControl reports ~80% fewer iterations to reach equivalent quality
when mutation is slot-targeted vs token-level. Our setup likely sees
30-50% improvement (factor expressions are smaller than full code, so
the gain is less dramatic than EvoControl's code-optimization domain).

## The EvoControl pattern

Identify explicit "slots" in the artifact, mutate only one slot per
mutation step.

For QA factor expressions:

```
ZSCORE(  TS_PCTCHANGE(  $close , 5  )  )
       └─ smoothing op   └─ feature  └─ window   └─ outer wrapper
       (slot type:       (slot type: (slot type:  (slot type:
         transform)        feature)    window)     normalization)
```

Mutation prompt becomes: *"Keep everything else fixed; mutate only the
window slot."* → produces (5 → 10), (5 → 20), (5 → 60). Three new
candidates, all isolating the effect of window length.

## Slot taxonomy for QA

Five slot types covering most of qlib's operator library:

| Slot type | What it controls | Examples |
|---|---|---|
| **window** | Lookback length in time-series ops | the `5` in `TS_MEAN($close, 5)`; the `20` in `TS_STD($return, 20)` |
| **feature** | Which raw qlib feature is operand | `$close`, `$open`, `$high`, `$low`, `$volume`, `$return`, `$factor` |
| **transform** | Time-series transformation op | `TS_MEAN`, `TS_STD`, `TS_RANK`, `TS_CORR`, `TS_PCTCHANGE`, `DELTA`, `DELAY` |
| **normalization** | Cross-sectional or self-normalization wrapper | `ZSCORE`, `RANK`, `SCALE`, identity (none) |
| **binary_op** | How two sub-expressions combine | `+`, `-`, `*`, `/`, `IF`, `WHERE` |

## Mutation strategies (which slot to target?)

EvoControl's contribution isn't just slot definition — it's *which slot to
mutate when*. Three rules:

### Rule 1 — Lowest-confidence slot first

After a backtest produces poor metrics, attribute the failure to the
slot most likely responsible:

| Failure pattern | Likely culprit slot |
|---|---|
| RankIC near zero, IR near zero | `feature` (wrong signal source) |
| RankIC positive, IR negative ("regime-fit") | `normalization` (factor predicts ranks but trades poorly) |
| RankIC oscillates over time | `window` (wrong horizon) |
| Factor lookup-table-like (memorizes) | `transform` (overly nonlinear) |
| Massive drawdown spikes | `binary_op` (compounding effects) |

LLM is given the failure pattern + which slot to mutate. Rest is held fixed.

### Rule 2 — Diversified initialization

In round 0, generate factors that span DIFFERENT slot configurations. If
3 factors are generated per hypothesis, ensure their slot signatures
differ:

```
Factor A:  feature=$close,  transform=TS_PCTCHANGE,  normalization=ZSCORE,   window=5
Factor B:  feature=$volume, transform=TS_RANK,       normalization=identity, window=20
Factor C:  feature=$return, transform=TS_CORR,       normalization=RANK,     window=60
```

Forces a wide initial coverage instead of three close variants of the same idea.

### Rule 3 — Combinatorial sweep on promising slots

When a factor passes admission, automatically generate combinatorial
sweeps on *one* slot at a time:

- Best factor passes: `RANK(TS_RANK(TS_SUM($return, 5), 20))`
- Auto-sweep window slot: try (5,5), (10,5), (5,10), (20,5), (5,20), (10,10), (20,20)
- Best of sweep wins; replaces parent in pool

This is cheap — sweeps don't need LLM calls, just qlib backtests at
each parameter combo. ~30 sec per backtest × 7 sweep variants = 3.5 min
per accepted factor.

## Implementation

### Step 19.1 — Slot extraction (~1 day)

Parse qlib factor expressions into ASTs and tag each node with its
slot type. We already have AST parsing in
`quantaalpha/factors/coder/expr_parser.py`; extend it:

```python
# quantaalpha/factors/mutation/slots.py
@dataclass
class SlotInstance:
    slot_type: SlotType
    node_path: list[int]    # AST path to this slot
    current_value: str       # e.g. "5", "$close", "TS_MEAN"
    valid_alternatives: list[str]  # what could replace it

def extract_slots(expression: str) -> list[SlotInstance]:
    """Walk the AST, tag slots, return all mutable positions."""
```

Validation: for the existing factor `RANK(TS_RANK(TS_SUM($return, 5), 20))`,
extract should return:
- 1 normalization slot (`RANK`)
- 2 transform slots (`TS_RANK`, `TS_SUM`)
- 1 feature slot (`$return`)
- 2 window slots (`5`, `20`)

### Step 19.2 — Slot-targeted mutation prompt (~half day)

New prompt template that includes the slot taxonomy + the target slot:

```yaml
# quantaalpha/pipeline/prompts/slot_mutation_prompts.yaml
mutation_prompt:
  system: |
    You are mutating a factor expression. Mutate ONLY the targeted slot.
    Keep all other slots IDENTICAL. The targeted slot type is "{slot_type}"
    with current value "{current_value}". Valid alternatives are: {alternatives}.

    Original expression:    {original}
    Target slot:           {slot_path} (type: {slot_type})
    Current value:         {current_value}
    Recent failure pattern: {feedback_summary}

    Output STRICT JSON:
    {{
      "mutation_rationale": "<one sentence>",
      "new_value": "<replacement for the slot>",
      "new_expression": "<full expression with the slot replaced>"
    }}
```

### Step 19.3 — Failure attribution (~1 day)

After each backtest, classify the failure pattern (RankIC behavior,
IR behavior, drawdown shape) and map to a target slot. LLM call with
the metrics, returns slot_type to mutate next.

```python
# quantaalpha/factors/mutation/attribute.py
def attribute_failure_to_slot(
    metrics: dict, slot_instances: list[SlotInstance]
) -> SlotInstance:
    """Pick the slot most likely responsible for the failure pattern."""
    ...
```

### Step 19.4 — Diversified-init enforcement (~half day)

For round 0, after the LLM proposes N factors per hypothesis, check
their slot signatures. If two have the same signature, ask the LLM to
regenerate one with a forced-different slot.

### Step 19.5 — Combinatorial sweep on promotion (~1 day)

When a factor passes admission gates (Phase 13), trigger a window-slot
sweep. New CLI:

```bash
scripts/sweep_factor.py --factor-id <id> --slot window --grid 5,10,20,60
```

Runs each variant through qlib backtest, picks the best, replaces parent
in the pool. Tracks sweep history in the factor card (Phase 18).

### Step 19.6 — Validation (~half day)

Run two mining sessions:
- Control: token-level mutation (current behavior)
- Treatment: slot-based mutation

Compare:
- Iterations to reach the first promoted factor
- Pool diversity at iteration 5 (mechanism entropy + AST-similarity histogram)
- Final pool quality (best RankICIR + median RankICIR)

EvoControl claims 80% fewer iterations; in our domain probably 30-50%.
Even 30% means full paper-aligned runs go from 8 hr → 5 hr.

Total: 3-5 days for the full set; can ship Step 19.1-19.4 in ~2 days for an MVP.

## Acceptance

- `extract_slots()` correctly identifies slots in 10 hand-curated factor
  expressions (test fixture)
- A mutation request targeting slot type "window" produces an expression
  identical to the parent except for one window argument
- Diversified-init enforcer guarantees no two round-0 factors per
  hypothesis share an identical slot signature
- Combinatorial sweep on a promoted factor produces N variants and
  picks the best by RankICIR
- A/B comparison shows ≥20% iteration reduction or ≥10% pool diversity
  improvement vs current mutation

## Caveats

- **Slot taxonomy may need extension.** Some factors use `IF`/`WHERE`
  conditional structures; some use compound features like `$close - $open`.
  Start with the 5 slot types above; add more as they appear.
- **AST parsing brittle on hand-rolled expressions.** Some LLM-generated
  factors don't parse cleanly (we've seen "Expression has no nodes"
  warnings already). Slot extraction must gracefully fail on
  unparseable expressions and fall back to token-level mutation.
- **Don't over-constrain.** If slot mutation is too rigid, the LLM
  loses the ability to discover novel structural changes. Keep an
  occasional "free-form mutation" round (every 3rd round?) where the
  LLM is unconstrained.

## File-level deliverables

```
quantaalpha/factors/mutation/
  __init__.py
  slots.py                 # SlotInstance, extract_slots()
  attribute.py             # failure → slot type mapping
  combinatorial.py         # sweep helpers
  init_diversity.py        # round-0 diversified-init enforcer

quantaalpha/pipeline/prompts/
  slot_mutation_prompts.yaml  # new prompt template

scripts/
  sweep_factor.py          # CLI for combinatorial sweep on a promoted factor

quantaalpha/factors/runner.py
  - call extract_slots() + attribute_failure_to_slot() inside the
    mutation phase

docs/
  phase_19_slot_based_mutation.md   # this file
  phase_19_validation.md            # write after A/B comparison
```

## Cross-references

- Source paper: EvoControl, arXiv 2601.07348
- [phase_18_factor_memory_service.md](phase_18_factor_memory_service.md) —
  parallel "stop the LLM rediscovering failures" line of attack;
  complementary, not redundant
- [phase_13_admission_gate_upgrades.md](phase_13_admission_gate_upgrades.md)
  §"AST-similarity dedup" — uses the same AST infrastructure this phase
  builds; sequence: 13 → 19 (the dedup gate is a simpler use of AST
  parsing than slot extraction)
- AlphaAgent (arXiv 2502.16789) — also uses AST regularization, complementary
