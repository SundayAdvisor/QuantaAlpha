import React from 'react';
import { GitBranch, Loader2, RefreshCw } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/Card';
import { LineageGraph } from '@/components/LineageGraph';
import { TrajectoryDetailPanel } from '@/components/TrajectoryDetailPanel';
import { listRuns, getRun, getRunLineage } from '@/services/api';
import type { LineageEdge, LineageNode, RunSummary } from '@/types';

interface LiveLineageSectionProps {
  isRunning: boolean;
  pollMs?: number;
  /** Active mining task id — used to reset local state when a new task starts. */
  taskId?: string | null;
  /** Active task's createdAt ISO string — used to filter out older runs from
   * the list so we don't show the previous run while the new run dir is
   * still being created on disk. */
  taskCreatedAt?: string | null;
}

export const LiveLineageSection: React.FC<LiveLineageSectionProps> = ({
  isRunning,
  pollMs = 15000,
  taskId,
  taskCreatedAt,
}) => {
  const [run, setRun] = React.useState<RunSummary | null>(null);
  const [pool, setPool] = React.useState<any | null>(null);
  const [nodes, setNodes] = React.useState<LineageNode[]>([]);
  const [edges, setEdges] = React.useState<LineageEdge[]>([]);
  const [selectedTrajId, setSelectedTrajId] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [waitingForRun, setWaitingForRun] = React.useState(false);

  // Grace window: backend's run dir mtime can drift slightly from when the
  // mining task's createdAt was stamped on the FE side. 60 seconds covers
  // clock skew and the gap between FE submit and worker spawn.
  const TASK_GRACE_MS = 60_000;

  const refresh = React.useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const listRes = await listRuns();
      if (!listRes.success || !listRes.data) {
        setError(listRes.error || 'Failed to list runs');
        return;
      }
      let runs = [...(listRes.data.runs || [])];
      // Filter out runs created BEFORE the current task started — these are
      // stale (the previous run we don't want to show as "live").
      if (taskCreatedAt) {
        const taskMs = Date.parse(taskCreatedAt);
        if (Number.isFinite(taskMs)) {
          runs = runs.filter((r) => {
            if (!r.created_at) return false;
            const rMs = Date.parse(r.created_at);
            return Number.isFinite(rMs) && rMs >= taskMs - TASK_GRACE_MS;
          });
        }
      }
      const sorted = runs.sort((a, b) =>
        (b.created_at || '').localeCompare(a.created_at || '')
      );
      const latest = sorted[0] || null;
      if (!latest) {
        // No matching run yet — likely the new run dir hasn't been created on
        // disk. Keep state cleared and signal to the user.
        setRun(null);
        setPool(null);
        setNodes([]);
        setEdges([]);
        setWaitingForRun(!!taskCreatedAt);
        return;
      }
      setWaitingForRun(false);
      setRun(latest);

      const [runRes, lineRes] = await Promise.all([
        getRun(latest.run_id),
        getRunLineage(latest.run_id),
      ]);
      if (runRes.success && runRes.data) setPool(runRes.data.pool);
      if (lineRes.success && lineRes.data) {
        setNodes(lineRes.data.nodes || []);
        setEdges(lineRes.data.edges || []);
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to load lineage');
    } finally {
      setRefreshing(false);
    }
  }, [taskCreatedAt]);

  // Reset displayed state IMMEDIATELY when a new task starts (taskId changes)
  // so the previous run is never visible while we wait for the new run dir
  // to appear on disk. Then trigger an immediate refresh.
  React.useEffect(() => {
    setRun(null);
    setPool(null);
    setNodes([]);
    setEdges([]);
    setSelectedTrajId(null);
    setWaitingForRun(!!taskCreatedAt);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  React.useEffect(() => {
    if (!isRunning) return;
    // Poll fast (3s) while we don't yet have a matching run on disk —
    // catches the new run dir as soon as the worker creates it. Once we
    // have a run, settle into the normal pollMs cadence.
    const interval = waitingForRun ? 3000 : pollMs;
    const id = setInterval(refresh, interval);
    return () => clearInterval(id);
  }, [isRunning, pollMs, refresh, waitingForRun]);

  return (
    <Card>
      <CardContent className="py-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-foreground flex items-center gap-2">
            <GitBranch className="size-4" /> Live lineage
            {isRunning && (
              <span className="text-[10px] font-mono text-emerald-300 rounded border border-emerald-700/40 bg-emerald-950/30 px-1.5 py-0.5 uppercase tracking-wider">
                live
              </span>
            )}
            <span className="text-[10px] font-normal text-muted-foreground ml-2">
              Click a node for details · refreshes every {Math.round(pollMs / 1000)}s
            </span>
          </div>
          <button
            onClick={refresh}
            disabled={refreshing}
            className="text-muted-foreground hover:text-foreground"
            title="Refresh now"
          >
            {refreshing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          </button>
        </div>

        {error && (
          <div className="text-xs text-destructive">{error}</div>
        )}

        {!error && nodes.length === 0 && (
          <div className="text-xs text-muted-foreground py-4 text-center">
            {isRunning
              ? (waitingForRun
                  ? 'Waiting for the new run to start writing trajectories…'
                  : 'Waiting for the first trajectory to land…')
              : 'No trajectories produced yet.'}
          </div>
        )}

        {nodes.length > 0 && (
          <>
            {run && (
              <div className="text-[10px] font-mono text-muted-foreground/80">
                run <span className="text-foreground/80">{run.run_id}</span>
                {' · '}
                <span>{nodes.length} trajectories</span>
                {run.current_round != null && (
                  <> {' · '} round {run.current_round}</>
                )}
                {run.current_phase && (
                  <> {' · '} phase {run.current_phase}</>
                )}
              </div>
            )}
            <LineageGraph
              nodes={nodes}
              edges={edges}
              selectedId={selectedTrajId}
              onSelect={(id) => setSelectedTrajId((cur) => (cur === id ? null : id))}
              height={420}
            />
            <TrajectoryDetailPanel
              selectedId={selectedTrajId}
              nodes={nodes}
              pool={pool}
              onClose={() => setSelectedTrajId(null)}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
};
