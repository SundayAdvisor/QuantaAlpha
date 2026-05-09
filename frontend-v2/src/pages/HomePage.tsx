import React from 'react';
import { ChatInput } from '@/components/ChatInput';
import { ObjectiveSuggester } from '@/components/ObjectiveSuggester';
import { Layout } from '@/components/layout/Layout';
import type { PageId } from '@/components/layout/Layout';
import { useTaskContext } from '@/context/TaskContext';

// -------------------------------------------------------------------
// Component
// -------------------------------------------------------------------

interface HomePageProps {
  onNavigate?: (page: PageId) => void;
}

export const HomePage: React.FC<HomePageProps> = ({ onNavigate }) => {
  const {
    backendAvailable,
    miningTask: task,
    startMining,
    stopMining,
  } = useTaskContext();

  const [chatValue, setChatValue] = React.useState('');

  return (
    <Layout
      currentPage="home"
      onNavigate={onNavigate || (() => {})}
      showNavigation={!!onNavigate}
    >
        {/* Welcome Screen - leave some space at the bottom to avoid overlapping with fixed input area */}
        <div className="flex flex-col items-center justify-center min-h-[60vh] pb-8 animate-fade-in-up">
          <div className="text-center mb-10">
            <h2 className="text-4xl font-bold mb-4 bg-gradient-to-r from-primary via-purple-500 to-pink-500 bg-clip-text text-transparent">
              Welcome to QuantaAlpha
            </h2>
            <p className="text-lg text-muted-foreground">
              Describe your research direction in natural language — the AI mines high-quality quantitative factors automatically.
            </p>
            {backendAvailable === false && (
              <p className="text-sm text-warning mt-2">
                Backend not connected — running with simulated data.
              </p>
            )}
            {backendAvailable === true && (
              <p className="text-sm text-success mt-2">
                Connected to backend service.
              </p>
            )}
          </div>

          {/* Feature Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl w-full mb-10">
            <div className="glass rounded-2xl p-6 card-hover text-center cursor-pointer" onClick={() => onNavigate?.('home')}>
              <div className="text-4xl mb-3">🤖</div>
              <h3 className="font-semibold mb-2">AI Factor Mining</h3>
              <p className="text-sm text-muted-foreground">
                LLM understands your goal, generates factor hypotheses, and evolves them over rounds.
              </p>
            </div>
            <div className="glass rounded-2xl p-6 card-hover text-center cursor-pointer" onClick={() => onNavigate?.('library')}>
              <div className="text-4xl mb-3">📊</div>
              <h3 className="font-semibold mb-2">Factor Library</h3>
              <p className="text-sm text-muted-foreground">
                Browse, filter, and analyze every factor that has been mined.
              </p>
            </div>
            <div className="glass rounded-2xl p-6 card-hover text-center cursor-pointer" onClick={() => onNavigate?.('backtest')}>
              <div className="text-4xl mb-3">🚀</div>
              <h3 className="font-semibold mb-2">Independent Backtest</h3>
              <p className="text-sm text-muted-foreground">
                Pick a factor library and run a full out-of-sample backtest with real metrics.
              </p>
            </div>
          </div>

          {/* AI Direction Suggester */}
          <div className="w-full max-w-4xl glass rounded-2xl p-6 mb-6">
            <h4 className="font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="text-lg">✨</span> Need a starting point?
            </h4>
            <ObjectiveSuggester onPick={(text) => setChatValue(text)} />
          </div>

          {/* System Info Panel */}
          <div className="w-full max-w-4xl glass rounded-2xl p-6 text-sm space-y-3">
            <h4 className="font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="text-lg">💡</span> Quick reference
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2 text-muted-foreground">

              <div className="flex items-start gap-2">
                <span className="text-primary mt-0.5">&#9679;</span>
                <span>
                  <strong className="text-foreground">Default universe:</strong> SP500 (US equities) — 547 tickers
                  with continuous data through May 2026. Other universes (NASDAQ, sector ETFs, gold/commodities)
                  not yet fetched; LLM auto-pick by objective is on the roadmap. Configurable in <code>configs/backtest.yaml</code>.
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-primary mt-0.5">&#9679;</span>
                <span>
                  <strong className="text-foreground">Available data:</strong> 1999-12-31 → 2026-05-07 (~6,627
                  trading days). Default config still uses paper-aligned splits — see below — but you can extend
                  backtests to today via <code>configs/experiment.yaml</code>.
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-primary mt-0.5">&#9679;</span>
                <span>
                  <strong className="text-foreground">Mining splits (in-sample):</strong>{' '}
                  Train <code>2008-01-02 → 2015-12-31</code> (fits LightGBM),
                  {' '}Valid <code>2016</code> (early-stop), Test <code>2017-01-03 → 2020-11-04</code>{' '}
                  (the IC / RankICIR / IR you see in <em>History</em>).
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-warning mt-0.5">&#9679;</span>
                <span>
                  <strong className="text-foreground">Subtlety: "test" is in-sample for the mining loop.</strong>{' '}
                  Mutation/crossover pick parents by their test-segment RankICIR, so mining sees and
                  optimizes for those scores. A factor's reported test RankICIR is not a true held-out
                  number — it's still useful for ranking trajectories against each other, but don't read
                  it as "this factor will work live."
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-success mt-0.5">&#9679;</span>
                <span>
                  <strong className="text-foreground">Genuine OOS window:</strong>{' '}
                  <code>2020-11-11 → 2026-05-07</code> (~5.5 yr) — never touched by any mining run, just
                  freshly fetched. Validate a factor honestly by extracting it to a Phase-5 bundle, then
                  running <code>predict_with_production_model.py</code> over this range. Covers the 2021
                  vol regime, 2022 bear, 2023 small-cap rotation, 2024 AI rally.
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-primary mt-0.5">&#9679;</span>
                <span><strong className="text-foreground">Resource cost:</strong> LLM tokens and wall time scale with <strong className="text-foreground">(evolution rounds × parallel directions)</strong>.</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-primary mt-0.5">&#9679;</span>
                <span><strong className="text-foreground">Base factors:</strong> Each new factor is combined with 4 base factors (open return, volume ratio, range return, daily return) before the preliminary backtest.</span>
              </div>
            </div>
          </div>
        </div>

      {/* Bottom Chat Input - Always visible on Home Page for starting new tasks */}
      <ChatInput
        value={chatValue}
        onChange={setChatValue}
        onSubmit={startMining}
        onStop={stopMining}
        isRunning={task?.status === 'running'}
      />
    </Layout>
  );
};
