import React from 'react';
import {
  ChevronDown,
  ChevronRight,
  Lightbulb,
  Loader2,
  RefreshCw,
  Sparkles,
} from 'lucide-react';

import { suggestObjectives } from '@/services/api';
import type { SuggestedObjective } from '@/types';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { cn } from '@/utils';

type SuggestionStyle =
  | 'auto'
  | 'gap-fill'
  | 'adventurous'
  | 'refinement'
  | 'diversify'
  | 'focused'
  | 'contrarian'
  | 'simplify'
  | 'compose';

type Complexity = 'low' | 'medium' | 'high';

interface ObjectiveSuggesterProps {
  onPick: (objective: string) => void;
}

const STYLE_OPTIONS: { value: SuggestionStyle; label: string; hint: string }[] = [
  { value: 'auto',        label: 'Auto',        hint: 'Pick the best style based on your run history (default).' },
  { value: 'gap-fill',    label: 'Gap-fill',    hint: 'Avoid topics already explored in past runs. Stays within familiar mechanism families.' },
  { value: 'adventurous', label: 'Adventurous', hint: 'Unusual / experimental factor families — calendar, microstructure, regime-conditioned. Higher novelty, more uncertainty.' },
  { value: 'refinement',  label: 'Refinement',  hint: 'Build on a past winner (best_rank_icir > 0.04). Tighter universe, alternative neutralization, additional risk controls.' },
  { value: 'diversify',   label: 'Diversify',   hint: 'Spread suggestions across many different mechanisms in one batch. Breadth-first.' },
  { value: 'focused',     label: 'Focused',     hint: 'Variants within a single mechanism (deep dive). Vary windows / features / gates but stay in one family.' },
  { value: 'contrarian',  label: 'Contrarian',  hint: 'Invert what worked. If past wins are momentum, propose mean-reversion. Builds an anti-correlated complement.' },
  { value: 'simplify',    label: 'Simplify',    hint: 'Low-complexity only — single window, single feature, no nesting. Sanity baseline & interpretability.' },
  { value: 'compose',     label: 'Compose',     hint: 'Combine mechanisms from your top two past winners into hybrid factors.' },
];

// Quick-pick topic chips that prefill the focus hint
const TOPIC_CHIPS: { label: string; hint: string }[] = [
  { label: 'Momentum',         hint: 'momentum-based, trend continuation' },
  { label: 'Mean-reversion',   hint: 'mean-reversion, short-horizon overshoots' },
  { label: 'Volatility',       hint: 'volatility-derived, regime-conditioned by realized vol' },
  { label: 'Volume',           hint: 'volume-derived, dollar volume, turnover patterns' },
  { label: 'Sector-neutral',   hint: 'sector-neutral or industry-neutral composite' },
  { label: 'Cross-sectional',  hint: 'cross-sectional rank/skew patterns' },
  { label: 'Calendar',         hint: 'calendar effects (turn-of-month, day-of-week)' },
  { label: 'Microstructure',   hint: 'gap, intraday range, opening-auction patterns' },
  { label: 'Value',            hint: 'fundamental/valuation proxy from price + volume' },
  { label: 'Regime-aware',     hint: 'conditioned on market regime (vol, trend, breadth)' },
];

const MECHANISM_TONES: Record<string, string> = {
  'value-anchor':              'border-emerald-700/60 bg-emerald-950/40 text-emerald-300',
  'momentum':                  'border-sky-700/60 bg-sky-950/40 text-sky-300',
  'mean-reversion':            'border-cyan-700/60 bg-cyan-950/40 text-cyan-300',
  'volatility-derived':        'border-amber-700/60 bg-amber-950/40 text-amber-300',
  'volume-derived':            'border-orange-700/60 bg-orange-950/40 text-orange-300',
  'cross-sectional':           'border-pink-700/60 bg-pink-950/40 text-pink-300',
  'regime-conditioned':        'border-violet-700/60 bg-violet-950/40 text-violet-300',
  'calendar-effect':           'border-indigo-700/60 bg-indigo-950/40 text-indigo-300',
  'sector-neutral-composite':  'border-teal-700/60 bg-teal-950/40 text-teal-300',
  'fundamental-proxy':         'border-fuchsia-700/60 bg-fuchsia-950/40 text-fuchsia-300',
};

export const ObjectiveSuggester: React.FC<ObjectiveSuggesterProps> = ({ onPick }) => {
  const [open, setOpen] = React.useState(false);
  const [focusHint, setFocusHint] = React.useState('');
  const [style, setStyle] = React.useState<SuggestionStyle>('auto');
  const [customizeOpen, setCustomizeOpen] = React.useState(false);
  const [pending, setPending] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [suggestions, setSuggestions] = React.useState<SuggestedObjective[]>([]);
  const [styleResolved, setStyleResolved] = React.useState<string | null>(null);

  const run = async () => {
    setPending(true);
    setErr(null);
    try {
      const res = await suggestObjectives({
        n: 4,
        focusHint: focusHint || undefined,
        style,
      });
      if (res.success && res.data) {
        setSuggestions(res.data.suggestions || []);
        const resolved = (res.data as any).style_resolved || null;
        setStyleResolved(resolved);
        setOpen(true);
      } else {
        setErr(res.error || 'Suggester failed');
      }
    } catch (e: any) {
      setErr(e?.message || 'Suggester failed');
    } finally {
      setPending(false);
    }
  };

  const styleLabel = STYLE_OPTIONS.find((s) => s.value === style)?.label || style;

  return (
    <div className="space-y-3">
      {/* Topic quick-picks */}
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-muted-foreground mr-1">topic:</span>
        {TOPIC_CHIPS.map((t) => (
          <button
            key={t.label}
            type="button"
            onClick={() => setFocusHint(t.hint)}
            title={`Set focus hint to: "${t.hint}"`}
            className="rounded-md border border-border hover:border-primary/50 hover:bg-primary/5 text-muted-foreground hover:text-foreground px-2 py-0.5 transition-colors"
          >
            {t.label}
          </button>
        ))}
        {focusHint && (
          <button
            type="button"
            onClick={() => setFocusHint('')}
            className="rounded-md border border-transparent text-muted-foreground hover:text-destructive px-2 py-0.5 text-[10px] uppercase tracking-wider"
            title="Clear focus hint"
          >
            clear
          </button>
        )}
      </div>

      {/* Main row: button + focus hint */}
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={run}
          disabled={pending}
          title="Use the LLM to propose factor-mining directions based on the available qlib universe + your past runs"
        >
          {pending ? (
            <>
              <Loader2 className="size-3.5 animate-spin mr-1" /> Thinking…
            </>
          ) : suggestions.length > 0 ? (
            <>
              <RefreshCw className="size-3.5 mr-1" /> Re-roll suggestions
            </>
          ) : (
            <>
              <Lightbulb className="size-3.5 mr-1" /> Suggest directions
            </>
          )}
        </Button>
        <input
          type="text"
          value={focusHint}
          onChange={(e) => setFocusHint(e.target.value)}
          placeholder='Optional focus, e.g. "volatility-aware" or "sector-neutral"'
          className="flex-1 rounded-md border border-border bg-secondary/40 px-3 py-1.5 text-xs focus:border-primary focus:outline-none"
        />
      </div>

      {/* Customize disclosure */}
      <div>
        <button
          type="button"
          onClick={() => setCustomizeOpen((v) => !v)}
          className="text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground flex items-center gap-1"
        >
          {customizeOpen ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
          Customize
          <span className="normal-case tracking-normal text-[10px] text-muted-foreground/70 ml-1">
            (style: {styleLabel})
          </span>
        </button>

        {customizeOpen && (
          <div className="mt-2 p-3 rounded-md border border-border bg-secondary/20 space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Strategy — how should the LLM pick directions?
            </div>
            <div className="flex items-center gap-1 flex-wrap">
              {STYLE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setStyle(opt.value)}
                  title={opt.hint}
                  className={cn(
                    'rounded border px-2 py-0.5 text-[11px] transition-colors',
                    style === opt.value
                      ? 'border-violet-500 bg-violet-950/40 text-violet-200'
                      : 'border-border hover:border-muted text-muted-foreground hover:text-foreground'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="text-[10px] text-muted-foreground italic">
              {STYLE_OPTIONS.find((s) => s.value === style)?.hint}
            </div>
          </div>
        )}
      </div>

      {err && (
        <div className="text-xs text-destructive bg-destructive/10 border border-destructive/40 rounded p-2">
          {err}
        </div>
      )}

      {open && suggestions.length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1 flex-wrap">
            <Sparkles className="size-3" /> {suggestions.length} ideas — click any to use
            {styleResolved && style === 'auto' && (
              <span className="normal-case tracking-normal text-[10px] text-muted-foreground/80 ml-1">
                · auto picked: <strong className="text-foreground/90">{styleResolved}</strong>
              </span>
            )}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            {suggestions.map((s, i) => (
              <SuggestionCard key={i} suggestion={s} onPick={onPick} />
            ))}
          </div>
        </div>
      )}

      {open && !pending && suggestions.length === 0 && !err && (
        <div className="text-xs text-muted-foreground italic">
          No suggestions returned. Try a more specific focus hint or check the backend logs.
        </div>
      )}
    </div>
  );
};

const SuggestionCard: React.FC<{
  suggestion: SuggestedObjective;
  onPick: (objective: string) => void;
}> = ({ suggestion, onPick }) => {
  return (
    <Card className="hover:border-violet-700/60 transition-colors">
      <CardContent className="space-y-2 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="text-sm font-semibold text-foreground min-w-0">{suggestion.title}</div>
          <button
            type="button"
            onClick={() => onPick(suggestion.description)}
            className="shrink-0 text-[10px] uppercase tracking-wider rounded border border-violet-700/60 bg-violet-950/40 text-violet-300 px-2 py-1 hover:bg-violet-900/40"
          >
            Use this →
          </button>
        </div>

        <p className="text-xs text-foreground/90 leading-snug">{suggestion.description}</p>

        <div className="flex flex-wrap gap-1.5">
          <MechanismBadge mechanism={suggestion.mechanism} />
          <ComplexityBadge label="complexity" value={suggestion.complexity} />
          {suggestion.expected_horizon_days != null && (
            <span className="text-[10px] rounded border border-border bg-secondary/60 text-foreground/80 px-1.5 py-0.5 font-mono">
              horizon: {suggestion.expected_horizon_days}d
            </span>
          )}
          {suggestion.primary_features.length > 0 && (
            <span className="text-[10px] rounded border border-border bg-secondary/60 text-foreground/80 px-1.5 py-0.5 font-mono">
              {suggestion.primary_features.slice(0, 4).join(', ')}
              {suggestion.primary_features.length > 4 ? ` +${suggestion.primary_features.length - 4}` : ''}
            </span>
          )}
        </div>

        {suggestion.rationale_for_user && (
          <div className="text-[11px] text-muted-foreground italic leading-snug border-t border-border pt-2">
            ↪ {suggestion.rationale_for_user}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

const MechanismBadge: React.FC<{ mechanism: string }> = ({ mechanism }) => {
  const tone = MECHANISM_TONES[mechanism] || 'border-border bg-secondary/60 text-muted-foreground';
  return (
    <span className={cn('text-[10px] rounded border px-1.5 py-0.5', tone)}>{mechanism}</span>
  );
};

const ComplexityBadge: React.FC<{ label: string; value: Complexity }> = ({ label, value }) => {
  const tones: Record<Complexity, string> = {
    low:    'border-emerald-700/60 text-emerald-300',
    medium: 'border-border text-foreground/80',
    high:   'border-red-700/60 text-red-300',
  };
  return (
    <span className={cn('text-[10px] rounded border bg-secondary/40 px-1.5 py-0.5', tones[value])}>
      {label}: <strong>{value}</strong>
    </span>
  );
};
