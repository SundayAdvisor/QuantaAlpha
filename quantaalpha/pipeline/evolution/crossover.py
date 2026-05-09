"""
Crossover operator for combining multiple parent trajectories.

Two modes:
- `generate_crossover` (legacy): whole-hypothesis fusion via LLM. Loses lineage.
- `generate_segment_crossover` (paper §4.2.2 eq. 8): decompose each parent into
  segments (hypothesis, factor expressions, repair actions), score segments by
  parent RankIC contribution, recombine high-scoring segments from different
  parents into a child trajectory with explicit provenance.

A "segment" here is one of:
  - hypothesis: the core market insight
  - factor_expression_pattern: symbolic construction patterns (e.g. "TS_CORR
    of return-volume change") that contributed to the parent's reward
  - repair_action: debugging/correction moves applied during the parent's run
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from quantaalpha.log import logger
from quantaalpha.llm.client import APIBackend
from .trajectory import StrategyTrajectory, RoundPhase


SEGMENT_TYPES = ("hypothesis", "factor_expression_pattern", "repair_action")


@dataclass
class CrossoverGuidance:
    """
    Structured plan for segment-level crossover with explicit lineage.

    Each entry in `inherited_segments` is a dict:
        {
            "type": one of SEGMENT_TYPES,
            "source_parent_id": trajectory_id,
            "source_rank_ic": float,
            "content": the inherited content (text/expression),
            "rationale": why this segment was chosen
        }

    `composition_directive` describes how the segments should be combined.
    """
    inherited_segments: list[dict] = field(default_factory=list)
    composition_directive: str = ""
    lineage_summary: str = ""
    parent_ids: list[str] = field(default_factory=list)
    fallback_used: bool = False


# Default prompt path
DEFAULT_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "evolution_prompts.yaml"


class CrossoverOperator:
    """
    Combines multiple parent trajectories into hybrid strategies.
    
    The crossover process:
    1. Takes 2 or more parent trajectories
    2. Analyzes their strengths, weaknesses, and complementary aspects
    3. Generates a hybrid hypothesis that combines the best elements
    
    Key principles:
    - Synergy: Combine complementary aspects of parents
    - Improvement: Learn from both successes and failures
    - Innovation: Generate novel combinations not present in parents
    """
    
    def __init__(self, prompt_path: Optional[Path] = None):
        """
        Initialize crossover operator.
        
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
                crossover_prompts = all_prompts.get("crossover", {})
                if crossover_prompts:
                    return crossover_prompts
            except Exception as e:
                logger.warning(f"Failed to load crossover prompts from {self.prompt_path}: {e}")
        
        # Minimal fallback prompts (English)
        logger.warning("Using minimal fallback prompts for crossover operator")
        return {
            "system": "You are a quantitative finance strategy fusion expert. Combine strategies effectively.",
            "user": "Combine parent strategies:\n{parent_summaries}",
            "simple_user": "Generate hybrid hypothesis from:\n{parent_summaries}",
            "parent_template": "Parent {idx}: {hypothesis}",
            "phase_names": {
                "original": "Original Round",
                "mutation": "Mutation Round",
                "crossover": "Crossover Round"
            }
        }
    
    def _format_parent_summary(self, parent: StrategyTrajectory, idx: int) -> str:
        """Format a single parent trajectory for the prompt."""
        phase_names = self.prompts.get("phase_names", {
            "original": "Original Round",
            "mutation": "Mutation Round",
            "crossover": "Crossover Round"
        })
        phase_name = phase_names.get(parent.phase.value, "Unknown")
        
        factors_str = ""
        if parent.factors:
            for f in parent.factors[:3]:
                name = f.get("name", "unknown")
                expr = f.get("expression", "")[:80]
                factors_str += f"  - {name}: {expr}\n"
        else:
            factors_str = "  N/A\n"
        
        metrics_str = ""
        if parent.backtest_metrics:
            for k, v in parent.backtest_metrics.items():
                if v is not None:
                    metrics_str += f"  - {k}: {v:.4f}\n"
        if not metrics_str:
            metrics_str = "  N/A\n"
        
        template = self.prompts.get("parent_template", "")
        if template:
            return template.format(
                idx=idx,
                phase_name=phase_name,
                direction_id=parent.direction_id,
                hypothesis=parent.hypothesis[:300] if parent.hypothesis else "N/A",
                factors=factors_str,
                metrics=metrics_str,
                feedback=parent.feedback[:200] if parent.feedback else "N/A"
            )
        
        # Default format
        return f"""### Parent {idx}: {phase_name}
**Direction ID**: {parent.direction_id}
**Hypothesis**: {parent.hypothesis[:300] if parent.hypothesis else 'N/A'}
**Factors**:
{factors_str}
**Metrics**:
{metrics_str}
**Feedback**:
{parent.feedback[:200] if parent.feedback else 'N/A'}
---
"""
    
    def generate_crossover(
        self,
        parents: list[StrategyTrajectory],
        use_detailed_prompt: bool = True
    ) -> dict[str, str]:
        """
        Generate a crossover (hybrid) strategy from multiple parents.
        
        Args:
            parents: List of parent trajectories to combine
            use_detailed_prompt: Whether to use detailed prompt with JSON output
            
        Returns:
            Dictionary containing crossover results:
            - "hybrid_hypothesis": The hybrid hypothesis text
            - "fusion_logic": How parents were combined
            - "innovation_points": Novel aspects of hybrid
            - "expected_benefits": Expected improvements
            - "parent_ids": List of parent trajectory IDs
        """
        if len(parents) < 2:
            logger.warning("Crossover requires at least 2 parents")
            return {"hybrid_hypothesis": parents[0].hypothesis if parents else ""}
        
        # Format parent summaries
        parent_summaries = "\n".join(
            self._format_parent_summary(p, i + 1) 
            for i, p in enumerate(parents)
        )
        
        # Build prompt
        system_prompt = self.prompts.get("system", "")
        
        if use_detailed_prompt:
            user_prompt = self.prompts.get("user", "").format(
                parent_summaries=parent_summaries
            )
        else:
            user_prompt = self.prompts.get("simple_user", "").format(
                parent_summaries=parent_summaries
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
                result = {"hybrid_hypothesis": response.strip()}
            
            result["parent_ids"] = [p.trajectory_id for p in parents]
            
            logger.info(f"Generated crossover from {len(parents)} parents: "
                       f"{[p.trajectory_id for p in parents]}")
            return result
            
        except Exception as e:
            logger.error(f"Crossover generation failed: {e}")
            # Return fallback
            return self._generate_fallback_crossover(parents)
    
    def _parse_detailed_response(self, response: str) -> dict[str, str]:
        """Parse JSON response from LLM."""
        import json
        import re

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
                "hybrid_hypothesis": data.get("hybrid_hypothesis", ""),
                "fusion_logic": data.get("fusion_logic", ""),
                "innovation_points": data.get("innovation_points", ""),
                "expected_benefits": data.get("expected_benefits", "")
            }
        except json.JSONDecodeError:
            return {"hybrid_hypothesis": response.strip()}

    def generate_segment_crossover(
        self, parents: list[StrategyTrajectory]
    ) -> CrossoverGuidance:
        """
        Paper §4.2.2 eq. 8: segment-level crossover with explicit provenance.

        Build a segment menu from each parent (hypothesis, factor expression
        patterns, repair actions), have the LLM pick the highest-contributing
        segments from across parents, and emit guidance with traceable lineage.
        """
        if len(parents) < 2:
            logger.warning("Segment crossover requires at least 2 parents")
            return CrossoverGuidance(
                fallback_used=True,
                parent_ids=[p.trajectory_id for p in parents],
            )

        segment_menu = self._build_segment_menu(parents)
        parent_ids = [p.trajectory_id for p in parents]

        system_prompt = (
            "You are a quantitative finance expert performing trajectory-level "
            "crossover. Below is a segment menu listing the best-performing "
            "components from each parent trajectory: hypotheses, factor "
            "expression patterns, and repair actions. Each segment is tagged "
            "with its source parent and that parent's RankIC.\n\n"
            "Your job: select segments from DIFFERENT parents whose combination "
            "is plausibly better than any individual parent. Preserve the exact "
            "wording of inherited segments (no paraphrasing) so lineage is "
            "traceable. Output STRICT JSON with keys:\n"
            "  - inherited_segments: list of {type, source_parent_id, content, rationale}\n"
            "  - composition_directive: how to combine the chosen segments\n"
            "  - lineage_summary: one-sentence summary of the inheritance"
        )
        user_prompt = (
            f"Segment menu:\n{segment_menu}\n\n"
            f"Pick complementary segments from different parents and propose a "
            f"composition. Inherit at least 2 segments, ideally from at least 2 "
            f"different parents."
        )

        try:
            response = APIBackend().build_messages_and_create_chat_completion(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                json_mode=True,
            )
            parsed = self._parse_segment_response(response)
            segments = self._validate_inherited_segments(
                parsed.get("inherited_segments", []), parents
            )
            guidance = CrossoverGuidance(
                inherited_segments=segments,
                composition_directive=parsed.get("composition_directive", ""),
                lineage_summary=parsed.get("lineage_summary", ""),
                parent_ids=parent_ids,
            )
            logger.info(
                f"Segment crossover from {len(parents)} parents: inherited "
                f"{len(segments)} segments across "
                f"{len({s['source_parent_id'] for s in segments})} sources"
            )
            return guidance
        except Exception as e:
            logger.warning(f"Segment crossover LLM call failed ({e}); falling back")
            fallback = self._fallback_segment_crossover(parents)
            return CrossoverGuidance(
                inherited_segments=fallback,
                composition_directive=(
                    "Combine the highest-RankIC hypothesis with the second parent's "
                    "factor expression patterns and any successful repair moves."
                ),
                lineage_summary="Heuristic segment inheritance (LLM unavailable)",
                parent_ids=parent_ids,
                fallback_used=True,
            )

    def _build_segment_menu(self, parents: list[StrategyTrajectory]) -> str:
        """Format each parent's segments for the LLM, tagged with provenance."""
        lines = []
        for p in parents:
            ric = p.get_primary_metric()
            ric_str = f"{ric:.4f}" if ric is not None else "N/A"
            lines.append(f"\n=== Parent {p.trajectory_id} (RankIC={ric_str}, "
                         f"phase={p.phase.value}) ===")
            # Hypothesis segment
            if p.hypothesis:
                lines.append(f"[hypothesis] {p.hypothesis[:400]}")
            # Factor expression patterns
            for f in p.factors[:3]:
                name = f.get("name", "?")
                expr = (f.get("expression") or "")[:200]
                if expr:
                    lines.append(f"[factor_expression_pattern:{name}] {expr}")
            # Repair actions (from feedback if it mentions corrections)
            fb = p.feedback or ""
            if fb and any(k in fb.lower() for k in ("fix", "correct", "repair", "revise")):
                lines.append(f"[repair_action] {fb[:300]}")
        return "\n".join(lines)

    def _validate_inherited_segments(
        self, raw_segments: list, parents: list[StrategyTrajectory]
    ) -> list[dict]:
        """Validate LLM's inherited-segment list and attach source RankICs."""
        parent_lookup = {p.trajectory_id: p for p in parents}
        clean = []
        for s in raw_segments:
            if not isinstance(s, dict):
                continue
            stype = s.get("type", "")
            if stype not in SEGMENT_TYPES:
                continue
            src = s.get("source_parent_id", "")
            parent = parent_lookup.get(src)
            if parent is None:
                # LLM may have hallucinated the parent id; pick the highest-RankIC parent as fallback
                parent = max(parents, key=lambda p: p.get_primary_metric() or 0)
                src = parent.trajectory_id
            content = s.get("content", "")
            if not content:
                continue
            clean.append({
                "type": stype,
                "source_parent_id": src,
                "source_rank_ic": parent.get_primary_metric() or 0.0,
                "content": content,
                "rationale": s.get("rationale", ""),
            })
        return clean

    def _parse_segment_response(self, response: str) -> dict:
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
            logger.warning("Segment crossover response not valid JSON")
            return {}

    def _fallback_segment_crossover(
        self, parents: list[StrategyTrajectory]
    ) -> list[dict]:
        """Heuristic when the LLM is unavailable: take hypothesis from the
        highest-RankIC parent and one factor expression from the next-best."""
        ranked = sorted(
            parents,
            key=lambda p: p.get_primary_metric() or 0.0,
            reverse=True,
        )
        out = []
        if ranked and ranked[0].hypothesis:
            out.append({
                "type": "hypothesis",
                "source_parent_id": ranked[0].trajectory_id,
                "source_rank_ic": ranked[0].get_primary_metric() or 0.0,
                "content": ranked[0].hypothesis,
                "rationale": "Highest-RankIC parent's hypothesis",
            })
        if len(ranked) > 1 and ranked[1].factors:
            f = ranked[1].factors[0]
            out.append({
                "type": "factor_expression_pattern",
                "source_parent_id": ranked[1].trajectory_id,
                "source_rank_ic": ranked[1].get_primary_metric() or 0.0,
                "content": f"{f.get('name', 'expr')}: {f.get('expression', '')[:200]}",
                "rationale": "Second-ranked parent's leading factor expression",
            })
        return out
    
    def _generate_fallback_crossover(self, parents: list[StrategyTrajectory]) -> dict[str, str]:
        """Generate a fallback crossover when LLM fails."""
        # Simple heuristic: combine keywords from parent hypotheses
        keywords = []
        for p in parents:
            if p.hypothesis:
                # Extract key concepts
                words = p.hypothesis[:100].split()
                keywords.extend(words[:5])
        
        hypothesis = f"Hybrid strategy: combining advantages of {len(parents)} parent strategies, " \
                    f"exploring synergistic effects in directions including {', '.join(set(keywords[:3]))}"
        
        return {
            "hybrid_hypothesis": hypothesis,
            "fusion_logic": "Simple fusion of core concepts from each parent",
            "innovation_points": "Multi-strategy combination may produce synergistic effects",
            "expected_benefits": "Reduce single strategy risk through combination",
            "parent_ids": [p.trajectory_id for p in parents]
        }
    
    def generate_crossover_prompt_suffix(
        self,
        parents: list[StrategyTrajectory],
        segment_mode: bool = True,
    ) -> str:
        """
        Generate a prompt suffix to be appended to the hypothesis generator.

        Args:
            parents: List of parent trajectories
            segment_mode: When True (default), use paper §4.2.2 segment-level
                crossover with explicit lineage. When False, use legacy
                whole-hypothesis fusion.

        Returns:
            Prompt suffix string
        """
        if segment_mode:
            guidance = self.generate_segment_crossover(parents)
            return self._build_segment_suffix(guidance)

        crossover_result = self.generate_crossover(parents, use_detailed_prompt=True)
        
        parent_summaries = []
        for i, p in enumerate(parents):
            summary = f"""**Parent {i+1}** (Direction {p.direction_id}, {p.phase.value}):
- Hypothesis: {p.hypothesis[:200] if p.hypothesis else 'N/A'}...
- Key Metric: RankIC={p.backtest_metrics.get('RankIC', 'N/A')}"""
            parent_summaries.append(summary)
        
        # Use template from prompts if available
        suffix_template = self.prompts.get("suffix_template")
        if suffix_template:
            return suffix_template.format(
                parent_summaries=chr(10).join(parent_summaries),
                hybrid_hypothesis=crossover_result.get('hybrid_hypothesis', 'Combine parent advantages'),
                fusion_logic=crossover_result.get('fusion_logic', ''),
                innovation_points=crossover_result.get('innovation_points', '')
            )
        
        # Default suffix (English)
        suffix = f"""

---

## Crossover Round Guidance

This is a crossover fusion exploration round that requires generating a hybrid strategy by combining multiple parent strategies.

### Parent Strategy Summaries
{chr(10).join(parent_summaries)}

### Fusion Direction Suggestions
- **Hybrid Hypothesis Direction**: {crossover_result.get('hybrid_hypothesis', 'Combine parent advantages')}
- **Fusion Logic**: {crossover_result.get('fusion_logic', '')}
- **Innovation Points**: {crossover_result.get('innovation_points', '')}

### Important Notes
1. Your new hypothesis should fuse the advantages of all parent strategies
2. Avoid inheriting common weaknesses of the parents
3. Look for synergistic effects between parent strategies
4. Generated factors should capture the comprehensive characteristics of the combined strategies

Please propose your fusion hypothesis based on the above crossover guidance.
"""
        return suffix
    
    def select_crossover_pairs(
        self,
        candidates: list[StrategyTrajectory],
        crossover_size: int = 2,
        crossover_n: int = 3,
        prefer_diverse: bool = True,
        selection_strategy: str = "best",
        top_percent_threshold: float = 0.3
    ) -> list[list[StrategyTrajectory]]:
        """
        Select parent groups for crossover.
        
        Args:
            candidates: All available trajectories
            crossover_size: Number of parents per group
            crossover_n: Number of groups to create
            prefer_diverse: Whether to prefer combinations from different directions
            selection_strategy: Parent selection strategy:
                - "best": Prioritize best-performing trajectories
                - "random": Random selection
                - "weighted": Performance-weighted sampling (higher = higher weight)
                - "weighted_inverse": Inverse performance-weighted (lower = higher weight)
                - "top_percent_plus_random": Top N% guaranteed + random from rest
            top_percent_threshold: Threshold for top_percent_plus_random strategy (default 0.3)
            
        Returns:
            List of parent groups
        """
        import itertools
        import random
        
        if len(candidates) < crossover_size:
            return []
        
        # Pre-select candidates based on strategy
        selected_candidates = self._select_candidates_by_strategy(
            candidates, 
            selection_strategy, 
            top_percent_threshold,
            crossover_n * crossover_size  # Need enough for all groups
        )
        
        # Generate all possible combinations from selected candidates
        all_combos = list(itertools.combinations(selected_candidates, crossover_size))
        
        if not all_combos:
            return []
        
        if prefer_diverse:
            # Score combinations by diversity
            scored = []
            for combo in all_combos:
                # Higher score for different directions and phases
                directions = len(set(t.direction_id for t in combo))
                phases = len(set(t.phase for t in combo))
                # Also consider performance
                avg_metric = sum(t.get_primary_metric() or 0 for t in combo) / len(combo)
                score = directions * 2 + phases + avg_metric
                scored.append((list(combo), score))
            
            # Sort by score descending
            scored.sort(key=lambda x: x[1], reverse=True)
            
            # Select top combinations
            selected = [combo for combo, _ in scored[:crossover_n]]
        else:
            # Random selection
            random.shuffle(all_combos)
            selected = [list(combo) for combo in all_combos[:crossover_n]]
        
        return selected
    
    def _select_candidates_by_strategy(
        self,
        candidates: list[StrategyTrajectory],
        strategy: str,
        top_percent_threshold: float,
        num_needed: int
    ) -> list[StrategyTrajectory]:
        """
        Pre-select candidates based on selection strategy.
        
        Args:
            candidates: All available trajectories
            strategy: Selection strategy
            top_percent_threshold: Threshold for top_percent_plus_random
            num_needed: Minimum number of candidates needed
            
        Returns:
            List of selected candidates
        """
        import random
        
        if len(candidates) <= num_needed:
            return candidates
        
        # Sort by primary metric (descending)
        sorted_candidates = sorted(
            candidates, 
            key=lambda t: t.get_primary_metric() or 0, 
            reverse=True
        )
        
        if strategy == "best":
            # Return top performers
            return sorted_candidates[:num_needed]
        
        elif strategy == "random":
            # Random selection
            return random.sample(candidates, min(num_needed, len(candidates)))
        
        elif strategy == "weighted":
            # Performance-weighted sampling (higher performance = higher weight)
            return self._weighted_sample(sorted_candidates, num_needed, inverse=False)
        
        elif strategy == "weighted_inverse":
            # Inverse performance-weighted sampling (lower performance = higher weight)
            # Ref: EvoControl _weighted_select_labels strategy
            return self._weighted_sample(sorted_candidates, num_needed, inverse=True)
        
        elif strategy == "top_percent_plus_random":
            # Top N% guaranteed + random from rest
            top_n = max(1, int(len(candidates) * top_percent_threshold))
            top_candidates = sorted_candidates[:top_n]
            rest_candidates = sorted_candidates[top_n:]
            
            # If we need more, randomly sample from the rest
            still_needed = num_needed - len(top_candidates)
            if still_needed > 0 and rest_candidates:
                random_picks = random.sample(
                    rest_candidates, 
                    min(still_needed, len(rest_candidates))
                )
                return top_candidates + random_picks
            return top_candidates
        
        else:
            # Default to best
            logger.warning(f"Unknown selection strategy: {strategy}, using 'best'")
            return sorted_candidates[:num_needed]
    
    def _weighted_sample(
        self,
        sorted_candidates: list[StrategyTrajectory],
        num_needed: int,
        inverse: bool = False
    ) -> list[StrategyTrajectory]:
        """
        Weighted sampling based on performance.
        
        Args:
            sorted_candidates: Candidates sorted by performance (descending)
            num_needed: Number to select
            inverse: If True, lower performance = higher weight (encourages exploration)
            
        Returns:
            List of selected candidates
        """
        import random
        
        if len(sorted_candidates) <= num_needed:
            return sorted_candidates
        
        # Calculate weights
        metrics = [t.get_primary_metric() or 0 for t in sorted_candidates]
        
        # Normalize metrics to [0, 1] range
        min_m = min(metrics) if metrics else 0
        max_m = max(metrics) if metrics else 1
        range_m = max_m - min_m if max_m > min_m else 1
        
        normalized = [(m - min_m) / range_m for m in metrics]
        
        if inverse:
            # Lower performance = higher weight (for exploration)
            # Ref: EvoControl - lower performance => higher weight
            weights = [1 - n + 0.1 for n in normalized]  # +0.1 to avoid zero weight
        else:
            # Higher performance = higher weight
            weights = [n + 0.1 for n in normalized]  # +0.1 to avoid zero weight
        
        # Normalize weights to sum to 1
        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]
        
        # Weighted sampling without replacement
        selected = []
        remaining = list(zip(sorted_candidates, weights))
        
        for _ in range(min(num_needed, len(sorted_candidates))):
            if not remaining:
                break
            
            candidates_left, weights_left = zip(*remaining)
            # Re-normalize weights
            total = sum(weights_left)
            probs = [w / total for w in weights_left]
            
            # Sample one
            chosen_idx = random.choices(range(len(candidates_left)), weights=probs, k=1)[0]
            selected.append(candidates_left[chosen_idx])

            # Remove chosen from remaining
            remaining = [(c, w) for i, (c, w) in enumerate(remaining) if i != chosen_idx]

        return selected

    def _build_segment_suffix(self, guidance: CrossoverGuidance) -> str:
        """
        Render CrossoverGuidance as a prompt suffix that instructs the agent to
        compose a child trajectory from the explicitly inherited segments,
        preserving lineage.
        """
        if not guidance.inherited_segments:
            return f"""

---

## Crossover Round Guidance — Segment Inheritance (Paper §4.2.2 eq. 8)

Segment selection produced no inheritable segments. Falling back to free
hypothesis fusion across the parents.
"""

        segment_lines = []
        for i, seg in enumerate(guidance.inherited_segments, 1):
            segment_lines.append(
                f"{i}. **{seg['type']}** "
                f"(from parent `{seg['source_parent_id']}`, "
                f"RankIC={seg['source_rank_ic']:.4f}):\n"
                f"   ```\n   {seg['content']}\n   ```\n"
                f"   _rationale_: {seg.get('rationale', '(none)')}"
            )
        segments_block = "\n\n".join(segment_lines)

        sources = sorted({s["source_parent_id"] for s in guidance.inherited_segments})
        provenance = ", ".join(sources)

        suffix = f"""

---

## Crossover Round Guidance — Segment Inheritance (Paper §4.2.2 eq. 8)

This child trajectory inherits validated segments from {len(sources)} parent
trajectories. PRESERVE inherited content verbatim — lineage must remain
traceable. Compose downstream steps so they remain consistent with the
inherited segments.

### Lineage
{guidance.lineage_summary or '(no summary)'}

Inherited from: {provenance}

### Inherited Segments (DO NOT paraphrase)
{segments_block}

### Composition Directive
{guidance.composition_directive or '(combine inherited segments coherently)'}

### Constraints
1. The hypothesis MUST incorporate the inherited hypothesis segment(s) verbatim.
2. Factor expressions MUST reuse the inherited factor_expression_pattern(s) as
   structural building blocks (you may parameterize windows but not change the
   operator skeleton).
3. If a repair_action is inherited, apply it during code generation.
4. Output should clearly trace which content came from which parent.
"""
        return suffix
