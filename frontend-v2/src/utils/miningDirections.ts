/**
 * Reference mining directions list and default direction parsing (consistent with "Mining Direction" in settings)
 * Each direction can attach up to 3 factors' "short name", "expression", "meaning", displayed on hover
 */

export interface FactorHint {
  shortName: string;
  expression: string;
  meaning: string;
}

export interface MiningDirectionItem {
  label: string;
  /** Up to 3 factors, displayed when hovering over the direction */
  factors?: FactorHint[];
}

/** Reference mining directions (Alpha158(20) style, can be added/deleted/modified as needed; factors can be filled from original_direction.json) */
export const REFERENCE_MINING_DIRECTIONS: MiningDirectionItem[] = [
  {
    label: 'Price-volume relationship & open-price return',
    factors: [
      { shortName: 'KMID', expression: '(close-open)/open', meaning: 'Open-to-close return' },
      { shortName: 'KUP', expression: '(high-max(open,close))/open', meaning: 'Upper wick relative to open' },
      { shortName: 'KLOW', expression: '(min(open,close)-low)/open', meaning: 'Lower wick relative to open' },
    ],
  },
  { label: 'Short-term momentum / return', factors: [] },
  { label: 'Volume ratio / volume surge confirmation', factors: [] },
  { label: 'Volatility / price stability', factors: [] },
  { label: 'Range / high-low band', factors: [] },
  { label: 'RSV / overbought-oversold', factors: [] },
  { label: 'Moving-average ratio / trend', factors: [] },
  { label: 'Wick ratio / candlestick patterns', factors: [] },
  { label: 'Body ratio / bull-bear strength', factors: [] },
  { label: 'Return volatility / risk', factors: [] },
  { label: 'High-low relative position', factors: [] },
  { label: 'Volume-price divergence / confirmation', factors: [] },
  { label: 'Multi-period momentum combined', factors: [] },
  { label: 'Volume-normalized features', factors: [] },
  { label: 'Price relative to moving average', factors: [] },
];

/** Get direction label (compatible with object or string) */
export function getDirectionLabel(item: MiningDirectionItem): string {
  return typeof item === 'string' ? item : item.label;
}

interface StoredMiningDirectionConfig {
  miningDirectionMode?: 'selected' | 'random';
  selectedMiningDirectionIndices?: number[];
}

/** Get a default mining direction from saved config (one of the selected list, or a random one) */
export function getDefaultMiningDirection(): string {
  try {
    const raw = localStorage.getItem('quantaalpha_config');
    if (!raw) return '';
    const config = JSON.parse(raw) as StoredMiningDirectionConfig;
    const indices = config?.selectedMiningDirectionIndices ?? [];
    const list = REFERENCE_MINING_DIRECTIONS;
    if (!list.length || !indices.length) return '';
    const validIndices = indices.filter((i) => i >= 0 && i < list.length);
    if (!validIndices.length) return '';
    if (config?.miningDirectionMode === 'random') {
      const idx = validIndices[Math.floor(Math.random() * validIndices.length)];
      return getDirectionLabel(list[idx]);
    }
    return getDirectionLabel(list[validIndices[0]]);
  } catch {
    return '';
  }
}
