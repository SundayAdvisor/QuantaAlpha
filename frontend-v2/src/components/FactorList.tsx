import React from 'react';
import {
  AreaChart,
  Area,
  ResponsiveContainer,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/HoverCard";
import { RealtimeMetrics } from '@/types';
import { formatNumber, formatPercent } from '@/utils';
import { TrendingUp } from 'lucide-react';

interface FactorListProps {
  metrics: RealtimeMetrics | null;
}

export const FactorList: React.FC<FactorListProps> = ({ metrics }) => {
  const truncate = (val: unknown, max: number) => {
    if (val === null || val === undefined) return '';
    // Some library entries arrive as arrays (a hypothesis groups N factors).
    // Join them so the cell shows "Name1, Name2, Name3" instead of the raw
    // list literal that React stringifies as "Name1,Name2,Name3" (or worse,
    // a Python-style "['Name1', ...]" if the backend pre-stringified it).
    let str: string;
    if (Array.isArray(val)) {
      str = val.map(v => String(v)).join(', ');
    } else if (typeof val === 'string' && val.startsWith('[') && val.endsWith(']')) {
      // Backend sometimes serialises a Python list via repr; strip the outer brackets/quotes.
      try {
        const parsed = JSON.parse(val.replace(/'/g, '"'));
        str = Array.isArray(parsed) ? parsed.map(v => String(v)).join(', ') : val;
      } catch {
        str = val;
      }
    } else {
      str = String(val);
    }
    return str.length > max ? str.substring(0, max) + '...' : str;
  };

  const formatMetric = (value: number | undefined | null, type: 'number' | 'percent' = 'number') => {
    if (value === undefined || value === null || value === 0) return <span className="text-muted-foreground/50">N/A</span>;
    return type === 'percent' ? formatPercent(value) : formatNumber(value, 4);
  };

  return (
    <Card className="glass card-hover animate-fade-in-up w-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-purple-500 animate-pulse" />
          CurrentFactor Library RankIC Top 10
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50">
                <th className="py-3 px-4 text-left font-medium text-muted-foreground w-1/6">Factor name</th>
                <th className="py-3 px-4 text-left font-medium text-muted-foreground w-1/4">Formula</th>
                <th className="py-3 px-4 text-right font-medium text-muted-foreground">IC</th>
                <th className="py-3 px-4 text-right font-medium text-muted-foreground">RankIC</th>
                <th className="py-3 px-4 text-right font-medium text-muted-foreground">ICIR</th>
                <th className="py-3 px-4 text-right font-medium text-muted-foreground">RankICIR</th>
                <th className="py-3 px-4 text-right font-medium text-muted-foreground">ARR</th>
                <th className="py-3 px-4 text-right font-medium text-muted-foreground">MDD</th>
                <th className="py-3 px-4 text-right font-medium text-muted-foreground">Sharpe</th>
              </tr>
            </thead>
            <tbody>
              {metrics?.top10Factors && metrics.top10Factors.length > 0 ? (
                metrics.top10Factors.map((factor, index) => (
                  <HoverCard key={index} openDelay={200}>
                    <HoverCardTrigger asChild>
                      <tr className="group hover:bg-muted/50 transition-colors border-b border-border/50 last:border-0 cursor-help">
                        <td className="py-3 px-4 font-medium max-w-[150px] truncate" title={truncate(factor.factorName, 200)}>
                          {truncate(factor.factorName, 15)}
                        </td>
                        <td className="py-3 px-4 font-mono text-xs text-muted-foreground max-w-[200px] truncate">
                          {truncate(factor.factorExpression, 30)}
                        </td>
                        <td className="py-3 px-4 text-right font-mono">{formatMetric(factor.ic)}</td>
                        <td className="py-3 px-4 text-right font-mono font-bold text-primary">{formatMetric(factor.rankIc)}</td>
                        <td className="py-3 px-4 text-right font-mono">{formatMetric(factor.icir)}</td>
                        <td className="py-3 px-4 text-right font-mono">{formatMetric(factor.rankIcir)}</td>
                        <td className="py-3 px-4 text-right font-mono text-success">{formatMetric(factor.annualReturn, 'percent')}</td>
                        <td className="py-3 px-4 text-right font-mono text-destructive">{formatMetric(factor.maxDrawdown, 'percent')}</td>
                        <td className="py-3 px-4 text-right font-mono">{formatMetric(factor.sharpeRatio)}</td>
                      </tr>
                    </HoverCardTrigger>
                    <HoverCardContent 
                      className="w-[400px] glass-strong p-4 shadow-xl border border-primary/20" 
                      side="top" 
                      align="center"
                      sideOffset={10}
                      collisionPadding={20}
                      avoidCollisions={true}
                      style={{ zIndex: 1000 }}
                    >
                      <div className="space-y-4">
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <h4 className="font-bold text-primary text-base">{truncate(factor.factorName, 200)}</h4>
                            <div className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-medium border border-primary/20">
                               Score: {formatNumber(factor.rankIc * 100, 1)}
                            </div>
                          </div>
                          <div className="p-3 bg-secondary/40 rounded-lg font-mono text-xs break-all border border-border/50 text-foreground/90 shadow-inner">
                            {truncate(factor.factorExpression, 1000)}
                          </div>
                        </div>
                        
                        <div className="grid grid-cols-2 gap-3 p-3 bg-background/40 rounded-lg border border-border/30">
                          <div>
                            <span className="text-xs text-muted-foreground block mb-0.5">Ann. Return (ARR)</span>
                            <span className="font-bold text-success text-sm">{formatPercent(factor.annualReturn || 0)}</span>
                          </div>
                          <div>
                            <span className="text-xs text-muted-foreground block mb-0.5">Sharpe Ratio (Sharpe)</span>
                            <span className="font-bold text-sm">{formatNumber(factor.sharpeRatio || 0, 2)}</span>
                          </div>
                          <div>
                            <span className="text-xs text-muted-foreground block mb-0.5">Max Drawdown (MDD)</span>
                            <span className="font-bold text-destructive text-sm">{formatPercent(factor.maxDrawdown || 0)}</span>
                          </div>
                          <div>
                            <span className="text-xs text-muted-foreground block mb-0.5">Calmar Ratio (CR)</span>
                            <span className="font-bold text-primary text-sm">{formatNumber(factor.calmarRatio || 0, 2)}</span>
                          </div>
                        </div>

                      </div>
                    </HoverCardContent>
                  </HoverCard>
                ))
              ) : (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-muted-foreground">
                    No Factor countdata
                  </td>
                </tr>
              )}

            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
};
