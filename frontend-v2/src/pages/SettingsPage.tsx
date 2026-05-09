import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Settings, Save, RotateCcw, Eye, EyeOff, Check, AlertCircle, Info, Loader2, Database, Sliders, Box, Cpu, Compass, Shuffle, ChevronDown, ChevronRight, Sparkles } from 'lucide-react';
import { getSystemConfig, updateSystemConfig, healthCheck } from '@/services/api';
import { REFERENCE_MINING_DIRECTIONS, getDirectionLabel, type MiningDirectionItem } from '@/utils/miningDirections';

interface SystemConfig {
  // LLM provider routing — read-only from .env
  llmProvider: string;            // "claude_code" | "openai" | etc.
  claudeCodeModel: string;        // active model when provider=claude_code
  claudeCodeFallback: string;     // "anthropic" | "openai"
  // LLM (fallback config — only used when provider != claude_code, or as fallback)
  apiKey: string;
  apiUrl: string;
  modelName: string;
  // Qlib
  qlibDataPath: string;
  resultsDir: string;
  // Parameters
  defaultNumDirections: number;
  defaultMaxRounds: number;
  defaultMarket: 'sp500';         // CSI markets removed — no CN data in this bundle
  // Advanced
  parallelExecution: boolean;
  qualityGateEnabled: boolean;
  backtestTimeout: number;
  defaultLibrarySuffix: string;
  // Mining direction: use selected directions / random
  miningDirectionMode: 'selected' | 'random';
  selectedMiningDirectionIndices: number[];
}

const DEFAULT_CONFIG: SystemConfig = {
  llmProvider: '',
  claudeCodeModel: '',
  claudeCodeFallback: '',
  apiKey: '',
  apiUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  modelName: 'deepseek-v3',
  qlibDataPath: '',
  resultsDir: '',
  defaultNumDirections: 10,    // paper Appendix B: Ninit=10
  defaultMaxRounds: 5,         // paper Appendix B: 5 main iterations
  defaultMarket: 'sp500',      // matches conf YAMLs (no CN data in this bundle)
  parallelExecution: true,
  qualityGateEnabled: true,
  backtestTimeout: 600,
  defaultLibrarySuffix: '',
  miningDirectionMode: 'selected',
  selectedMiningDirectionIndices: [0, 1, 2],
};

type SettingsTab = 'api' | 'data' | 'params' | 'directions';

export const SettingsPage: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig>(DEFAULT_CONFIG);
  const [activeTab, setActiveTab] = useState<SettingsTab>('api');
  const [showApiKey, setShowApiKey] = useState(false);
  const [isSaved, setIsSaved] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [backendStatus, setBackendStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [factorLibraries, setFactorLibraries] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Load config from backend on mount
  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setIsLoading(true);
    setError(null);

    // Check backend health
    try {
      await healthCheck();
      setBackendStatus('online');
    } catch {
      setBackendStatus('offline');
    }

    // Load config
    try {
      const resp = await getSystemConfig();
      if (resp.success && resp.data) {
        const env = resp.data.env || {};
        const saved = localStorage.getItem('quantaalpha_config');
        let miningDirectionMode = DEFAULT_CONFIG.miningDirectionMode;
        let selectedMiningDirectionIndices = DEFAULT_CONFIG.selectedMiningDirectionIndices;
        if (saved) {
          try {
            const parsed = JSON.parse(saved);
            if (parsed.miningDirectionMode) miningDirectionMode = parsed.miningDirectionMode;
            if (Array.isArray(parsed.selectedMiningDirectionIndices)) selectedMiningDirectionIndices = parsed.selectedMiningDirectionIndices;
          } catch { /* use defaults */ }
        }
        // Carry over locally-cached numeric/checkbox params if present
        let cached: any = {};
        if (saved) {
          try { cached = JSON.parse(saved); } catch { /* ignore */ }
        }
        setConfig({
          llmProvider: env.LLM_PROVIDER || '',
          claudeCodeModel: env.CLAUDE_CODE_MODEL || '',
          claudeCodeFallback: env.CLAUDE_CODE_FALLBACK || '',
          apiKey: env.OPENAI_API_KEY || '',
          apiUrl: env.OPENAI_BASE_URL || DEFAULT_CONFIG.apiUrl,
          modelName: env.CHAT_MODEL || DEFAULT_CONFIG.modelName,
          qlibDataPath: env.QLIB_DATA_DIR || '',
          resultsDir: env.DATA_RESULTS_DIR || '',
          defaultNumDirections: cached.defaultNumDirections ?? DEFAULT_CONFIG.defaultNumDirections,
          defaultMaxRounds: cached.defaultMaxRounds ?? DEFAULT_CONFIG.defaultMaxRounds,
          defaultMarket: 'sp500',
          parallelExecution: cached.parallelExecution ?? DEFAULT_CONFIG.parallelExecution,
          qualityGateEnabled: cached.qualityGateEnabled ?? DEFAULT_CONFIG.qualityGateEnabled,
          backtestTimeout: cached.backtestTimeout ?? DEFAULT_CONFIG.backtestTimeout,
          defaultLibrarySuffix: cached.defaultLibrarySuffix ?? DEFAULT_CONFIG.defaultLibrarySuffix,
          miningDirectionMode,
          selectedMiningDirectionIndices,
        });
        setFactorLibraries(resp.data.factorLibraries || []);
      }
    } catch (err: any) {
      console.error('Failed to load config:', err);
      // Fallback to localStorage
      const saved = localStorage.getItem('quantaalpha_config');
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          setConfig({
            ...DEFAULT_CONFIG,
            ...parsed,
            selectedMiningDirectionIndices: Array.isArray(parsed.selectedMiningDirectionIndices)
              ? parsed.selectedMiningDirectionIndices
              : DEFAULT_CONFIG.selectedMiningDirectionIndices,
          });
        } catch {
          // use defaults
        }
      }
      setError('Could not load configuration from the backend — showing locally cached values.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);

    // Always save to localStorage as backup
    localStorage.setItem('quantaalpha_config', JSON.stringify(config));

    // Try to save to backend
    try {
      const update: Record<string, string> = {};
      if (config.apiKey && !config.apiKey.includes('...')) {
        update.OPENAI_API_KEY = config.apiKey;
      }
      if (config.apiUrl) update.OPENAI_BASE_URL = config.apiUrl;
      if (config.modelName) {
        update.CHAT_MODEL = config.modelName;
        update.REASONING_MODEL = config.modelName;
      }
      if (config.qlibDataPath) update.QLIB_DATA_DIR = config.qlibDataPath;
      if (config.resultsDir) update.DATA_RESULTS_DIR = config.resultsDir;

      if (Object.keys(update).length > 0) {
        await updateSystemConfig(update);
      }
    } catch (err: any) {
      console.warn('Failed to save to backend, saved locally:', err);
    }

    setIsSaved(true);
    setIsDirty(false);
    setIsSaving(false);
    setTimeout(() => setIsSaved(false), 2000);
  };

  const handleReset = () => {
    if (confirm('Reset to default configuration?')) {
      setConfig(DEFAULT_CONFIG);
      setIsDirty(true);
    }
  };

  const updateConfigField = (key: keyof SystemConfig, value: any) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
    setIsDirty(true);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="ml-3 text-muted-foreground">Loading configuration…</span>
      </div>
    );
  }

  const TabButton = ({ id, label, icon: Icon }: { id: SettingsTab; label: string; icon: any }) => (
    <button
      onClick={() => setActiveTab(id)}
      className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
        activeTab === id
          ? 'bg-primary text-primary-foreground shadow-lg scale-105'
          : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
      }`}
    >
      <Icon className="h-4 w-4" />
      <span className="font-medium">{label}</span>
    </button>
  );

  return (
    <div className="space-y-6 animate-fade-in-up">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Settings className="h-8 w-8 text-primary" />
            System settings
          </h1>
          <p className="text-muted-foreground mt-1">
            Manage API connection, data sources, and experiment parameters
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" onClick={handleReset}>
            <RotateCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
          <Button variant="primary" onClick={handleSave} disabled={!isDirty || isSaving}>
            {isSaving ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            Save
          </Button>
        </div>
      </div>

      {/* Status Banners */}
      {isSaved && (
        <div className="glass rounded-lg p-4 flex items-center gap-3 bg-success/10 border-success/50 animate-fade-in-down">
          <Check className="h-5 w-5 text-success" />
          <span className="text-success">Settings saved</span>
        </div>
      )}
      {isDirty && !isSaved && (
        <div className="glass rounded-lg p-4 flex items-center gap-3 bg-primary/10 border-primary/40 animate-fade-in-down">
          <Info className="h-5 w-5 text-primary shrink-0" />
          <div className="flex-1">
            <div className="text-sm font-medium text-foreground">You have unsaved changes</div>
            <div className="text-xs text-muted-foreground">
              Click <strong>Save</strong> above to apply. Numeric defaults are read by the home-page chat
              when starting a new mining run.
            </div>
          </div>
        </div>
      )}
      {error && (
        <div className="glass rounded-lg p-4 flex items-center gap-3 bg-warning/10 border-warning/50">
          <AlertCircle className="h-5 w-5 text-warning flex-shrink-0" />
          <span className="text-sm text-warning">{error}</span>
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="flex gap-2 p-1 bg-secondary/20 rounded-xl w-fit flex-wrap">
        <TabButton id="api" label="API" icon={Cpu} />
        <TabButton id="data" label="Data Paths" icon={Database} />
        <TabButton id="params" label="Default Parameters" icon={Sliders} />
        <TabButton id="directions" label="Research Directions" icon={Compass} />
      </div>

      {/* Tab Content */}
      <div className="grid grid-cols-1 gap-6">
        
        {/* API Configuration Tab */}
        {activeTab === 'api' && (
          <ApiTab
            config={config}
            updateConfigField={updateConfigField}
            showApiKey={showApiKey}
            setShowApiKey={setShowApiKey}
            backendStatus={backendStatus}
          />
        )}

        {/* Data Path Configuration Tab */}
        {activeTab === 'data' && (
          <Card className="glass card-hover animate-fade-in-up">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                📊 Data paths
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div>
                <label className="block text-sm font-medium mb-2">
                  Qlib data directory <span className="text-destructive">*</span>
                </label>
                <div className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-muted-foreground" />
                  <input
                    type="text"
                    value={config.qlibDataPath}
                    onChange={(e) => updateConfigField('qlibDataPath', e.target.value)}
                    placeholder="/path/to/qlib/cn_data"
                    className="flex-1 rounded-lg border border-input bg-background px-4 py-2 text-sm font-mono focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-1 ml-6">
                  Must contain Qlib's standard subdirectories: calendars/, features/, instruments/
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Experiment results output directory
                </label>
                <div className="flex items-center gap-2">
                  <Box className="h-4 w-4 text-muted-foreground" />
                  <input
                    type="text"
                    value={config.resultsDir}
                    onChange={(e) => updateConfigField('resultsDir', e.target.value)}
                    placeholder="/path/to/results"
                    className="flex-1 rounded-lg border border-input bg-background px-4 py-2 text-sm font-mono focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-1 ml-6">
                  Where mined factors, backtest reports, and log files are stored
                </p>
              </div>

              {factorLibraries.length > 0 && (
                <div className="bg-secondary/20 rounded-lg p-4 mt-4">
                  <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
                    <Check className="h-4 w-4 text-success" />
                    Detected factor libraries
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {factorLibraries.map((lib, idx) => (
                      <Badge key={idx} variant="outline" className="bg-background/50">
                        {lib}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Default Parameters Tab */}
        {activeTab === 'params' && (
          <Card className="glass card-hover animate-fade-in-up">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                ⚙️ Default experiment parameters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium mb-2">Parallel directions</label>
                  <input
                    type="number"
                    value={config.defaultNumDirections}
                    onChange={(e) => updateConfigField('defaultNumDirections', Math.max(1, parseInt(e.target.value) || 1))}
                    min={1}
                    max={20}
                    className="w-full rounded-lg border border-input bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    How many independent research directions are explored per mining run (1–20).
                    Paper default: 10. Higher = more diversity + LLM cost. Saved values apply when you start
                    a run from the home-page chat (or override per-run there).
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Evolution rounds</label>
                  <input
                    type="number"
                    value={config.defaultMaxRounds}
                    onChange={(e) => updateConfigField('defaultMaxRounds', Math.max(1, parseInt(e.target.value) || 1))}
                    min={1}
                    max={20}
                    className="w-full rounded-lg border border-input bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Maximum mutation/crossover iterations per direction (1–20). Paper default: 5; pool
                    typically peaks around iter 11–12 (~350 factors).
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Default market</label>
                  <select
                    value={config.defaultMarket}
                    onChange={(e) => updateConfigField('defaultMarket', e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                  >
                    <option value="sp500">S&P 500 (US, daily OHLCV)</option>
                  </select>
                  <p className="text-xs text-muted-foreground mt-1">
                    Currently only SP500 is bundled (CSI 300 / CSI 500 from the paper require Chinese
                    A-share data which isn't shipped). Future: NASDAQ, DJIA, sector ETFs, commodities;
                    auto-pick by objective text.
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Backtest timeout (s)</label>
                  <input
                    type="number"
                    value={config.backtestTimeout}
                    onChange={(e) => updateConfigField('backtestTimeout', parseInt(e.target.value))}
                    min={60}
                    max={3600}
                    className="w-full rounded-lg border border-input bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Maximum runtime per backtest (s)
                  </p>
                </div>

                <div className="md:col-span-2">
                  <label className="block text-sm font-medium mb-2">Default factor library suffix</label>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground font-mono">all_factors_library_</span>
                    <input
                      type="text"
                      value={config.defaultLibrarySuffix}
                      onChange={(e) => {
                        const val = e.target.value.replace(/[^a-zA-Z0-9_\-]/g, '');
                        updateConfigField('defaultLibrarySuffix', val);
                      }}
                      placeholder="e.g. momentum_v1 (leave blank for no suffix)"
                      className="flex-1 rounded-lg border border-input bg-background px-4 py-2 text-sm font-mono focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                    />
                    <span className="text-sm text-muted-foreground font-mono">.json</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Generated factors will be saved to this file. Letters, digits, and underscores only.
                  </p>
                </div>
              </div>

              <div className="pt-4 border-t border-border/50 space-y-4">
                <h4 className="text-sm font-medium">Advanced controls</h4>

                <label className="flex items-center gap-3 cursor-pointer group p-3 rounded-lg border border-border/50 hover:bg-secondary/20 transition-all">
                  <input
                    type="checkbox"
                    checked={config.parallelExecution}
                    onChange={(e) => updateConfigField('parallelExecution', e.target.checked)}
                    className="h-5 w-5 rounded border-input text-primary focus:ring-primary"
                  />
                  <div className="flex-1">
                    <div className="font-medium group-hover:text-primary transition-colors">
                      Enable parallel execution
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Run multiple research directions simultaneously — significantly faster, at the cost of higher system load
                    </div>
                  </div>
                </label>

                <label className="flex items-center gap-3 cursor-pointer group p-3 rounded-lg border border-border/50 hover:bg-secondary/20 transition-all">
                  <input
                    type="checkbox"
                    checked={config.qualityGateEnabled}
                    onChange={(e) => updateConfigField('qualityGateEnabled', e.target.checked)}
                    className="h-5 w-5 rounded border-input text-primary focus:ring-primary"
                  />
                  <div className="flex-1">
                    <div className="font-medium group-hover:text-primary transition-colors">
                      Enable quality gate
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Automatically detect and filter low-quality factors, preventing them from entering the next iteration and improving final result quality
                    </div>
                  </div>
                </label>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Mining Direction Tab */}
        {activeTab === 'directions' && (
          <Card className="glass card-hover animate-fade-in-up">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Compass className="h-5 w-5" />
                Research directions (Alpha158(20) reference list)
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* What this is + when it's used */}
              <div className="rounded-lg border border-border/60 bg-secondary/20 p-4 space-y-2 text-sm">
                <div className="flex items-center gap-2 font-semibold text-foreground">
                  <Info className="h-4 w-4 text-primary" />
                  What this page does (and when it matters)
                </div>
                <p className="text-muted-foreground">
                  This is a <strong>preset pool of objectives</strong> derived from Alpha158's classical
                  factor families. It's used <strong>only</strong> when you toggle{' '}
                  <span className="inline-flex items-center gap-1 mx-0.5 px-1.5 py-0.5 rounded bg-primary/15 text-primary text-[11px]">
                    <Compass className="h-3 w-3" />Custom research direction
                  </span>{' '}
                  on the home-page chat input. With the toggle <em>off</em> (default), your typed text in
                  the chat box is used directly — none of these presets are consulted.
                </p>
                <p className="text-muted-foreground">
                  <strong className="text-foreground">Selecting more does NOT improve mining quality.</strong>{' '}
                  These are alternative <em>starting prompts</em>, not a multi-objective mix. The system
                  uses one objective per run.
                </p>
                <ul className="text-muted-foreground space-y-1 ml-4 list-disc">
                  <li>
                    <strong>Use selected</strong> — when you tick the toggle and start a run, the{' '}
                    <em>first</em> checked direction is used.
                  </li>
                  <li>
                    <strong>Random</strong> — when you tick the toggle and start a run, a random one
                    from the checked directions is used. Useful for unsupervised exploration sessions.
                  </li>
                </ul>
                <p className="text-muted-foreground text-xs italic">
                  Recommendation: leave a few you trust ticked, set mode to "Use selected", and ignore
                  this page unless you want random preset cycling.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium mb-3">Selection mode</label>
                <div className="flex flex-wrap gap-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="miningDirectionMode"
                      checked={config.miningDirectionMode === 'selected'}
                      onChange={() => updateConfigField('miningDirectionMode', 'selected')}
                      className="h-4 w-4 text-primary focus:ring-primary"
                    />
                    <span>Use selected (pick one of the checked directions on start)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="miningDirectionMode"
                      checked={config.miningDirectionMode === 'random'}
                      onChange={() => updateConfigField('miningDirectionMode', 'random')}
                      className="h-4 w-4 text-primary focus:ring-primary"
                    />
                    <span className="flex items-center gap-1.5">
                      <Shuffle className="h-4 w-4" />
                      Random (pick a random one from the selected directions)
                    </span>
                  </label>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="text-sm font-medium">Reference directions (multiple selection allowed)</label>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        updateConfigField(
                          'selectedMiningDirectionIndices',
                          REFERENCE_MINING_DIRECTIONS.map((_: MiningDirectionItem, i: number) => i)
                        );
                      }}
                    >
                      Select all
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => updateConfigField('selectedMiningDirectionIndices', [])}
                    >
                      Clear all
                    </Button>
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[320px] overflow-y-auto rounded-lg border border-border/50 bg-secondary/10 p-3">
                  {REFERENCE_MINING_DIRECTIONS.map((item: MiningDirectionItem, idx: number) => {
                    const label = getDirectionLabel(item);
                    return (
                      <label
                        key={idx}
                        className="flex items-center gap-2 p-2 rounded-lg hover:bg-secondary/20 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={config.selectedMiningDirectionIndices.includes(idx)}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? [...config.selectedMiningDirectionIndices, idx].sort((a, b) => a - b)
                              : config.selectedMiningDirectionIndices.filter((i) => i !== idx);
                            updateConfigField('selectedMiningDirectionIndices', next);
                          }}
                          className="h-4 w-4 rounded border-input text-primary focus:ring-primary"
                        />
                        <span className="text-sm truncate flex-1" title={label}>
                          {label}
                        </span>
                      </label>
                    );
                  })}
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  Selected: {config.selectedMiningDirectionIndices.length} / {REFERENCE_MINING_DIRECTIONS.length}
                </p>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Info Footer */}
      <Card className="glass border-primary/20 bg-primary/5">
        <CardContent className="p-4 flex gap-3">
          <div className="text-xl">💡</div>
          <div className="text-sm text-muted-foreground">
            <p className="mb-1 font-medium text-foreground">Configuration tip</p>
            <p>All config changes are automatically persisted to the backend environment file and the local browser cache. For changes involving API keys or paths, restart the related services to ensure changes take effect.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

// ─── API Tab subcomponent ───────────────────────────────────────────────────

interface ApiTabProps {
  config: SystemConfig;
  updateConfigField: (key: keyof SystemConfig, value: any) => void;
  showApiKey: boolean;
  setShowApiKey: (v: boolean) => void;
  backendStatus: 'checking' | 'online' | 'offline';
}

const ApiTab: React.FC<ApiTabProps> = ({ config, updateConfigField, showApiKey, setShowApiKey, backendStatus }) => {
  const isClaudeCode = (config.llmProvider || '').toLowerCase() === 'claude_code';
  const [fallbackOpen, setFallbackOpen] = useState(false);

  return (
    <Card className="glass card-hover animate-fade-in-up">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          🤖 LLM model configuration
          <Badge variant="default">Core</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* ── Active provider banner ─────────────────────────────────────── */}
        {isClaudeCode ? (
          <div className="rounded-lg border border-primary/40 bg-primary/5 p-4 space-y-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="font-semibold text-foreground">Active provider:</span>
              <Badge variant="default" className="bg-primary/20 border-primary/40 text-primary">
                Claude Code (your local CLI session)
              </Badge>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm pt-1">
              <div>
                <span className="text-muted-foreground">Model:</span>{' '}
                <span className="font-mono text-foreground">{config.claudeCodeModel || '—'}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Fallback:</span>{' '}
                <span className="font-mono text-foreground">{config.claudeCodeFallback || 'none'}</span>
              </div>
            </div>
            <p className="text-xs text-muted-foreground pt-1 border-t border-border/40">
              All LLM calls are routed through your local Claude Code subscription —
              no per-token API charges. Configured via <code className="font-mono">LLM_PROVIDER=claude_code</code> in
              the project's <code className="font-mono">.env</code>. To change the active model,
              edit <code className="font-mono">CLAUDE_CODE_MODEL</code> in <code className="font-mono">.env</code>.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-amber-700/40 bg-amber-950/20 p-4">
            <div className="flex items-center gap-2 text-sm">
              <AlertCircle className="h-4 w-4 text-amber-300" />
              <span className="text-amber-200">
                Active provider: <strong>{config.llmProvider || 'unknown'}</strong> (API-key path).
                Configure the key + URL + model below.
              </span>
            </div>
          </div>
        )}

        {/* ── API key / OpenAI-compatible config (collapsible when not active) */}
        <div>
          <button
            type="button"
            onClick={() => setFallbackOpen((v) => !v)}
            className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            {fallbackOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            {isClaudeCode ? 'API-key fallback configuration' : 'API-key configuration'}
            <span className="text-[10px] text-muted-foreground/70 normal-case ml-1">
              {isClaudeCode
                ? '(used only if Claude Code rate-limits or is unavailable)'
                : '(active path — required)'}
            </span>
          </button>

          {(fallbackOpen || !isClaudeCode) && (
            <div className="mt-4 space-y-4 pl-4 border-l-2 border-border/40">
              <div>
                <label className="block text-sm font-medium mb-2">
                  API Key {!isClaudeCode && <span className="text-destructive">*</span>}
                </label>
                <div className="flex gap-2">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    value={config.apiKey}
                    onChange={(e) => updateConfigField('apiKey', e.target.value)}
                    placeholder="sk-..."
                    className="flex-1 rounded-lg border border-input bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                  />
                  <Button variant="outline" onClick={() => setShowApiKey(!showApiKey)} className="px-3">
                    {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Any OpenAI-compatible API key works (DashScope, DeepSeek, OpenAI, etc.)
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">API Base URL</label>
                <input
                  type="text"
                  value={config.apiUrl}
                  onChange={(e) => updateConfigField('apiUrl', e.target.value)}
                  placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                  className="w-full rounded-lg border border-input bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Model name</label>
                <select
                  value={config.modelName}
                  onChange={(e) => updateConfigField('modelName', e.target.value)}
                  className="w-full rounded-lg border border-input bg-background px-4 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary transition-all"
                >
                  <option value="deepseek-v3">DeepSeek V3</option>
                  <option value="deepseek-r1">DeepSeek R1</option>
                  <option value="qwen-max">Qwen Max</option>
                  <option value="qwen-plus">Qwen Plus</option>
                  <option value="gpt-4">GPT-4</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                  <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Connection Status */}
        <div className="pt-4 border-t border-border/50">
          <div className="flex items-center gap-3">
            <div
              className={`h-3 w-3 rounded-full ${
                backendStatus === 'online'
                  ? 'bg-success animate-pulse'
                  : backendStatus === 'offline'
                  ? 'bg-destructive'
                  : 'bg-warning animate-pulse'
              }`}
            />
            <span className="text-sm">
              Backend status:{' '}
              {backendStatus === 'online' ? <span className="text-success font-medium">Connected</span> :
               backendStatus === 'offline' ? <span className="text-destructive font-medium">Not connected</span> :
               'Checking…'}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
