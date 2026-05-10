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
}

export const LiveLineageSection: React.FC<LiveLineageSectionProps> = ({
  isRunning,
  pollMs = 15000,
}) => {
  const [run, setRun] = React.useState<RunSummary | null>(null);
  const [pool, setPool] = React.useState<any | null>(null);
  const [nodes, setNodes] = React.useState<LineageNode[]>([]);
  const [edges, setEdges] = React.useState<LineageEdge[]>([]);
  const [selectedTrajId, setSelectedTrajId] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const listRes = await listRuns();
      if (!listRes.success || !listRes.data) {
        setError(listRes.error || 'Failed to list runs');
        return;
      }
      const sorted = [...(listRes.data.runs || [])].sort((a, b) =>
        (b.created_at || '').localeCompare(a.created_at || '')
      );
      const latest = sorted[0] || null;
      setRun(latest);
      if (!latest) return;

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
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  React.useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [isRunning, pollMs, refresh]);

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
              ? 'Waiting for the first trajectory to land…'
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
