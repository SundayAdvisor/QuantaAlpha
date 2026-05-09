import React from 'react';
import {
  Boxes,
  Loader2,
  RefreshCw,
  PackageOpen,
  Wrench,
  PlayCircle,
  AlertCircle,
  CheckCircle2,
  CircleDashed,
} from 'lucide-react';

import { Layout } from '@/components/layout/Layout';
import type { PageId } from '@/components/layout/Layout';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { NamingGuide } from '@/components/NamingGuide';
import {
  buildBundle,
  getBuildLog,
  getBundle,
  listBuildableWorkspaces,
  listBundles,
} from '@/services/api';
import type {
  BuildableWorkspace,
  BundleFactor,
  ProductionBundle,
} from '@/types';
import { cn, formatDateTime } from '@/utils';

interface ProductionModelsPageProps {
  onNavigate?: (page: PageId) => void;
}

type Tab = 'list' | 'build';

export const ProductionModelsPage: React.FC<ProductionModelsPageProps> = ({ onNavigate }) => {
  const [tab, setTab] = React.useState<Tab>('list');

  return (
    <Layout
      currentPage={'bundles' as PageId}
      onNavigate={onNavigate || (() => {})}
      showNavigation={!!onNavigate}
    >
      <div className="space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-foreground flex items-center gap-2">
              <Boxes className="size-6" /> Production Models
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              LightGBM bundles trained on gate-passing factors. Phase 5 saves them; Phase 6 predicts with them.
            </p>
          </div>
        </header>

        <NamingGuide />

        <div className="flex items-center gap-1 border-b border-border">
          <TabButton active={tab === 'list'} onClick={() => setTab('list')} icon={<PackageOpen className="size-4" />}>
            Bundles
          </TabButton>
          <TabButton active={tab === 'build'} onClick={() => setTab('build')} icon={<Wrench className="size-4" />}>
            Build new
          </TabButton>
        </div>

        {tab === 'list' && <BundlesList />}
        {tab === 'build' && <BuildForm onCompleted={() => setTab('list')} />}
      </div>
    </Layout>
  );
};

const TabButton: React.FC<{
  active: boolean;
  onClick: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}> = ({ active, onClick, icon, children }) => (
  <button
    onClick={onClick}
    className={cn(
      'flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
      active
        ? 'border-primary text-foreground'
        : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted'
    )}
  >
    {icon}
    {children}
  </button>
);

// ─── Bundles list tab ───────────────────────────────────────────────────────

const BundlesList: React.FC = () => {
  const [bundles, setBundles] = React.useState<ProductionBundle[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [factors, setFactors] = React.useState<BundleFactor[]>([]);
  const [factorsLoading, setFactorsLoading] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await listBundles();
      if (res.success && res.data) {
        setBundles(res.data.bundles || []);
      } else {
        setErr(res.error || 'Failed to load bundles');
      }
    } catch (e: any) {
      setErr(e?.message || 'Failed to load bundles');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const loadFactors = async (name: string) => {
    setSelected(name);
    setFactorsLoading(true);
    try {
      const res = await getBundle(name);
      if (res.success && res.data) {
        setFactors(res.data.factors || []);
      } else {
        setFactors([]);
      }
    } catch {
      setFactors([]);
    } finally {
      setFactorsLoading(false);
    }
  };

  if (loading && bundles.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 flex items-center justify-center text-muted-foreground gap-2">
          <Loader2 className="size-4 animate-spin" /> Loading bundles…
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <PackageOpen className="size-4" /> {bundles.length} bundle{bundles.length === 1 ? '' : 's'}
          </h3>
          <button
            onClick={refresh}
            disabled={loading}
            className="text-muted-foreground hover:text-foreground"
            title="Refresh"
          >
            {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          </button>
        </div>
        {err && (
          <Card>
            <CardContent className="py-3 text-xs text-destructive">{err}</CardContent>
          </Card>
        )}
        {bundles.length === 0 && !err && !loading && (
          <Card>
            <CardContent className="py-4 text-xs text-muted-foreground">
              No bundles yet. Switch to <strong>Build new</strong> to create one from a completed mining workspace.
            </CardContent>
          </Card>
        )}
        <div className="space-y-2">
          {bundles.map((b) => (
            <BundleCard
              key={b.name}
              bundle={b}
              selected={b.name === selected}
              onClick={() => loadFactors(b.name)}
            />
          ))}
        </div>
      </div>

      <div className="lg:col-span-1 space-y-3">
        <h3 className="text-sm font-semibold">Factor list</h3>
        {selected ? (
          <Card>
            <CardContent className="py-3 space-y-2">
              <div className="text-[10px] text-muted-foreground font-mono truncate">{selected}</div>
              {factorsLoading && (
                <div className="text-xs text-muted-foreground flex items-center gap-1">
                  <Loader2 className="size-3 animate-spin" /> loading…
                </div>
              )}
              {!factorsLoading && factors.length === 0 && (
                <div className="text-xs text-muted-foreground italic">
                  Baseline-only bundle — no mined factors layered in.
                </div>
              )}
              {!factorsLoading && factors.length > 0 && (
                <ul className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
                  {factors.map((f, i) => (
                    <li key={i} className="text-xs border-l-2 border-violet-500/50 pl-2">
                      <div className="font-mono text-foreground">{f.name || `factor_${i}`}</div>
                      {f.expression && (
                        <div className="font-mono text-[10px] text-muted-foreground break-all">
                          {f.expression}
                        </div>
                      )}
                      {f.trajectory_rank_ic != null && (
                        <div className="text-[10px] text-muted-foreground">
                          parent traj RankIC ={' '}
                          <span
                            className={
                              f.trajectory_rank_ic > 0.05
                                ? 'text-emerald-300'
                                : f.trajectory_rank_ic > 0
                                ? 'text-amber-300'
                                : 'text-red-300'
                            }
                          >
                            {f.trajectory_rank_ic.toFixed(4)}
                          </span>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-3 text-xs text-muted-foreground italic">
              Click a bundle to see its factors.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

const BundleCard: React.FC<{
  bundle: ProductionBundle;
  selected: boolean;
  onClick: () => void;
}> = ({ bundle, selected, onClick }) => {
  const factorTrained = (bundle.num_factors_in_metadata ?? 0) > 0;
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full text-left rounded-lg border p-3 transition-colors',
        selected
          ? 'border-primary bg-primary/10'
          : 'border-border hover:border-primary/40 hover:bg-secondary/40'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-mono font-semibold text-foreground truncate">{bundle.name}</div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {bundle.saved_at ? formatDateTime(bundle.saved_at) : 'no metadata'} ·{' '}
            {bundle.market || '—'} / {bundle.benchmark || '—'}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          {factorTrained ? (
            <span className="text-[9px] uppercase rounded border border-emerald-700/60 bg-emerald-950/40 text-emerald-300 px-1.5 py-0.5">
              factor-trained
            </span>
          ) : (
            <span className="text-[9px] uppercase rounded border border-amber-700/60 bg-amber-950/40 text-amber-300 px-1.5 py-0.5">
              baseline only
            </span>
          )}
          {!bundle.has_model && (
            <span className="text-[9px] uppercase rounded border border-red-700/60 bg-red-950/40 text-red-300 px-1.5 py-0.5">
              missing model.lgbm
            </span>
          )}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-2 text-[11px] font-mono">
        <Stat label="factors" value={bundle.num_factors_in_metadata} />
        <Stat
          label="test IC"
          value={bundle.test_ic != null ? bundle.test_ic.toFixed(4) : '—'}
          numeric={bundle.test_ic}
          good={(v) => v > 0.03}
          bad={(v) => v < 0}
        />
        <Stat
          label="test RIC"
          value={bundle.test_rank_ic != null ? bundle.test_rank_ic.toFixed(4) : '—'}
          numeric={bundle.test_rank_ic}
          good={(v) => v > 0.04}
          bad={(v) => v < 0}
        />
      </div>
    </button>
  );
};

const Stat: React.FC<{
  label: string;
  value: string | number | null | undefined;
  numeric?: number | null;
  good?: (v: number) => boolean;
  bad?: (v: number) => boolean;
}> = ({ label, value, numeric, good, bad }) => {
  let cls = 'text-foreground';
  if (numeric != null) {
    if (good?.(numeric)) cls = 'text-emerald-300';
    else if (bad?.(numeric)) cls = 'text-red-300';
  }
  const display = value === null || value === undefined ? '—' : String(value);
  return (
    <div>
      <div className="text-[9px] text-muted-foreground uppercase tracking-wider">{label}</div>
      <div className={cn('font-semibold', cls)}>{display}</div>
    </div>
  );
};

// ─── Build new tab ──────────────────────────────────────────────────────────

const BuildForm: React.FC<{ onCompleted: () => void }> = ({ onCompleted }) => {
  const [workspaces, setWorkspaces] = React.useState<BuildableWorkspace[]>([]);
  const [loadingWs, setLoadingWs] = React.useState(false);
  const [wsErr, setWsErr] = React.useState<string | null>(null);

  const [mode, setMode] = React.useState<'full' | 'baseline'>('full');
  const [selectedWs, setSelectedWs] = React.useState<string>('');
  const [outputName, setOutputName] = React.useState<string>('');

  const [submitting, setSubmitting] = React.useState(false);
  const [buildErr, setBuildErr] = React.useState<string | null>(null);
  const [taskId, setTaskId] = React.useState<string | null>(null);
  const [logLines, setLogLines] = React.useState<string[]>([]);
  const [status, setStatus] = React.useState<'idle' | 'running' | 'completed' | 'failed'>('idle');

  React.useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoadingWs(true);
      setWsErr(null);
      try {
        const res = await listBuildableWorkspaces();
        if (cancelled) return;
        if (res.success && res.data) {
          setWorkspaces(res.data.workspaces || []);
          if (!selectedWs && res.data.workspaces?.length) {
            setSelectedWs(res.data.workspaces[0].name);
          }
        } else {
          setWsErr(res.error || 'Failed to load workspaces');
        }
      } catch (e: any) {
        if (!cancelled) setWsErr(e?.message || 'Failed to load workspaces');
      } finally {
        if (!cancelled) setLoadingWs(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll log when a build is running
  React.useEffect(() => {
    if (!taskId || status !== 'running') return;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await getBuildLog(taskId, 300);
        if (cancelled) return;
        if (res.success && res.data) {
          setLogLines(res.data.log || []);
          const taskStatus = res.data.task?.status;
          if (taskStatus === 'completed') {
            setStatus('completed');
          } else if (taskStatus === 'failed') {
            setStatus('failed');
          }
        }
      } catch {
        // ignore polling errors
      }
    };
    const id = window.setInterval(tick, 2000);
    tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [taskId, status]);

  const submit = async () => {
    setBuildErr(null);
    if (mode === 'full' && !selectedWs) {
      setBuildErr('Pick a workspace, or switch to baseline mode.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await buildBundle({
        workspace: mode === 'full' ? selectedWs : undefined,
        baseline: mode === 'baseline',
        outputName: outputName.trim() || undefined,
      });
      if (res.success && res.data) {
        setTaskId(res.data.buildTaskId);
        setStatus('running');
      } else {
        setBuildErr(res.error || 'Build failed');
      }
    } catch (e: any) {
      setBuildErr(e?.message || 'Build failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <CardContent className="py-4 space-y-4">
          <div>
            <h3 className="text-sm font-semibold mb-2">Configure build</h3>
            <p className="text-xs text-muted-foreground">
              This calls <code className="font-mono">extract_production_model.py</code> with the chosen flags.
              Hyperparameters are taken from the template config (LightGBM, paper-aligned). Hyperparameter
              overrides are not yet exposed in this UI.
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Mode
            </label>
            <div className="flex gap-2">
              <ModeButton
                active={mode === 'full'}
                onClick={() => setMode('full')}
                title="Train on the gate-filtered factor parquet from a completed mining run + 20 baseline features."
              >
                Full (factors + baseline)
              </ModeButton>
              <ModeButton
                active={mode === 'baseline'}
                onClick={() => setMode('baseline')}
                title="Train on the 20 Alpha158 baseline features only. Smoke test — fast, but no QA-mined alpha."
              >
                Baseline only
              </ModeButton>
            </div>
          </div>

          {mode === 'full' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Source workspace
                </label>
                {loadingWs && <Loader2 className="size-3 animate-spin text-muted-foreground" />}
              </div>
              {wsErr && <div className="text-xs text-destructive">{wsErr}</div>}
              {!loadingWs && workspaces.length === 0 && (
                <div className="text-xs text-amber-300 bg-amber-950/30 border border-amber-700/40 rounded p-2">
                  No workspace_exp_* dirs with combined_factors_df.parquet yet. Either run a real mining
                  experiment first, or switch to <strong>Baseline only</strong> for a smoke test.
                </div>
              )}
              {workspaces.length > 0 && (
                <>
                  <select
                    value={selectedWs}
                    onChange={(e) => setSelectedWs(e.target.value)}
                    className="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-sm focus:border-primary focus:outline-none"
                  >
                    {workspaces.map((w) => (
                      <option key={w.name} value={w.name}>
                        {w.parquet_mtime ? new Date(w.parquet_mtime).toLocaleString() : 'unknown date'}
                        {' · '}{w.parquet_count} parquet{w.parquet_count === 1 ? '' : 's'}
                        {' · '}{w.name}
                      </option>
                    ))}
                  </select>

                  {/* Show what the selected workspace is linked to */}
                  {(() => {
                    const w = workspaces.find((x) => x.name === selectedWs);
                    if (!w) return null;
                    return (
                      <div className="mt-1.5 px-2 py-1.5 rounded border border-border/60 bg-secondary/20 text-[11px] space-y-0.5">
                        <div className="text-muted-foreground">
                          <strong className="text-foreground">workspace:</strong>{' '}
                          <code className="font-mono">{w.name}</code>
                        </div>
                        {w.linked_library ? (
                          <div className="text-muted-foreground">
                            <strong className="text-foreground">→ linked library:</strong>{' '}
                            <code className="font-mono">{w.linked_library.name}</code>
                            {' '}({w.linked_library.factor_count} factor{w.linked_library.factor_count === 1 ? '' : 's'})
                          </div>
                        ) : (
                          <div className="text-amber-300/80">
                            no matching <code className="font-mono">all_factors_library_…</code> found
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </>
              )}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Bundle name <span className="text-muted-foreground/70 normal-case">(optional)</span>
            </label>
            <input
              value={outputName}
              onChange={(e) => setOutputName(e.target.value)}
              placeholder="defaults to spy_production_<timestamp>"
              className="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-sm font-mono focus:border-primary focus:outline-none"
            />
            <p className="text-[10px] text-muted-foreground">
              Alphanumerics, underscore, hyphen only. Will appear under <code>data/results/production_models/</code>.
            </p>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              disabled={submitting || status === 'running'}
            >
              {submitting || status === 'running' ? (
                <>
                  <Loader2 className="size-3.5 animate-spin mr-1" /> Building…
                </>
              ) : (
                <>
                  <PlayCircle className="size-3.5 mr-1" /> Build bundle
                </>
              )}
            </Button>
            {status === 'completed' && (
              <Button variant="secondary" size="sm" onClick={onCompleted}>
                See bundles list
              </Button>
            )}
          </div>

          {buildErr && (
            <div className="text-xs text-destructive bg-destructive/10 border border-destructive/40 rounded p-2 flex items-center gap-1">
              <AlertCircle className="size-3.5" /> {buildErr}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="py-4 space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              {status === 'running' && <Loader2 className="size-4 animate-spin text-primary" />}
              {status === 'completed' && <CheckCircle2 className="size-4 text-emerald-400" />}
              {status === 'failed' && <AlertCircle className="size-4 text-destructive" />}
              {status === 'idle' && <CircleDashed className="size-4 text-muted-foreground" />}
              Build log
            </h3>
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{status}</span>
          </div>
          <div className="rounded border border-border bg-black/40 p-3 text-[11px] font-mono text-foreground/90 max-h-[60vh] overflow-y-auto">
            {logLines.length === 0 ? (
              <span className="text-muted-foreground italic">
                {status === 'idle' ? 'No build running.' : 'Waiting for output…'}
              </span>
            ) : (
              logLines.map((line, i) => (
                <div key={i} className="whitespace-pre-wrap break-words">
                  {line}
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

const ModeButton: React.FC<{
  active: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}> = ({ active, onClick, title, children }) => (
  <button
    onClick={onClick}
    title={title}
    className={cn(
      'rounded-md border px-3 py-1.5 text-xs transition-colors',
      active
        ? 'border-primary bg-primary/10 text-foreground'
        : 'border-border hover:border-primary/50 text-muted-foreground hover:text-foreground'
    )}
  >
    {children}
  </button>
);
