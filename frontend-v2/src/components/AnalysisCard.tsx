import React from 'react';
import {
  AlertTriangle,
  Award,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Sparkles,
  XCircle,
} from 'lucide-react';

import { explainRun } from '@/services/api';
import type { RunAnalysis, RunVerdict } from '@/types';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/utils';

interface AnalysisCardProps {
  runId: string;
  analysis: RunAnalysis | null;
  runStatus?: string;
  onAnalyzed?: (a: RunAnalysis) => void;
}

export const AnalysisCard: React.FC<AnalysisCardProps> = ({
  runId,
  analysis,
  runStatus,
  onAnalyzed,
}) => {
  const [pending, setPending] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const run = async () => {
    setPending(true);
    setErr(null);
    try {
      const res = await explainRun(runId);
      if (res.success && res.data?.analysis) {
        onAnalyzed?.(res.data.analysis);
      } else {
        setErr(res.error || 'Analysis failed');
      }
    } catch (e: any) {
      setErr(e?.message || 'Analysis failed');
    } finally {
      setPending(false);
    }
  };

  if (!analysis) {
    return (
      <Card>
        <CardContent className="flex items-center justify-between gap-4 py-4">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles className="size-4 text-violet-400 shrink-0" />
            <span className="text-sm text-muted-foreground">
              Get an AI verdict on this run — robust, regime-fit, broken, or somewhere in between.
            </span>
          </div>
          <Button
            size="sm"
            disabled={pending || runStatus === 'running'}
            onClick={run}
          >
            {pending ? (
              <>
                <Loader2 className="size-3.5 animate-spin mr-1" /> Analyzing…
              </>
            ) : (
              <>
                <Sparkles className="size-3.5 mr-1" /> Analyze
              </>
            )}
          </Button>
        </CardContent>
        {err && (
          <CardContent className="py-2 text-xs text-destructive border-t border-border">
            {err}
          </CardContent>
        )}
      </Card>
    );
  }

  return (
    <Card className={cn('border-l-4', verdictBorderClass(analysis.verdict))}>
      <CardContent className="space-y-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <VerdictIcon verdict={analysis.verdict} />
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <VerdictBadge verdict={analysis.verdict} />
                {analysis.best_rank_icir !== null && analysis.best_rank_icir !== undefined && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    best RankICIR{' '}
                    <span className={cn('font-semibold', ricirColor(analysis.best_rank_icir))}>
                      {analysis.best_rank_icir.toFixed(4)}
                    </span>
                  </span>
                )}
                {analysis.best_ir !== null && analysis.best_ir !== undefined && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    best IR{' '}
                    <span className={cn('font-semibold', irColor(analysis.best_ir))}>
                      {analysis.best_ir.toFixed(3)}
                    </span>
                  </span>
                )}
                {analysis.rank_icir_to_ir_gap !== null && analysis.rank_icir_to_ir_gap !== undefined && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    curve-fit smell{' '}
                    <span className={cn('font-semibold', gapColor(analysis.rank_icir_to_ir_gap))}>
                      {(analysis.rank_icir_to_ir_gap * 100).toFixed(0)}%
                    </span>
                  </span>
                )}
              </div>
              <div className="text-sm text-foreground mt-1.5">{analysis.verdict_reason}</div>
            </div>
          </div>
          <button
            onClick={run}
            disabled={pending}
            className="text-muted-foreground hover:text-foreground shrink-0"
            title="Re-run analysis"
          >
            {pending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-3.5" />}
          </button>
        </div>

        {analysis.summary && (
          <div className="text-sm text-foreground leading-relaxed whitespace-pre-line bg-secondary/40 rounded p-3 border border-border">
            {analysis.summary}
          </div>
        )}

        {analysis.per_trajectory_notes.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
              Per-trajectory notes
            </div>
            <ul className="space-y-1 text-xs text-foreground">
              {analysis.per_trajectory_notes.map((n, i) => (
                <li key={`${n.trajectory_id}-${i}`} className="flex gap-2">
                  <span className="text-muted-foreground font-mono shrink-0">
                    {(n.trajectory_id || '?').slice(0, 8)}:
                  </span>
                  <span>{n.note}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {analysis.recommended_next_steps.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
              Recommended next steps
            </div>
            <ul className="space-y-1 text-xs text-foreground">
              {analysis.recommended_next_steps.map((step, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-violet-400 shrink-0">→</span>
                  <span>{step}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="text-[9px] text-muted-foreground/70">
          analyzed {new Date(analysis.created_at).toLocaleString()}
        </div>
        {err && <div className="text-xs text-destructive">{err}</div>}
      </CardContent>
    </Card>
  );
};

function VerdictBadge({ verdict }: { verdict: RunVerdict }) {
  return (
    <span className={cn('text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5 border font-semibold', verdictBadgeClass(verdict))}>
      {verdict}
    </span>
  );
}

function VerdictIcon({ verdict }: { verdict: RunVerdict }) {
  const cls = 'size-5 shrink-0 mt-0.5';
  if (verdict === 'robust') return <Award className={cn(cls, 'text-emerald-400')} />;
  if (verdict === 'promising') return <CheckCircle2 className={cn(cls, 'text-cyan-400')} />;
  if (verdict === 'regime-fit') return <AlertTriangle className={cn(cls, 'text-amber-400')} />;
  if (verdict === 'marginal') return <AlertTriangle className={cn(cls, 'text-zinc-400')} />;
  return <XCircle className={cn(cls, 'text-red-400')} />;
}

function verdictBadgeClass(verdict: RunVerdict): string {
  switch (verdict) {
    case 'robust': return 'bg-emerald-950/40 border-emerald-700/60 text-emerald-300';
    case 'promising': return 'bg-cyan-950/40 border-cyan-700/60 text-cyan-300';
    case 'regime-fit': return 'bg-amber-950/40 border-amber-700/60 text-amber-300';
    case 'marginal': return 'bg-zinc-800 border-zinc-700 text-zinc-300';
    case 'broken': return 'bg-red-950/40 border-red-700/60 text-red-300';
  }
}

function verdictBorderClass(verdict: RunVerdict): string {
  switch (verdict) {
    case 'robust': return 'border-l-emerald-500';
    case 'promising': return 'border-l-cyan-500';
    case 'regime-fit': return 'border-l-amber-500';
    case 'marginal': return 'border-l-zinc-500';
    case 'broken': return 'border-l-red-500';
  }
}

function ricirColor(v: number): string {
  if (v >= 0.07) return 'text-emerald-300';
  if (v >= 0.05) return 'text-cyan-300';
  if (v >= 0.03) return 'text-amber-300';
  return 'text-red-300';
}

function irColor(v: number): string {
  if (v >= 0.5) return 'text-emerald-300';
  if (v >= 0.3) return 'text-cyan-300';
  if (v >= 0) return 'text-amber-300';
  return 'text-red-300';
}

function gapColor(v: number): string {
  if (v >= 0.6) return 'text-red-300';
  if (v >= 0.3) return 'text-amber-300';
  return 'text-emerald-300';
}
