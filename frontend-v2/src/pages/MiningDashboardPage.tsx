import React from 'react';
import { Boxes, Calendar, Tag } from 'lucide-react';
import { ProgressSidebar } from '@/components/ProgressSidebar';
import { LiveCharts } from '@/components/LiveCharts';
import { ChatInput } from '@/components/ChatInput';
import { FactorStatsRow } from '@/components/FactorStatsRow';
import { FactorList } from '@/components/FactorList';
import { LiveLineageSection } from '@/components/LiveLineageSection';
import { Card, CardContent } from '@/components/ui/Card';
import { useTaskContext } from '@/context/TaskContext';
import { Layout } from '@/components/layout/Layout';
import type { PageId } from '@/components/layout/Layout';
import type { TaskConfig } from '@/types';

interface MiningDashboardPageProps {
  onNavigate?: (page: PageId) => void;
}

export const MiningDashboardPage: React.FC<MiningDashboardPageProps> = ({ onNavigate }) => {
  const {
    miningTask: task,
    miningEquityCurve: equityCurve,
    miningDrawdownCurve: drawdownCurve,
    startMining,
    stopMining,
  } = useTaskContext();

  // If no task, this page shouldn't be active (or show empty state)
  if (!task) {
    return (
      <Layout
        currentPage="home"
        onNavigate={onNavigate || (() => {})}
        showNavigation={!!onNavigate}
      >
        <div className="flex flex-col items-center justify-center min-h-[60vh] animate-fade-in-up">
          <p className="text-muted-foreground">No mining task is currently running.</p>
          <button
            className="mt-4 text-primary hover:underline"
            onClick={() => onNavigate?.('home')}
          >
            Back to home
          </button>
        </div>
      </Layout>
    );
  }

  return (
    <Layout
      currentPage="home"
      onNavigate={onNavigate || (() => {})}
      showNavigation={!!onNavigate}
    >
      <RunConfigCard config={task.config as TaskConfig} taskId={task.taskId} />

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 mt-4">
        <div className="lg:col-span-1">
          <ProgressSidebar progress={task.progress} />
        </div>
        <div className="lg:col-span-3">
          <LiveCharts
            equityCurve={equityCurve}
            drawdownCurve={drawdownCurve}
            metrics={task.metrics || null}
            isRunning={task.status === 'running'}
            logs={task.logs}
          />
        </div>

        {/* New Rows - Full Width */}
        <div className="lg:col-span-4">
           <FactorStatsRow 
             metrics={task.metrics || null} 
             onBacktest={() => {
               // Set active library for backtest page
               if (task.config?.librarySuffix) {
                 const libName = `all_factors_library_${task.config.librarySuffix}.json`;
                 localStorage.setItem('quantaalpha_active_library', libName);
               } else {
                 localStorage.setItem('quantaalpha_active_library', 'all_factors_library.json');
               }
               onNavigate?.('backtest');
             }}
           />
        </div>
        <div className="lg:col-span-4">
           <FactorList metrics={task.metrics || null} />
        </div>
        <div className="lg:col-span-4">
          <LiveLineageSection
            isRunning={task.status === 'running'}
            taskId={task.taskId}
            taskCreatedAt={task.createdAt}
          />
        </div>
      </div>

      {/* Bottom Chat Input — hidden while a task is running so users
          aren't prompted to start a new run mid-flight. Re-appears once
          the current task is completed/failed/cancelled so a fresh run
          can be kicked off from this page. */}
      {task.status !== 'running' && (
        <ChatInput
          onSubmit={startMining}
          onStop={stopMining}
          isRunning={false}
        />
      )}
    </Layout>
  );
};

// ─── Run config card (shows what the active run is using) ──────────────────

const RunConfigCard: React.FC<{ config: TaskConfig; taskId: string }> = ({ config, taskId }) => {
  const universe = config.universe || 'sp500';
  const isCustom = universe === 'custom';
  const tickers = config.customTickers || [];
  const trainStart = config.trainStart || '2008-01-02';
  const trainEnd = config.trainEnd || '2015-12-31';
  const validStart = config.validStart || '2016-01-04';
  const validEnd = config.validEnd || '2016-12-30';
  const testStart = config.testStart || '2017-01-03';
  const testEnd = config.testEnd || '2026-05-07';

  const displayName = config.displayName?.trim();

  return (
    <Card>
      <CardContent className="py-3 px-4 space-y-2">
        {/* Header — display name + raw task id */}
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <div className="text-base font-semibold text-foreground">
              {displayName || 'Mining run'}
            </div>
            <div className="text-[10px] font-mono text-muted-foreground/70">
              task {taskId}
              {config.librarySuffix && (
                <> · suffix <code>{config.librarySuffix}</code></>
              )}
            </div>
          </div>
          <div className="text-[10px] font-mono text-muted-foreground">
            {config.numDirections ?? '?'} directions × {config.maxRounds ?? '?'} rounds
          </div>
        </div>

        {/* 3 inline cells: universe / dates / extras */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs pt-2 border-t border-border">
          {/* Universe */}
          <div className="space-y-0.5">
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
              <Boxes className="size-3" /> Universe
            </div>
            <div className="font-mono text-foreground font-semibold">
              {isCustom ? `custom (${tickers.length} tickers)` : universe}
            </div>
            {isCustom && tickers.length > 0 && (
              <div
                className="font-mono text-[10px] text-muted-foreground/80 truncate"
                title={tickers.join(', ')}
              >
                {tickers.slice(0, 8).join(', ')}
                {tickers.length > 8 && ` +${tickers.length - 8} more`}
              </div>
            )}
          </div>

          {/* Date splits */}
          <div className="space-y-0.5">
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
              <Calendar className="size-3" /> Date splits
            </div>
            <div className="font-mono text-[11px] text-foreground/90 leading-relaxed">
              <div>train <span className="text-muted-foreground">{trainStart} → {trainEnd}</span></div>
              <div>valid <span className="text-muted-foreground">{validStart} → {validEnd}</span></div>
              <div>test <span className="text-muted-foreground">{testStart} → {testEnd}</span></div>
            </div>
          </div>

          {/* Extras */}
          <div className="space-y-0.5">
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
              <Tag className="size-3" /> Run options
            </div>
            <div className="font-mono text-[11px] text-foreground/90 leading-relaxed">
              <div>parallel: <span className="text-muted-foreground">
                {config.parallelExecution ? 'on' : 'off'}
              </span></div>
              <div>quality gate: <span className="text-muted-foreground">
                {config.qualityGateEnabled !== false ? 'on' : 'off'}
              </span></div>
              {config.useCustomMiningDirection && (
                <div className="text-primary">using preset direction (Settings)</div>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
