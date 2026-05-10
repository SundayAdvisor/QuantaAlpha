import React from 'react';
import { Loader2, RefreshCw, Clock, GitBranch, FileText, Database, Boxes } from 'lucide-react';

import { Layout } from '@/components/layout/Layout';
import type { PageId } from '@/components/layout/Layout';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { AnalysisCard } from '@/components/AnalysisCard';
import { LineageGraph } from '@/components/LineageGraph';
import { TrajectoryDetailPanel } from '@/components/TrajectoryDetailPanel';
import { NamingGuide } from '@/components/NamingGuide';
import { listRuns, getRun, getRunLineage } from '@/services/api';
import type { LineageEdge, LineageNode, RunAnalysis, RunSummary } from '@/types';
import { cn, formatDateTime, formatDuration } from '@/utils';
import { useTaskContext } from '@/context/TaskContext';

interface RunHistoryPageProps {
  onNavigate?: (page: PageId) => void;
}

interface RunDetailState {
  summary: RunSummary | null;
  pool: any | null;
  analysis: RunAnalysis | null;
  lineage: { nodes: LineageNode[]; edges: LineageEdge[] };
  loading: boolean;
  error: string | null;
}

const EMPTY_DETAIL: RunDetailState = {
  summary: null,
  pool: null,
  analysis: null,
  lineage: { nodes: [], edges: [] },
  loading: false,
  error: null,
};

export const RunHistoryPage: React.FC<RunHistoryPageProps> = ({ onNavigate }) => {
  const [runs, setRuns] = React.useState<RunSummary[]>([]);
  const [loadingList, setLoadingList] = React.useState(false);
  const [listErr, setListErr] = React.useState<string | null>(null);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<RunDetailState>(EMPTY_DETAIL);
  const [selectedTrajId, setSelectedTrajId] = React.useState<string | null>(null);

  React.useEffect(() => {
    setSelectedTrajId(null);
  }, [selectedId]);

  const refreshList = React.useCallback(async () => {
    setLoadingList(true);
    setListErr(null);
    try {
      const res = await listRuns();
      if (res.success && res.data) {
        const sorted = [...(res.data.runs || [])].sort((a, b) => {
          return (b.created_at || '').localeCompare(a.created_at || '');
        });
        setRuns(sorted);
        if (!selectedId && sorted.length > 0) {
          setSelectedId(sorted[0].run_id);
        }
      } else {
        setListErr(res.error || 'Failed to load runs');
      }
    } catch (e: any) {
      setListErr(e?.message || 'Failed to load runs');
    } finally {
      setLoadingList(false);
    }
  }, [selectedId]);

  React.useEffect(() => {
    refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refetch when a new mining task starts so the history list shows the
  // currently-running run without the user having to manually refresh.
  // Also poll periodically (every 8s) so a freshly-started run that
  // appears in the backend's run dir within seconds is reflected here.
  const { miningTask } = useTaskContext();
  React.useEffect(() => {
    if (miningTask?.taskId) refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [miningTask?.taskId]);
  React.useEffect(() => {
    const id = setInterval(() => refreshList(), 8000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadDetail = React.useCallback(async (runId: string) => {
    setDetail({ ...EMPTY_DETAIL, loading: true });
    try {
      const [runRes, lineRes] = await Promise.all([getRun(runId), getRunLineage(runId)]);
      const next: RunDetailState = { ...EMPTY_DETAIL, loading: false };
      if (runRes.success && runRes.data) {
        next.summary = runRes.data.summary;
        next.pool = runRes.data.pool;
        next.analysis = runRes.data.analysis;
      } else {
        next.error = runRes.error || 'Failed to load run';
      }
      if (lineRes.success && lineRes.data) {
        next.lineage = { nodes: lineRes.data.nodes || [], edges: lineRes.data.edges || [] };
      }
      setDetail(next);
    } catch (e: any) {
      setDetail({ ...EMPTY_DETAIL, error: e?.message || 'Failed to load run' });
    }
  }, []);

  React.useEffect(() => {
    if (selectedId) loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  return (
    <Layout
      currentPage={'history' as PageId}
      onNavigate={onNavigate || (() => {})}
      showNavigation={!!onNavigate}
    >
      <div className="mb-4">
        <NamingGuide />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Run list sidebar */}
        <div className="lg:col-span-1 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Clock className="size-4" /> Past runs
            </h3>
            <button
              onClick={refreshList}
              disabled={loadingList}
              className="text-muted-foreground hover:text-foreground"
              title="Refresh"
            >
              {loadingList ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            </button>
          </div>
          {listErr && (
            <Card>
              <CardContent className="text-xs text-destructive py-3">{listErr}</CardContent>
            </Card>
          )}
          {runs.length === 0 && !loadingList && !listErr && (
            <Card>
              <CardContent className="text-xs text-muted-foreground py-3">
                No past runs yet. Mine some factors and they'll appear here.
              </CardContent>
            </Card>
          )}
          <div className="space-y-2 max-h-[70vh] overflow-y-auto pr-1">
            {runs.map((r) => (
              <button
                key={r.run_id}
                onClick={() => setSelectedId(r.run_id)}
                className={cn(
                  'w-full text-left rounded-lg border p-3 transition-colors',
                  r.run_id === selectedId
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:border-primary/40 hover:bg-secondary/40'
                )}
              >
                {/* Display name (if set) is primary; date is fallback. Date always shown as subtext. */}
                <div className="flex items-center gap-1.5">
                  <div className="text-sm font-semibold text-foreground truncate flex-1">
                    {r.display_name || (r.created_at ? formatDateTime(r.created_at) : 'unknown date')}
                  </div>
                  {r.status === 'running' && (
                    <span className="text-[9px] font-mono uppercase tracking-wider rounded border border-emerald-700/40 bg-emerald-950/30 text-emerald-300 px-1.5 py-0.5 flex items-center gap-1">
                      <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      live
                    </span>
                  )}
                  {r.status === 'stale' && (
                    <span className="text-[9px] font-mono uppercase tracking-wider rounded border border-amber-700/40 bg-amber-950/30 text-amber-300 px-1.5 py-0.5" title="No manifest written and last write >5 min ago — probably crashed or was killed">
                      stale
                    </span>
                  )}
                </div>
                {r.display_name && r.created_at && (
                  <div className="text-[10px] text-muted-foreground">
                    {formatDateTime(r.created_at)}
                  </div>
                )}
                {/* Raw run_id as small subtext */}
                <div
                  className="text-[9px] font-mono text-muted-foreground/70 truncate"
                  title={r.run_id}
                >
                  log/{r.run_id}
                </div>
                <div className="flex gap-3 mt-1.5 text-[10px] font-mono">
                  <span>
                    n=<span className="text-foreground">{r.total_trajectories}</span>
                  </span>
                  <span>
                    RankICIR=
                    <span className={cn('font-semibold', r.best_rank_icir && r.best_rank_icir > 0.05 ? 'text-emerald-300' : 'text-amber-300')}>
                      {r.best_rank_icir != null ? r.best_rank_icir.toFixed(4) : '—'}
                    </span>
                  </span>
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  IR={r.best_ir != null ? r.best_ir.toFixed(3) : '—'} · phase={r.current_phase || '—'}
                  {formatDuration(r.created_at, r.saved_at) && (
                    <> · <span className="font-mono text-foreground/80">{formatDuration(r.created_at, r.saved_at)}</span></>
                  )}
                </div>
                {/* Linkage chips */}
                {(r.linked_workspace || r.linked_library) && (
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {r.linked_workspace && (
                      <span
                        className="text-[9px] rounded border border-border bg-secondary/40 px-1.5 py-0.5 font-mono text-muted-foreground"
                        title={`Workspace: ${r.linked_workspace}${r.linkage_source ? ' (' + r.linkage_source + '-matched)' : ''}`}
                      >
                        ws: {r.linked_workspace.replace('workspace_', '')}
                      </span>
                    )}
                    {r.linked_library && (
                      <span
                        className="text-[9px] rounded border border-border bg-secondary/40 px-1.5 py-0.5 font-mono text-muted-foreground"
                        title={`Library: ${r.linked_library}`}
                      >
                        lib: {r.linked_library.replace('all_factors_library_', '').replace('.json', '')}
                      </span>
                    )}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Run detail */}
        <div className="lg:col-span-3 space-y-4">
          {!selectedId && (
            <Card>
              <CardContent className="py-6 text-center text-muted-foreground text-sm">
                Select a run on the left to see details, AI verdict, and lineage.
              </CardContent>
            </Card>
          )}
          {selectedId && detail.loading && (
            <Card>
              <CardContent className="py-6 flex items-center justify-center text-muted-foreground gap-2">
                <Loader2 className="size-4 animate-spin" /> Loading run…
              </CardContent>
            </Card>
          )}
          {selectedId && !detail.loading && detail.error && (
            <Card>
              <CardContent className="py-4 text-destructive text-sm">{detail.error}</CardContent>
            </Card>
          )}
          {selectedId && !detail.loading && !detail.error && detail.summary && (
            <>
              <Card>
                <CardContent className="py-4 space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-base font-semibold text-foreground flex items-center gap-2">
                        <FileText className="size-4" />
                        {detail.summary.display_name ||
                          (detail.summary.created_at
                            ? formatDateTime(detail.summary.created_at)
                            : detail.summary.run_id)}
                      </div>
                      {detail.summary.display_name && detail.summary.created_at && (
                        <div className="text-xs text-muted-foreground mt-0.5">
                          {formatDateTime(detail.summary.created_at)}
                        </div>
                      )}
                      <div
                        className="text-[10px] font-mono text-muted-foreground/70 mt-0.5 truncate"
                        title={detail.summary.run_id}
                      >
                        log/{detail.summary.run_id}
                      </div>
                      {detail.summary.objective && (
                        <div className="text-xs text-foreground/80 mt-1.5 italic line-clamp-2">
                          “{detail.summary.objective}”
                        </div>
                      )}
                      <div className="text-xs text-muted-foreground mt-1.5">
                        {detail.summary.total_trajectories} trajectories
                        {detail.summary.directions_completed > 0 && (
                          <>{' · '}{detail.summary.directions_completed} directions completed</>
                        )}
                        {formatDuration(detail.summary.created_at, detail.summary.saved_at) && (
                          <>
                            {' · '}duration{' '}
                            <span className="font-mono text-foreground/80">
                              {formatDuration(detail.summary.created_at, detail.summary.saved_at)}
                            </span>
                            {detail.summary.created_at && detail.summary.saved_at && (
                              <span className="text-muted-foreground/70">
                                {' '}({formatDateTime(detail.summary.created_at)} → {formatDateTime(detail.summary.saved_at)})
                              </span>
                            )}
                          </>
                        )}
                      </div>
                      {(detail.summary.linked_workspace || detail.summary.linked_library) && (
                        <div className="flex gap-2 mt-2 flex-wrap text-[11px]">
                          {detail.summary.linked_workspace && (
                            <span
                              className="rounded border border-border bg-secondary/40 px-2 py-0.5 font-mono text-foreground/80 flex items-center gap-1"
                              title={`Inferred via ${detail.summary.linkage_source || 'unknown'}`}
                            >
                              <Boxes className="size-3" />
                              {detail.summary.linked_workspace}
                            </span>
                          )}
                          {detail.summary.linked_library && (
                            <span className="rounded border border-border bg-secondary/40 px-2 py-0.5 font-mono text-foreground/80 flex items-center gap-1">
                              <Database className="size-3" />
                              {detail.summary.linked_library}
                            </span>
                          )}
                          {detail.summary.linkage_source === 'mtime' && (
                            <span className="rounded border border-amber-700/40 bg-amber-950/20 px-2 py-0.5 text-[9px] uppercase tracking-wider text-amber-300">
                              inferred
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 text-xs">
                    <Stat label="best RankICIR" value={detail.summary.best_rank_icir} fmt={4} good={(v) => v > 0.05} bad={(v) => v < 0.02} />
                    <Stat label="best IR" value={detail.summary.best_ir} fmt={3} good={(v) => v > 0.3} bad={(v) => v < 0} />
                    <Stat label="round" value={detail.summary.current_round} fmt={0} />
                    <Stat label="phase" textValue={detail.summary.current_phase || '—'} />
                  </div>
                  {Object.keys(detail.summary.by_phase).length > 0 && (
                    <div className="text-[11px] text-muted-foreground font-mono pt-1 border-t border-border">
                      by phase:{' '}
                      {Object.entries(detail.summary.by_phase)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(' · ')}
                    </div>
                  )}
                </CardContent>
              </Card>

              <AnalysisCard
                runId={detail.summary.run_id}
                analysis={detail.analysis}
                onAnalyzed={(a) => setDetail((d) => ({ ...d, analysis: a }))}
              />

              <Card>
                <CardContent className="py-4 space-y-2">
                  <div className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <GitBranch className="size-4" /> Lineage
                    <span className="text-[10px] font-normal text-muted-foreground ml-2">
                      Click a node for details
                    </span>
                  </div>
                  <LineageGraph
                    nodes={detail.lineage.nodes}
                    edges={detail.lineage.edges}
                    selectedId={selectedTrajId}
                    onSelect={(id) => setSelectedTrajId((cur) => (cur === id ? null : id))}
                    height={520}
                  />
                  <TrajectoryDetailPanel
                    selectedId={selectedTrajId}
                    nodes={detail.lineage.nodes}
                    pool={detail.pool}
                    onClose={() => setSelectedTrajId(null)}
                  />
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>

      <Card className="mt-6">
        <CardContent className="py-4 space-y-3 text-xs">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Metric reference — what RankICIR and IR mean, and how this app uses them
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <div className="font-mono text-foreground font-semibold">
                RankICIR
                <span className="font-sans font-normal text-muted-foreground ml-2">
                  Rank Information Coefficient · Information Ratio
                </span>
              </div>
              <p className="text-muted-foreground leading-relaxed">
                Daily Spearman rank-correlation between the factor's predicted scores and realized
                forward returns, divided by its std over the test period. In plain English:{' '}
                <em>"how consistently does this factor rank stocks correctly, day after day?"</em>
              </p>
              <div className="font-mono text-[10px] text-muted-foreground space-y-0.5 pt-1 border-t border-border">
                <div>&gt; 0.07 — strong (rare for a single factor)</div>
                <div>&gt; 0.05 — meaningful</div>
                <div>&gt; 0.03 — marginal</div>
                <div>&lt; 0.02 — noise</div>
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="font-mono text-foreground font-semibold">
                IR
                <span className="font-sans font-normal text-muted-foreground ml-2">
                  Information Ratio
                </span>
              </div>
              <p className="text-muted-foreground leading-relaxed">
                Annualized excess return (over benchmark) divided by tracking-error std, computed{' '}
                <em>after</em> transaction costs on the daily TopkDropout backtest. In plain English:{' '}
                <em>"how much profit does the factor produce per unit of risk, after fees?"</em>
              </p>
              <div className="font-mono text-[10px] text-muted-foreground space-y-0.5 pt-1 border-t border-border">
                <div>&gt; 0.5 — strong</div>
                <div>&gt; 0.3 — meaningful</div>
                <div>&gt; 0 — at least profitable</div>
                <div>&lt; 0 — loses money in execution</div>
              </div>
            </div>
          </div>

          <div className="rounded border border-amber-700/40 bg-amber-950/20 px-3 py-2 text-amber-200/90">
            <strong className="text-amber-200">Why both matter:</strong> a factor can have{' '}
            <em>positive RankICIR but negative IR</em> — it ranks stocks correctly on paper, but
            the simple top-decile portfolio still loses money after turnover costs / sector
            mismatch. That's the classic <strong>curve-fit smell</strong>; the AI verdict labels
            it <span className="font-mono">regime-fit</span>.
          </div>

          <div className="space-y-1 pt-2 border-t border-border">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              How this app uses these numbers
            </div>
            <ul className="space-y-1 text-muted-foreground leading-relaxed">
              <li>
                <strong className="text-foreground">Mining loop:</strong> ranks trajectories by RankICIR
                during evolution. Mutation operates on the lowest-RankICIR step; crossover picks high-RankICIR
                parents.
              </li>
              <li>
                <strong className="text-foreground">Auto-publish gate:</strong> top-5 factors with
                RankICIR &gt; 0.05 AND IR &gt; 0 (and max drawdown &gt; -40%) get auto-pushed to
                the findings repo.
              </li>
              <li>
                <strong className="text-foreground">AI verdict:</strong> {' '}
                <span className="font-mono text-emerald-300">robust</span> = RankICIR &gt; 0.06 AND
                IR &gt; 0.3 across rounds; {' '}
                <span className="font-mono text-amber-300">regime-fit</span> = positive RankICIR
                with negative IR; {' '}
                <span className="font-mono text-zinc-300">marginal</span> = RankICIR &lt; 0.04 with
                IR ≤ 0; {' '}
                <span className="font-mono text-red-300">broken</span> = mostly failed gates.
              </li>
              <li>
                <strong className="text-foreground">Suggester auto-pick:</strong> 1 run with
                RankICIR &gt; 0.04 → "refinement" (build on it); 2+ → "compose" (combine winners);
                else fallback to gap-fill / contrarian.
              </li>
            </ul>
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end mt-6">
        <Button variant="outline" size="sm" onClick={() => onNavigate?.('home')}>
          Back to home
        </Button>
      </div>
    </Layout>
  );
};

const Stat: React.FC<{
  label: string;
  value?: number | null;
  textValue?: string;
  fmt?: number;
  good?: (v: number) => boolean;
  bad?: (v: number) => boolean;
}> = ({ label, value, textValue, fmt = 2, good, bad }) => {
  let cls = 'text-foreground';
  let display: string;
  if (textValue !== undefined) {
    display = textValue;
  } else if (value === null || value === undefined) {
    display = '—';
    cls = 'text-muted-foreground';
  } else {
    display = value.toFixed(fmt);
    if (good?.(value)) cls = 'text-emerald-300';
    else if (bad?.(value)) cls = 'text-red-300';
  }
  return (
    <div className="rounded-md border border-border bg-secondary/30 px-3 py-2">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</div>
      <div className={cn('font-mono text-sm font-semibold', cls)}>{display}</div>
    </div>
  );
};
