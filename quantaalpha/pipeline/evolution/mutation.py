"""
Mutation operator for evolutionary trajectory refinement.

Two modes:
- `generate_mutation` (legacy): produces an orthogonal hypothesis from the
  parent — broad exploration, replaces everything.
- `generate_targeted_mutation` (paper §4.2.2 eq. 7): self-reflects to localize
  the worst step k in the trajectory, refines only that step, and signals which
  prefix steps to freeze. Targeted exploration that keeps validated work intact.

The targeted mode treats each trajectory as a sequence of decision steps:
  step 0: hypothesis
  step 1: factor expressions (symbolic form)
  step 2: code (compiled implementation)
  step 3: evaluation outcome (terminal)
The LLM identifies which step most explains the low terminal reward and emits
guidance for refining only that step while freezing earlier ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from quantaalpha.log import logger
from quantaalpha.llm.client import APIBackend
from .trajectory import StrategyTrajectory, RoundPhase


# Trajectory step taxonomy (paper §3 "Alpha Mining Trajectory")
TRAJECTORY_STEPS = ("hypothesis", "factor_expression", "code", "evaluation")


@dataclass
class MutationGuidance:
    """Structured output of self-reflection-driven mutation."""
    worst_step: str = "hypothesis"        # which step is faulty
    diagnosis: str = ""                    # why it failed
    refined_directive: str = ""            # how to fix this step
    freeze_steps: list[str] = field(default_factory=list)  # prefix to keep
    parent_hypothesis: str = ""            # echo back so downstream can reuse
    parent_factors_summary: str = ""       # echo back factor expressions if frozen
    fallback_used: bool = False


# Default prompt path
DEFAULT_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "evolution_prompts.yaml"


class MutationOperator:
    """
    Generates orthogonal (mutated) strategies from parent trajectories.
    
    The mutation process:
    1. Takes a parent trajectory's hypothesis, factors, and feedback
    2. Generates a new hypothesis that explores an orthogonal direction
    3. The new hypothesis should be fundamentally different to ensure diversity
    
    Key principles:
    - Orthogonality: New strategy should be nearly independent from parent
    - Diversity: Avoid repeating exploration paths
    - Learning: Use feedback from parent to avoid known pitfalls
    """
    
    def __init__(self, prompt_path: Optional[Path] = None):
        """
        Initialize mutation operator.
        
        Args:
            prompt_path: Path to YAML file containing prompts. 
                        If None, uses default prompt path.
        """
        self.prompt_path = prompt_path or DEFAULT_PROMPT_PATH
        self.prompts = self._load_prompts()
    
    def _load_prompts(self) -> dict[str, str]:
        """Load prompts from YAML file."""
        if self.prompt_path and self.prompt_path.exists():
            try:
                all_prompts = yaml.safe_load(self.prompt_path.read_text(encoding="utf-8")) or {}
                mutation_prompts = all_prompts.get("mutation", {})
                if mutation_prompts:
                    return mutation_prompts
            except Exception as e:
                logger.warning(f"Failed to load mutation prompts from {self.prompt_path}: {e}")
        
        # Minimal fallback prompts (English)
        logger.warning("Using minimal fallback prompts for mutation operator")
        return {
            "system": "You are a quantitative finance strategy expert. Generate orthogonal strategies.",
            "user": "Generate an orthogonal strategy based on parent: {parent_hypothesis}",
            "simple_user": "Generate orthogonal hypothesis: {parent_hypothesis}",
            "fallback_templates": [
                "Explore mean reversion characteristics",
                "Study volume-price nonlinear relationships",
                "Analyze cross-cycle trend signals",
                "Mine market microstructure liquidity features",
            ]
        }
    
    def generate_mutation(
        self,
        parent: StrategyTrajectory,
        use_detailed_prompt: bool = True
    ) -> dict[str, str]:
        """
        Generate a mutated (orthogonal) strategy from parent.
        
        Args:
            parent: The parent trajectory to mutate from
            use_detailed_prompt: Whether to use detailed prompt (returns structured output)
                               or simple prompt (returns just hypothesis text)
        
        Returns:
            Dictionary containing mutation results:
            - "new_hypothesis": The new hypothesis text
            - "exploration_direction": Direction description (if detailed)
            - "orthogonality_reason": Why this is orthogonal (if detailed)
            - "expected_characteristics": Expected characteristics (if detailed)
        """
        # Format parent information
        parent_hypothesis = parent.hypothesis or "N/A"
        
        parent_factors = ""
        if parent.factors:
            for f in parent.factors[:5]:
                name = f.get("name", "unknown")
                expr = f.get("expression", "")
                desc = f.get("description", "")
                parent_factors += f"- {name}: {expr}\n  Description: {desc}\n"
        else:
            parent_factors = "N/A"
        
        parent_metrics = ""
        if parent.backtest_metrics:
            for k, v in parent.backtest_metrics.items():
                if v is not None:
                    parent_metrics += f"- {k}: {v:.4f}\n"
        if not parent_metrics:
            parent_metrics = "N/A"
        
        parent_feedback = parent.feedback or "N/A"
        
        # Build prompt
        system_prompt = self.prompts.get("system", "")
        
        if use_detailed_prompt:
            user_prompt = self.prompts.get("user", "").format(
                parent_hypothesis=parent_hypothesis,
                parent_factors=parent_factors,
                parent_metrics=parent_metrics,
                parent_feedback=parent_feedback
            )
        else:
            user_prompt = self.prompts.get("simple_user", "").format(
                parent_hypothesis=parent_hypothesis,
                parent_factors=parent_factors
            )
        
        # Call LLM
        try:
            response = APIBackend().build_messages_and_create_chat_completion(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                json_mode=use_detailed_prompt
            )
            
            if use_detailed_prompt:
                result = self._parse_detailed_response(response)
            else:
                result = {"new_hypothesis": response.strip()}
            
            logger.info(f"Generated mutation from parent {parent.trajectory_id}")
            return result
            
        except Exception as e:
            logger.error(f"Mutation generation failed: {e}")
            # Return fallback
            return {
                "new_hypothesis": self._generate_fallback_hypothesis(parent),
                "exploration_direction": "Fallback strategy: exploring opposite direction",
                "orthogonality_reason": "Using fallback strategy due to generation failure",
                "expected_characteristics": "May produce factors negatively correlated with parent"
            }
    
    def generate_targeted_mutation(
        self, parent: StrategyTrajectory
    ) -> MutationGuidance:
        """
        Paper §4.2.2 eq. 7: self-reflect to localize the worst step k in the
        parent trajectory, refine only that step, freeze the prefix.

        Returns a MutationGuidance object with:
          - worst_step: which trajectory step is faulty
          - diagnosis: why
          - refined_directive: how to fix it
          - freeze_steps: prefix steps the downstream pipeline should NOT regenerate

        Unlike `generate_mutation` (which throws everything away and starts over),
        this method preserves validated work and surgically rewrites the failing
        component. Downstream pipeline can then condition on the frozen prefix
        when regenerating subsequent steps.
        """
        # Build trajectory step view for the LLM
        steps_summary = self._build_steps_summary(parent)
        terminal_metric = parent.get_primary_metric()
        terminal_str = f"{terminal_metric:.4f}" if terminal_metric is not None else "N/A"

        system_prompt = (
            "You are a quantitative finance expert performing post-hoc trajectory "
            "diagnosis. A factor mining trajectory consists of four steps: "
            "hypothesis → factor_expression → code → evaluation. You will be "
            "given a complete trajectory with its terminal RankIC. Your job is to "
            "identify which SINGLE step most explains the low reward and propose "
            "a targeted refinement of ONLY that step. Earlier steps will be frozen.\n\n"
            "Output STRICT JSON with keys: worst_step (one of: hypothesis, "
            "factor_expression, code), diagnosis, refined_directive."
        )
        user_prompt = (
            f"Trajectory steps:\n{steps_summary}\n\n"
            f"Terminal RankIC: {terminal_str}\n\n"
            f"Identify the worst step and describe how to refine it. Be specific."
        )

        try:
            response = APIBackend().build_messages_and_create_chat_completion(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                json_mode=True,
            )
            parsed = self._parse_targeted_response(response)
            worst = parsed.get("worst_step", "hypothesis")
            if worst not in TRAJECTORY_STEPS:
                worst = "hypothesis"

            # Freeze everything strictly BEFORE worst_step
            idx = TRAJECTORY_STEPS.index(worst)
            freeze = list(TRAJECTORY_STEPS[:idx])

            guidance = MutationGuidance(
                worst_step=worst,
                diagnosis=parsed.get("diagnosis", ""),
                refined_directive=parsed.get("refined_directive", ""),
                freeze_steps=freeze,
                parent_hypothesis=parent.hypothesis or "",
                parent_factors_summary=self._summarize_factors(parent),
            )
            logger.info(
                f"Targeted mutation from {parent.trajectory_id}: "
                f"worst_step={worst}, freezing {freeze}"
            )
            return guidance

        except Exception as e:
            logger.warning(
                f"Targeted mutation LLM call failed ({e}); falling back to "
                f"hypothesis-level rewrite"
            )
            return MutationGuidance(
                worst_step="hypothesis",
                diagnosis="Self-reflection unavailable; defaulting to hypothesis-level refinement",
                refined_directive=self._generate_fallback_hypothesis(parent),
                freeze_steps=[],
                parent_hypothesis=parent.hypothesis or "",
                fallback_used=True,
            )

    def _build_steps_summary(self, parent: StrategyTrajectory) -> str:
        """Render the parent's four steps as a labelled block for the LLM."""
        lines = []
        lines.append(f"[step 0: hypothesis]\n{parent.hypothesis or '(empty)'}")
        lines.append(f"\n[step 1: factor_expression]\n{self._summarize_factors(parent)}")
        # Code: include first factor's code if present, truncated
        code_block = "(empty)"
        if parent.factors:
            first_code = parent.factors[0].get("code", "")
            if first_code:
                code_block = first_code[:600] + ("..." if len(first_code) > 600 else "")
        lines.append(f"\n[step 2: code]\n{code_block}")
        # Evaluation
        eval_lines = []
        for k, v in (parent.backtest_metrics or {}).items():
            if v is not None:
                eval_lines.append(f"  {k}={v:.4f}")
        eval_str = "\n".join(eval_lines) if eval_lines else "(no metrics)"
        lines.append(f"\n[step 3: evaluation]\n{eval_str}")
        if parent.feedback:
            lines.append(f"\n[feedback]\n{parent.feedback[:400]}")
        return "\n".join(lines)

    def _summarize_factors(self, parent: StrategyTrajectory) -> str:
        if not parent.factors:
            return "(empty)"
        out = []
        for f in parent.factors[:5]:
            name = f.get("name", "unknown")
            expr = (f.get("expression") or "")[:200]
            out.append(f"  - {name}: {expr}")
        return "\n".join(out)

    def _parse_targeted_response(self, response: str) -> dict:
        """Parse the JSON output of the targeted-mutation LLM call."""
        import json
        import re

        text = response.strip()
        fence_match = re.search(r"```json\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Targeted-mutation response not valid JSON; using empty parse")
            return {}

    def _parse_detailed_response(self, response: str) -> dict[str, str]:
        """Parse JSON response from LLM."""
        import json
        import re
        
        # Extract JSON from response
        text = response.strip()
        
        # Try to find JSON block
        fence_match = re.search(r"```json\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1).strip()
        
        # Find JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        
        try:
            data = json.loads(text)
            return {
                "new_hypothesis": data.get("new_hypothesis", ""),
                "exploration_direction": data.get("exploration_direction", ""),
                "orthogonality_reason": data.get("orthogonality_reason", ""),
                "expected_characteristics": data.get("expected_characteristics", "")
            }
        except json.JSONDecodeError:
            # If JSON parsing fails, treat entire response as hypothesis
            return {"new_hypothesis": response.strip()}
    
    def _generate_fallback_hypothesis(self, parent: StrategyTrajectory) -> str:
        """Generate a fallback hypothesis when LLM fails."""
        parent_hypo = parent.hypothesis.lower() if parent.hypothesis else ""
        
        # Get fallback templates from prompts
        fallback_templates = self.prompts.get("fallback_templates", [
            "Explore mean reversion characteristics opposite to price momentum",
            "Study nonlinear relationships between volume and price",
            "Analyze trend transition signals across cycles",
            "Mine liquidity features in market microstructure",
            "Build factors based on volatility regime switching",
            "Explore the relationship between sector rotation and individual stock alpha",
        ])
        
        # Select based on parent content
        if "momentum" in parent_hypo:
            return "Explore mean reversion characteristics: patterns when price reverts to historical mean"
        elif "mean reversion" in parent_hypo or "reversion" in parent_hypo:
            return "Explore trend following characteristics: identify and follow medium-to-long term price trends"
        elif "volume" in parent_hypo:
            return "Explore price patterns: technical features purely based on price sequences"
        elif "volatility" in parent_hypo:
            return "Explore liquidity features: factors based on bid-ask spread and order flow"
        else:
            import random
            return random.choice(fallback_templates)
    
    def generate_mutation_prompt_suffix(
        self, parent: StrategyTrajectory, targeted: bool = True
    ) -> str:
        """
        Generate a prompt suffix to be appended to the hypothesis generator.

        Args:
            parent: The parent trajectory
            targeted: When True (default), use paper §4.2.2 targeted refinement
                (self-reflect → identify worst step → refine only that step,
                freeze prefix). When False, fall back to legacy "generate
                orthogonal hypothesis" behavior.

        Returns:
            Prompt suffix string
        """
        if targeted:
            guidance = self.generate_targeted_mutation(parent)
            return self._build_targeted_suffix(guidance)

        mutation_result = self.generate_mutation(parent, use_detailed_prompt=True)
        
        # Use template from prompts if available
        suffix_template = self.prompts.get("suffix_template")
        if suffix_template:
            return suffix_template.format(
                parent_summary=parent.to_summary_text(),
                new_hypothesis=mutation_result.get('new_hypothesis', 'Explore new direction'),
                exploration_direction=mutation_result.get('exploration_direction', ''),
                orthogonality_reason=mutation_result.get('orthogonality_reason', '')
            )
        
        # Default suffix (English)
        suffix = f"""

---

## Mutation Round Guidance

This is a mutation exploration round that requires generating an orthogonal new strategy based on the parent strategy.

### Parent Strategy Summary
{parent.to_summary_text()}

### Mutation Direction Suggestions
- **New Hypothesis Direction**: {mutation_result.get('new_hypothesis', 'Explore new direction')}
- **Exploration Dimension**: {mutation_result.get('exploration_direction', '')}
- **Orthogonality Reasoning**: {mutation_result.get('orthogonality_reason', '')}

### Important Notes
1. Your new hypothesis must be orthogonal to the parent strategy to avoid repeated exploration
2. Prioritize exploring data dimensions and market patterns not covered by the parent
3. Generated factors should have low correlation with parent factors

Please propose your new hypothesis based on the above mutation guidance.
"""
        return suffix

    def _build_targeted_suffix(self, guidance: MutationGuidance) -> str:
        """
        Render MutationGuidance as a prompt suffix that instructs the downstream
        agent to freeze validated steps and refine only the localized failure.
        """
        freeze_block = (
            ", ".join(guidance.freeze_steps) if guidance.freeze_steps else "(none — refine from the top)"
        )

        # When prefix is frozen, echo the frozen content so the agent can build on it.
        echoed = []
        if "hypothesis" in guidance.freeze_steps and guidance.parent_hypothesis:
            echoed.append(
                f"### FROZEN — Hypothesis (do NOT change):\n{guidance.parent_hypothesis}"
            )
        if "factor_expression" in guidance.freeze_steps and guidance.parent_factors_summary:
            echoed.append(
                f"### FROZEN — Factor expressions (do NOT change):\n"
                f"{guidance.parent_factors_summary}"
            )
        echoed_block = "\n\n".join(echoed) if echoed else "(no prefix to freeze)"

        suffix = f"""

---

## Mutation Round Guidance — Targeted Refinement (Paper §4.2.2 eq. 7)

This is a TARGETED mutation. Self-reflection localized the failing step and
froze the validated prefix. Refine ONLY the indicated step; preserve everything
upstream of it.

### Diagnosis
{guidance.diagnosis or '(none)'}

### Refinement Target
- **Worst step**: `{guidance.worst_step}`
- **Frozen prefix**: {freeze_block}

### Refinement Directive (apply ONLY to `{guidance.worst_step}`)
{guidance.refined_directive or '(no specific directive)'}

{echoed_block}

### Constraints
1. Do NOT modify any frozen step — preserve its exact semantics.
2. Refine the targeted step in line with the directive above.
3. After refining `{guidance.worst_step}`, regenerate downstream steps
   conditioned on the (now-fixed) refined step.
"""
        return suffix
