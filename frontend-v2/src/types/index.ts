// Task status
export type TaskStatus = 'idle' | 'running' | 'completed' | 'failed';

// Execution phase
export type ExecutionPhase =
  | 'parsing'      // Parsing requirements
  | 'planning'     // Planning direction
  | 'evolving'     // Evolving
  | 'backtesting'  // Backtesting
  | 'analyzing'    // Analyzing results
  | 'completed';   // Completed

// Factor quality level
export type FactorQuality = 'high' | 'medium' | 'low';

// Task configuration
export interface TaskConfig {
  // Basic configuration
  userInput: string;
  /** Optional human-friendly name shown on History/Models in place of the raw run timestamp. */
  displayName?: string;
  /** Universe to mine on — sp500 | nasdaq100 | commodities | "custom". */
  universe?: string;
  /** When universe="custom", the explicit ticker list. Recommend ≥30 for stable RankIC. */
  customTickers?: string[];
  /** Train/valid/test segment overrides (YYYY-MM-DD). All optional; defaults from conf_baseline.yaml. */
  trainStart?: string;
  trainEnd?: string;
  validStart?: string;
  validEnd?: string;
  testStart?: string;
  testEnd?: string;
  /** When true, use options in "Settings -> Mining Direction" (selected/random), ignoring input box content */
  useCustomMiningDirection?: boolean;
  numDirections?: number;
  maxRounds?: number;
  librarySuffix?: string;

  // LLM configuration
  apiKey?: string;
  apiUrl?: string;
  modelName?: string;

  // Backtest configuration
  market?: 'csi300' | 'csi500' | 'sp500';
  startDate?: string;
  endDate?: string;

  // Advanced configuration
  parallelExecution?: boolean;
  qualityGateEnabled?: boolean;
  backtestTimeout?: number;
}

// Real-time metrics
export interface RealtimeMetrics {
  // IC metrics
  ic: number;
  icir: number;
  rankIc: number;
  rankIcir: number;
  
  // Optional factor name if available (e.g. best factor)
  factorName?: string;
  
  // Top 10 factors list
  top10Factors?: Array<{
    factorName: string;
    factorExpression: string;
    rankIc: number;
    rankIcir: number;
    ic: number;
    icir: number;
    annualReturn?: number;
    sharpeRatio?: number;
    maxDrawdown?: number;
    calmarRatio?: number;
    cumulativeCurve?: Array<{date: string, value: number}>;
  }>;

  // Return metrics
  annualReturn: number;
  sharpeRatio: number;
  maxDrawdown: number;

  // Factor statistics
  totalFactors: number;
  highQualityFactors: number;
  mediumQualityFactors: number;
  lowQualityFactors: number;
}

// Execution progress
export interface ExecutionProgress {
  phase: ExecutionPhase;
  currentRound: number;
  totalRounds: number;
  progress: number; // 0-100
  message: string;
  timestamp: string;
}

// Log entry
export interface LogEntry {
  id: string;
  timestamp: string;
  level: 'info' | 'warning' | 'error' | 'success';
  message: string;
}

// Factor information
export interface Factor {
  factorId: string;
  factorName: string;
  factorExpression: string;
  factorDescription: string;
  quality: FactorQuality;

  // Backtest metrics
  ic: number;
  icir: number;
  rankIc: number;
  rankIcir: number;

  // Metadata
  round: number;
  direction: string;
  createdAt: string;
}

// Backtest result
export interface BacktestResult {
  // Overall metrics
  metrics: RealtimeMetrics;

  // Time series data
  equityCurve: TimeSeriesData[];
  drawdownCurve: TimeSeriesData[];
  icTimeSeries: TimeSeriesData[];

  // Factor list
  factors: Factor[];

  // Quality distribution
  qualityDistribution: {
    high: number;
    medium: number;
    low: number;
  };
}

// Time series data point
export interface TimeSeriesData {
  date: string;
  value: number;
}

// Task information
export interface Task {
  taskId: string;
  status: TaskStatus;
  config: TaskConfig;
  progress: ExecutionProgress;
  metrics?: RealtimeMetrics;
  result?: BacktestResult;
  logs: LogEntry[];
  createdAt: string;
  updatedAt: string;
}

// API Response
export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

// WebSocket message type
export type WsMessageType =
  | 'progress'
  | 'metrics'
  | 'log'
  | 'result'
  | 'error';

// WebSocket message
export interface WsMessage {
  type: WsMessageType;
  taskId: string;
  data: any;
  timestamp: string;
}

// ─── Run history / analysis / lineage / suggester ────────────────────────────

export type RunVerdict = 'robust' | 'promising' | 'regime-fit' | 'marginal' | 'broken';

export interface RunSummary {
  run_id: string;
  log_dir: string;
  total_trajectories: number;
  by_phase: Record<string, number>;
  best_rank_icir: number | null;
  best_ir: number | null;
  current_round: number | null;
  current_phase: string | null;
  directions_completed: number;
  config: Record<string, any>;
  saved_at: string | null;
  created_at: string | null;
  /** Run status derived by the backend from manifest.json + saved_at recency.
   * 'running' = no manifest, saved_at ≤ 5 min old.
   * 'completed' = manifest.json exists.
   * 'stale' = no manifest, saved_at > 5 min old (probably crashed/killed). */
  status?: 'running' | 'completed' | 'stale' | 'unknown';
  /** Workspace dir name this run wrote to (factor execution sandbox). May be null if not inferable. */
  linked_workspace?: string | null;
  /** Factor library JSON file name produced by this run. May be null if not inferable. */
  linked_library?: string | null;
  /** "manifest" if explicit pointer was found, "mtime" if inferred, null if neither. */
  linkage_source?: 'manifest' | 'mtime' | null;
  /** User-supplied human-friendly name (from manifest). */
  display_name?: string | null;
  /** Original objective string the user typed (from manifest). */
  objective?: string | null;
}

export interface RunAnalysis {
  run_id: string;
  verdict: RunVerdict;
  verdict_reason: string;
  summary: string;
  per_trajectory_notes: Array<{ trajectory_id: string; note: string }>;
  recommended_next_steps: string[];
  best_rank_icir: number | null;
  best_ir: number | null;
  rank_icir_to_ir_gap: number | null;
  created_at: string;
}

export type TrajectoryPhase = 'original' | 'mutation' | 'crossover' | 'optimized';

export interface LineageNode {
  id: string;
  phase: TrajectoryPhase | string;
  round: number | null;
  direction_id: number | null;
  rank_icir: number | null;
  ir: number | null;
  ic: number | null;
  ann_ret: number | null;
  max_dd: number | null;
  hypothesis: string;
}

export interface LineageEdge {
  source: string;
  target: string;
}

export interface SuggestedObjective {
  title: string;
  description: string;
  mechanism: string;
  primary_features: string[];
  expected_horizon_days: number | null;
  complexity: 'low' | 'medium' | 'high';
  rationale_for_user: string;
}

export interface FindingsConfig {
  repo_path: string | null;
  repo_exists: boolean;
  auto_publish_enabled: boolean;
}

// ─── Production model bundles (Phase 5/6) ────────────────────────────────────

export interface ProductionBundle {
  name: string;
  path: string;
  has_model: boolean;
  factor_count: number;
  saved_at: string | null;
  market: string | null;
  benchmark: string | null;
  model_class: string | null;
  model_kwargs: Record<string, any> | null;
  train_segments: Record<string, [string, string]> | null;
  test_ic: number | null;
  test_rank_ic: number | null;
  num_factors_in_metadata: number | null;
}

export interface BundleFactor {
  name?: string;
  expression?: string;
  description?: string;
  trajectory_id?: string;
  trajectory_rank_ic?: number | null;
}

export interface BuildableWorkspace {
  name: string;
  path: string;
  parquet_path: string;
  parquet_mtime: string | null;
  parquet_count: number;
  /** all_factors_library_<suffix>.json that matches this workspace, if found. */
  linked_library?: {
    name: string;
    path: string;
    mtime: string | null;
    factor_count: number;
  } | null;
}

export interface BuildBundleParams {
  workspace?: string;
  baseline?: boolean;
  outputName?: string;
}

export interface BuildBundleResult {
  buildTaskId: string;
  outputName: string;
  logPath: string;
}

export interface BuildBundleStatus {
  task: {
    type: string;
    pid: number;
    cmd: string[];
    logPath: string;
    outputName: string;
    status: 'running' | 'completed' | 'failed';
    createdAt: string;
    updatedAt?: string;
  };
  log: string[];
}

// ─── Universes (Phase D — universe-aware mining) ─────────────────────────────

export interface UniverseSummary {
  name: string;
  ticker_count: number;
  instruments_path: string;
  /** ISO timestamp of the most-recent close.day.bin write for a sample ticker. */
  last_data_mtime: string | null;
  sample_ticker: string | null;
}

export interface DetectedUniverse {
  universe: string;
  reason: string;
}
