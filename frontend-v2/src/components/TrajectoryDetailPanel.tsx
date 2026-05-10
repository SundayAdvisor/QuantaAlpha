import React from 'react';
import type { LineageNode } from '@/types';
import { cn } from '@/utils';

interface TrajectoryDetailPanelProps {
  selectedId: string | null;
  nodes: LineageNode[];
  pool: any | null;
  onClose: () => void;
}

export const TrajectoryDetailPanel: React.FC<TrajectoryDetailPanelProps> = ({
  selectedId,
  nodes,
  pool,
  onClose,
}) => {
  if (!selectedId) return null;
  const node = nodes.find((n) => n.id === selectedId) || null;
  const traj: any = pool?.trajectories?.[selectedId] || null;
  if (!node && !traj) {
    return (
      <div className="mt-3 rounded-md border border-border bg-secondary/30 p-3 text-xs text-muted-foreground">
        Trajectory <span className="font-mono">{selectedId.slice(0, 8)}</span> not found in this run.
        <button onClick={onClose} className="ml-2 underline hover:text-foreground">close</button>
      </div>
    );
  }
  const factors: any[] = traj?.factors || [];
  const feedback: string = traj?.feedback || '';
  const phase = node?.phase || traj?.phase || 'unknown';
  const round = node?.round ?? traj?.round_idx;
  const direction = node?.direction_id ?? traj?.direction_id;
  const parentIds: string[] = traj?.parent_ids || [];
  return (
    <div className="mt-3 rounded-md border border-primary/40 bg-primary/5 p-3 space-y-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-foreground font-semibold flex items-center gap-2 flex-wrap">
            <span>{selectedId.slice(0, 8)}</span>
            <span className="text-[10px] uppercase tracking-wider rounded border border-border bg-secondary/40 px-1.5 py-0.5 text-muted-foreground">
              {phase}
            </span>
            {round !== undefined && round !== null && (
              <span className="text-[10px] text-muted-foreground">round {round}</span>
            )}
            {direction !== undefined && direction !== null && (
              <span className="text-[10px] text-muted-foreground">dir {direction}</span>
            )}
          </div>
          {parentIds.length > 0 && (
            <div className="text-[10px] text-muted-foreground mt-0.5 font-mono">
              parents: {parentIds.map((p) => p.slice(0, 8)).join(', ')}
            </div>
          )}
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xs">
          close
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <MiniStat label="RankICIR" value={node?.rank_icir ?? null} fmt={4} good={(v) => v > 0.05} bad={(v) => v < 0.02} />
        <MiniStat label="IR" value={node?.ir ?? null} fmt={3} good={(v) => v > 0.3} bad={(v) => v < 0} />
        <MiniStat label="IC" value={node?.ic ?? null} fmt={4} />
        <MiniStat label="ann_ret" value={node?.ann_ret ?? null} fmt={3} />
        <MiniStat label="max_dd" value={node?.max_dd ?? null} fmt={3} bad={(v) => v < -0.4} />
      </div>

      {(node?.hypothesis || traj?.hypothesis) && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Hypothesis</div>
          <p className="text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-6">
            {node?.hypothesis || traj?.hypothesis}
          </p>
        </div>
      )}

      {factors.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Factors ({factors.length})
          </div>
          <div className="space-y-1.5">
            {factors.map((f: any, i: number) => (
              <div key={i} className="rounded border border-border bg-background/40 p-2">
                <div className="font-mono text-foreground text-[11px]">{f.name}</div>
                <div className="font-mono text-muted-foreground text-[10px] break-all mt-0.5">
                  {f.expression}
                </div>
                {f.description && (
                  <div className="text-[10px] text-foreground/70 mt-1 line-clamp-2">{f.description}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {feedback && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Feedback</div>
          <p className="text-muted-foreground leading-relaxed line-clamp-4">{feedback}</p>
        </div>
      )}
    </div>
  );
};

const MiniStat: React.FC<{
  label: string;
  value?: number | null;
  fmt?: number;
  good?: (v: number) => boolean;
  bad?: (v: number) => boolean;
}> = ({ label, value, fmt = 2, good, bad }) => {
  let cls = 'text-foreground';
  let display: string;
  if (value === null || value === undefined) {
    display = '—';
    cls = 'text-muted-foreground';
  } else {
    display = value.toFixed(fmt);
    if (good?.(value)) cls = 'text-emerald-300';
    else if (bad?.(value)) cls = 'text-red-300';
  }
  return (
    <div className="rounded-md border border-border bg-secondary/30 px-2 py-1.5">
      <div className="text-[9px] text-muted-foreground uppercase tracking-wider">{label}</div>
      <div className={cn('font-mono text-xs font-semibold', cls)}>{display}</div>
    </div>
  );
};
