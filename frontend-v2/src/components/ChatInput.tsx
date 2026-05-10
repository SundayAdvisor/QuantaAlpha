import React, { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, Square, Compass, ChevronDown, ChevronRight, Wand2, Loader2 } from 'lucide-react';
import { TaskConfig, UniverseSummary } from '@/types';
import { listUniverses, detectUniverse, getQlibBundle, QlibBundleInfo } from '@/services/api';

interface ChatInputProps {
  onSubmit: (config: TaskConfig) => void;
  onStop?: () => void;
  isRunning?: boolean;
  /** Optional controlled value (lets a parent set the textarea, e.g. from ObjectiveSuggester). */
  value?: string;
  onChange?: (v: string) => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSubmit,
  onStop,
  isRunning = false,
  value,
  onChange,
}) => {
  const [internal, setInternal] = useState('');
  const [displayName, setDisplayName] = useState('');
  const isControlled = value !== undefined;
  const input = isControlled ? (value as string) : internal;
  const setInput = (v: string) => {
    if (!isControlled) setInternal(v);
    onChange?.(v);
  };
  const [useCustomMiningDirection, setUseCustomMiningDirection] = useState(false);
  const [config] = useState<Partial<TaskConfig>>({
    librarySuffix: '',
  });
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Advanced panel state — universe + date overrides
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [universe, setUniverse] = useState<string>('sp500');
  const [customTickersText, setCustomTickersText] = useState('');
  const [trainStart, setTrainStart] = useState('2008-01-02');
  const [trainEnd, setTrainEnd] = useState('2015-12-31');
  const [validStart, setValidStart] = useState('2016-01-04');
  const [validEnd, setValidEnd] = useState('2016-12-30');
  const [testStart, setTestStart] = useState('2017-01-03');
  const [testEnd, setTestEnd] = useState('2026-05-07');
  const [universes, setUniverses] = useState<UniverseSummary[]>([]);
  const [bundle, setBundle] = useState<QlibBundleInfo | null>(null);

  useEffect(() => {
    getQlibBundle().then((r) => {
      if (r.success && r.data) setBundle(r.data);
    }).catch(() => {});
  }, []);

  // When the bundle loads, clamp default testEnd / trainEnd / validEnd if they
  // exceed the bundle's last_date — this prevents the silent PortAnaRecord
  // failure mode where the conf asks for data past available bars.
  useEffect(() => {
    if (!bundle?.last_date) return;
    const last = bundle.last_date;
    setTestEnd((v) => (v && v > last ? last : v));
    setTrainEnd((v) => (v && v > last ? last : v));
    setValidEnd((v) => (v && v > last ? last : v));
    const first = bundle.first_date;
    if (first) {
      setTrainStart((v) => (v && v < first ? first : v));
      setValidStart((v) => (v && v < first ? first : v));
      setTestStart((v) => (v && v < first ? first : v));
    }
  }, [bundle?.last_date, bundle?.first_date]);
  const [autoDetect, setAutoDetect] = useState(true);
  const [detectedUniverse, setDetectedUniverse] = useState<string | null>(null);
  const [detectReason, setDetectReason] = useState<string>('');
  const [detecting, setDetecting] = useState(false);

  // Parse custom ticker text → cleaned array
  const customTickers = customTickersText
    .split(/[\s,;]+/)
    .map((t) => t.trim().toUpperCase())
    .filter((t) => t && /^[A-Z0-9.\-]+$/.test(t));

  // Load available universes on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listUniverses();
        if (!cancelled && res.success && res.data) {
          setUniverses(res.data.universes || []);
        }
      } catch {
        // backend offline; keep static defaults
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Debounced LLM auto-detect on input change (only when auto + non-empty)
  useEffect(() => {
    if (!autoDetect) {
      setDetectedUniverse(null);
      return;
    }
    if (!input.trim()) {
      setDetectedUniverse(null);
      return;
    }
    const timer = window.setTimeout(async () => {
      setDetecting(true);
      try {
        const res = await detectUniverse(input.trim());
        if (res.success && res.data) {
          setDetectedUniverse(res.data.universe);
          setDetectReason(res.data.reason || '');
          if (res.data.universe && res.data.universe !== universe) {
            setUniverse(res.data.universe);
          }
        }
      } catch {
        // silent
      } finally {
        setDetecting(false);
      }
    }, 1200);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, autoDetect]);

  const examplePrompts = [
    '💹 Mine momentum factors — focus on short-term reversal with volume confirmation',
    '💰 Explore value/growth combinations with sector neutralization',
    '📊 Build factors based on technical indicators, focusing on RSI & MACD',
  ];

  const handleSubmit = () => {
    if (isRunning) return;
    const suffix = config.librarySuffix?.trim() || undefined;
    onSubmit({
      userInput: input.trim(),
      displayName: displayName.trim() || undefined,
      universe: universe === 'custom' ? 'custom' : (universe || undefined),
      customTickers: universe === 'custom' && customTickers.length >= 2 ? customTickers : undefined,
      trainStart: trainStart || undefined,
      trainEnd: trainEnd || undefined,
      validStart: validStart || undefined,
      validEnd: validEnd || undefined,
      testStart: testStart || undefined,
      testEnd: testEnd || undefined,
      useCustomMiningDirection,
      ...config,
      librarySuffix: suffix,
    } as TaskConfig);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [input]);

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 pb-6">
      <div className="container mx-auto px-6">
        
        {/* Example Prompts */}
        {!input && !isRunning && (
          <div className="flex flex-wrap justify-center gap-2 mb-3 overflow-x-auto pb-2 scrollbar-hide">
            {examplePrompts.map((prompt, idx) => (
              <button
                key={idx}
                onClick={() => setInput(prompt)}
                className="glass rounded-xl px-4 py-2 text-sm text-muted-foreground hover:text-foreground hover:scale-105 transition-all whitespace-nowrap flex items-center gap-2 card-hover"
              >
                <Sparkles className="h-3 w-3" />
                {prompt}
              </button>
            ))}
          </div>
        )}

        {/* Main Input */}
        <div className="gradient-border">
          <div className="gradient-border-content">
            <div className="glass-strong rounded-xl p-4">
              {/* Icon bar: Custom mining direction etc. */}
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <button
                  type="button"
                  onClick={() => setUseCustomMiningDirection((v) => !v)}
                  title={useCustomMiningDirection ? 'Use research direction from Settings (enabled)' : 'Use research direction from Settings (click to enable)'}
                  className={`p-2 rounded-lg transition-all ${
                    useCustomMiningDirection
                      ? 'bg-primary/15 text-primary ring-1 ring-primary/30'
                      : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
                  }`}
                >
                  <Compass className="h-4 w-4" />
                </button>
                <span
                  className={`text-xs ${
                    useCustomMiningDirection ? 'text-primary font-medium' : 'text-muted-foreground'
                  }`}
                >
                  Custom research direction
                </span>
                <div className="flex-1 min-w-[180px] flex items-center gap-2 border-l border-border pl-3 ml-1">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground shrink-0">
                    Run name
                  </span>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="optional, e.g. 'Q2 vol experiment'"
                    disabled={isRunning}
                    className="flex-1 bg-transparent text-xs placeholder:text-muted-foreground/60 focus:outline-none border-b border-transparent focus:border-primary/50"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setAdvancedOpen((v) => !v)}
                  className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground border-l border-border pl-3 ml-1"
                >
                  {advancedOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  Advanced
                  <span className="text-[9px] font-mono text-muted-foreground/70">
                    ({universe === 'custom' ? `${customTickers.length} tickers` : universe} · test→{testEnd})
                  </span>
                </button>
              </div>

              {/* Advanced panel */}
              {advancedOpen && (
                <div className="mb-3 p-3 rounded-md border border-border bg-secondary/20 space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          Universe
                        </label>
                        <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer">
                          <input
                            type="checkbox"
                            checked={autoDetect}
                            onChange={(e) => setAutoDetect(e.target.checked)}
                            className="h-3 w-3"
                          />
                          <Wand2 className="h-3 w-3" /> auto-pick from objective
                          {detecting && <Loader2 className="h-3 w-3 animate-spin" />}
                        </label>
                      </div>
                      <select
                        value={universe}
                        onChange={(e) => setUniverse(e.target.value)}
                        disabled={isRunning}
                        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs focus:border-primary focus:outline-none"
                      >
                        {universes.map((u) => (
                          <option key={u.name} value={u.name}>
                            {u.name} ({u.ticker_count} tickers)
                          </option>
                        ))}
                        <option value="custom">custom (specify tickers)</option>
                      </select>
                      {detectedUniverse && autoDetect && detectedUniverse === universe && detectReason && (
                        <div className="text-[10px] text-violet-300 mt-1 italic">
                          ↪ {detectReason}
                        </div>
                      )}
                      {universe === 'custom' && (
                        <>
                          <input
                            type="text"
                            value={customTickersText}
                            onChange={(e) => setCustomTickersText(e.target.value)}
                            placeholder="AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, AMD"
                            disabled={isRunning}
                            className="w-full mt-1.5 rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono focus:border-primary focus:outline-none"
                          />
                          <div
                            className={`text-[10px] mt-1 ${
                              customTickers.length < 2
                                ? 'text-destructive'
                                : customTickers.length < 30
                                ? 'text-amber-300'
                                : 'text-emerald-300'
                            }`}
                          >
                            {customTickers.length} ticker{customTickers.length === 1 ? '' : 's'} parsed
                            {customTickers.length < 2 && ' — need at least 2'}
                            {customTickers.length >= 2 && customTickers.length < 30 &&
                              ' — RankIC will be noisy; ≥30 recommended'}
                            {customTickers.length >= 30 && ' — good for stable RankIC'}
                          </div>
                        </>
                      )}
                    </div>

                    <div>
                      <label className="text-[10px] uppercase tracking-wider text-muted-foreground block mb-1">
                        Date splits (YYYY-MM-DD)
                      </label>
                      <div className="grid grid-cols-2 gap-1.5 text-[10px]">
                        <DateField label="train start" value={trainStart} onChange={setTrainStart} disabled={isRunning} min={bundle?.first_date} max={bundle?.last_date} />
                        <DateField label="train end"   value={trainEnd}   onChange={setTrainEnd}   disabled={isRunning} min={bundle?.first_date} max={bundle?.last_date} />
                        <DateField label="valid start" value={validStart} onChange={setValidStart} disabled={isRunning} min={bundle?.first_date} max={bundle?.last_date} />
                        <DateField label="valid end"   value={validEnd}   onChange={setValidEnd}   disabled={isRunning} min={bundle?.first_date} max={bundle?.last_date} />
                        <DateField label="test start"  value={testStart}  onChange={setTestStart}  disabled={isRunning} min={bundle?.first_date} max={bundle?.last_date} />
                        <DateField label="test end"    value={testEnd}    onChange={setTestEnd}    disabled={isRunning} min={bundle?.first_date} max={bundle?.last_date} />
                      </div>
                    </div>
                  </div>
                  {bundle && !bundle.is_missing && bundle.first_date && bundle.last_date && (
                    <div className={`text-[10px] rounded border px-2 py-1.5 mt-2 ${bundle.is_stale
                      ? 'border-amber-700/40 bg-amber-950/20 text-amber-200'
                      : 'border-border bg-secondary/30 text-muted-foreground'}`}>
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono font-semibold">qlib bundle</span>
                        <span className="font-mono">{bundle.first_date} → {bundle.last_date}</span>
                        <span className="font-mono opacity-70">({bundle.trading_days} days)</span>
                        {bundle.age_days != null && (
                          <span className={`font-mono ml-auto ${bundle.is_stale ? 'text-amber-300 font-semibold' : 'opacity-60'}`}>
                            {bundle.is_stale ? `${bundle.age_days}d stale` : `fresh (${bundle.age_days}d old)`}
                          </span>
                        )}
                      </div>
                      {bundle.is_stale && (
                        <div className="mt-1 text-[9px] leading-relaxed">
                          ⚠ Bundle hasn't been refreshed in over a week. Run{' '}
                          <code className="font-mono bg-amber-950/40 px-1 rounded">scripts/fetch_qlib_data.py --extend</code>{' '}
                          before mining so test segments include recent bars and PortAnaRecord can produce IR / portfolio metrics.
                        </div>
                      )}
                    </div>
                  )}
                  {bundle?.is_missing && (
                    <div className="text-[10px] rounded border border-red-700/40 bg-red-950/20 text-red-200 px-2 py-1.5 mt-2 leading-relaxed">
                      ⚠ <strong>qlib bundle is missing.</strong> Mining will fail. Run{' '}
                      <code className="font-mono bg-red-950/40 px-1 rounded">scripts/fetch_qlib_data.py --universe sp500 --start 2008-01-02 --rebuild</code>{' '}
                      first. See <code className="font-mono">docs/data_setup.md</code>.
                    </div>
                  )}
                  <div className="text-[10px] text-muted-foreground italic border-t border-border pt-2">
                    Date pickers are capped to the bundle's actual coverage. Mining
                    metrics are computed on the test segment, so a longer test
                    window = noisier per-iteration scores but more honest.
                  </div>
                </div>
              )}
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <textarea
                    ref={textareaRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={
                      isRunning
                        ? 'Experiment running… you can switch to other pages — the task will not be interrupted'
                        : useCustomMiningDirection
                        ? 'Custom research direction enabled — will use the option from Settings → Research direction'
                        : 'Describe your factor-mining goal, or enable "Custom research direction" to use one from Settings (Shift+Enter for newline, Enter to send)'
                    }
                    disabled={isRunning}
                    className="w-full bg-transparent text-base placeholder:text-muted-foreground focus:outline-none resize-none"
                    rows={1}
                    style={{ maxHeight: '120px' }}
                  />
                </div>

                <div className="flex items-center gap-2">
                  {isRunning && onStop ? (
                    <button
                      onClick={onStop}
                      className="p-2.5 rounded-lg bg-red-500 text-white hover:bg-red-600 transition-all hover:scale-105 active:scale-95"
                      title="Stop experiment"
                    >
                      <Square className="h-5 w-5" />
                    </button>
                  ) : (
                    <button
                      onClick={handleSubmit}
                      disabled={isRunning}
                      className="p-2.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all hover:scale-105 active:scale-95"
                      title="Send (Enter)"
                    >
                      <Send className="h-5 w-5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const DateField: React.FC<{
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  min?: string | null;
  max?: string | null;
}> = ({ label, value, onChange, disabled, min, max }) => {
  const outOfRange =
    (min && value && value < min) || (max && value && value > max);
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        min={min ?? undefined}
        max={max ?? undefined}
        title={outOfRange ? `Outside bundle range (${min} → ${max})` : undefined}
        className={`rounded border bg-background px-1.5 py-1 text-[11px] font-mono focus:outline-none ${
          outOfRange
            ? 'border-amber-600 text-amber-300 focus:border-amber-500'
            : 'border-border focus:border-primary'
        }`}
      />
    </label>
  );
};
