import React from 'react';
import { ChevronDown, GitMerge, Sparkles } from 'lucide-react';

import type { LineageEdge, LineageNode } from '@/types';
import { cn } from '@/utils';

interface LineageGraphProps {
  nodes: LineageNode[];
  edges: LineageEdge[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  height?: number;
  showLegend?: boolean;
}

const PHASE_COLORS: Record<string, string> = {
  original: 'border-zinc-500 bg-zinc-800/80 text-zinc-200',
  mutation: 'border-violet-500 bg-violet-950/60 text-violet-100',
  crossover: 'border-cyan-500 bg-cyan-950/60 text-cyan-100',
  optimized: 'border-amber-500 bg-amber-950/60 text-amber-100',
};

const EDGE_COLORS: Record<string, string> = {
  original: '#52525b',
  mutation: '#a78bfa',
  crossover: '#22d3ee',
  optimized: '#fbbf24',
};

const COL_WIDTH = 220;
const ROW_HEIGHT = 130;
const NODE_WIDTH = 180;
const NODE_HEIGHT = 90;
const PADDING_X = 30;
const PADDING_Y = 20;

interface PositionedNode extends LineageNode {
  x: number;
  y: number;
}

/**
 * Visualizes parent → mutation/crossover → child relationships.
 * Layout: column = direction_id, row = round_idx. SVG-based, no
 * external graph library required.
 */
export const LineageGraph: React.FC<LineageGraphProps> = ({
  nodes,
  edges,
  selectedId,
  onSelect,
  height = 480,
  showLegend = true,
}) => {
  const layout = React.useMemo(() => {
    if (nodes.length === 0) {
      return { positioned: [] as PositionedNode[], width: 0, totalHeight: 0, byId: new Map<string, PositionedNode>() };
    }
    const directions = Array.from(new Set(nodes.map((n) => n.direction_id ?? 0))).sort((a, b) => a - b);
    const rounds = Array.from(new Set(nodes.map((n) => n.round ?? 0))).sort((a, b) => a - b);
    const dirIdx = new Map<number, number>(directions.map((d, i) => [d, i]));
    const roundIdx = new Map<number, number>(rounds.map((r, i) => [r, i]));

    const bucketKey = (n: LineageNode) => `${n.round ?? 0}::${n.direction_id ?? 0}`;
    const bucketSize = new Map<string, number>();
    nodes.forEach((n) => {
      const k = bucketKey(n);
      bucketSize.set(k, (bucketSize.get(k) ?? 0) + 1);
    });
    const bucketSeen = new Map<string, number>();

    const positioned: PositionedNode[] = nodes.map((node) => {
      const col = dirIdx.get(node.direction_id ?? 0) ?? 0;
      const row = roundIdx.get(node.round ?? 0) ?? 0;
      const k = bucketKey(node);
      const bSize = bucketSize.get(k) ?? 1;
      const bIdx = bucketSeen.get(k) ?? 0;
      bucketSeen.set(k, bIdx + 1);
      const offset = bSize > 1 ? (bIdx - (bSize - 1) / 2) * (COL_WIDTH / Math.max(bSize, 2)) * 0.9 : 0;
      return {
        ...node,
        x: PADDING_X + col * COL_WIDTH + offset,
        y: PADDING_Y + row * ROW_HEIGHT,
      };
    });

    const width = PADDING_X * 2 + Math.max(directions.length, 1) * COL_WIDTH;
    const totalHeight = PADDING_Y * 2 + Math.max(rounds.length, 1) * ROW_HEIGHT;
    const byId = new Map(positioned.map((n) => [n.id, n]));
    return { positioned, width, totalHeight, byId };
  }, [nodes]);

  if (nodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-muted-foreground text-sm border border-border rounded-lg"
        style={{ height }}
      >
        No lineage to show — start a run to see how mutation and crossover produce child trajectories.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {showLegend && <LineageLegend />}
      <div
        className="rounded-lg border border-border overflow-auto bg-secondary/20"
        style={{ maxHeight: height }}
      >
        <svg
          width={Math.max(layout.width, 320)}
          height={Math.max(layout.totalHeight, 200)}
          style={{ display: 'block' }}
        >
          <defs>
            {Object.entries(EDGE_COLORS).map(([k, color]) => (
              <marker
                key={k}
                id={`arrow-${k}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
              </marker>
            ))}
          </defs>

          {/* Edges first, behind nodes */}
          {edges.map((e, i) => {
            const src = layout.byId.get(e.source);
            const tgt = layout.byId.get(e.target);
            if (!src || !tgt) return null;
            const childPhase = (tgt.phase || 'original') as string;
            const color = EDGE_COLORS[childPhase] || EDGE_COLORS.original;
            const x1 = src.x + NODE_WIDTH / 2;
            const y1 = src.y + NODE_HEIGHT;
            const x2 = tgt.x + NODE_WIDTH / 2;
            const y2 = tgt.y;
            const midY = (y1 + y2) / 2;
            return (
              <path
                key={`e${i}`}
                d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
                stroke={color}
                strokeWidth={2}
                fill="none"
                opacity={0.85}
                markerEnd={`url(#arrow-${childPhase})`}
              />
            );
          })}

          {/* Nodes */}
          {layout.positioned.map((n) => (
            <foreignObject
              key={n.id}
              x={n.x}
              y={n.y}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              style={{ overflow: 'visible' }}
            >
              <div
                onClick={() => onSelect?.(n.id)}
                className={cn(
                  'p-2 rounded-md text-xs space-y-1 border cursor-pointer transition-all',
                  PHASE_COLORS[n.phase] || PHASE_COLORS.original,
                  n.id === selectedId && 'ring-2 ring-violet-400'
                )}
                style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] opacity-70">{n.id.slice(0, 8)}</span>
                  <span className="text-[10px] uppercase opacity-80">{n.phase || '?'}</span>
                </div>
                <div className="font-mono text-[11px]">
                  RankICIR:{' '}
                  <span className={n.rank_icir !== null && n.rank_icir > 0 ? 'text-emerald-300' : 'text-red-300'}>
                    {n.rank_icir !== null && n.rank_icir !== undefined ? n.rank_icir.toFixed(4) : '—'}
                  </span>
                </div>
                <div className="font-mono text-[11px]">
                  IR:{' '}
                  <span className={n.ir !== null && n.ir > 0 ? 'text-emerald-300' : 'text-amber-300'}>
                    {n.ir !== null && n.ir !== undefined ? n.ir.toFixed(3) : '—'}
                  </span>
                </div>
                <div className="text-[10px] opacity-60">
                  round {n.round ?? '?'} · dir {n.direction_id ?? '?'}
                </div>
              </div>
            </foreignObject>
          ))}
        </svg>
      </div>
    </div>
  );
};

const LineageLegend: React.FC = () => (
  <div className="flex flex-wrap items-center gap-4 px-3 py-2 rounded-md border border-border bg-secondary/30 text-xs">
    <div className="flex items-center gap-1.5 text-muted-foreground">
      <Sparkles className="size-3.5" />
      <span>Columns:</span>
      <span className="text-foreground">parallel directions</span>
    </div>
    <div className="flex items-center gap-1.5 text-muted-foreground">
      <ChevronDown className="size-3.5 text-violet-400" />
      <span>Mutation:</span>
      <span className="text-violet-300">parent → refined child</span>
    </div>
    <div className="flex items-center gap-1.5 text-muted-foreground">
      <GitMerge className="size-3.5 text-cyan-400" />
      <span>Crossover:</span>
      <span className="text-cyan-300">two parents → merged child</span>
    </div>
  </div>
);
