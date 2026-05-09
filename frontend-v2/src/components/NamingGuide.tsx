import React from 'react';
import { ChevronDown, ChevronRight, HelpCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';

/**
 * Inline disclosure that explains the three QA naming conventions
 * (log dir / workspace / factor library) and how they relate.
 *
 * Use it on History, Models > Build new, and Factor Library pages so the
 * user can demystify the IDs they see in dropdowns / cards.
 */
export const NamingGuide: React.FC<{ defaultOpen?: boolean }> = ({ defaultOpen = false }) => {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <Card>
      <CardContent className="py-3 px-4">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
        >
          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          <HelpCircle className="size-3.5" />
          What do these names mean? (log dir vs workspace vs library)
        </button>

        {open && (
          <div className="mt-3 space-y-3 text-xs text-foreground/90">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="space-y-1 rounded border border-border bg-secondary/30 p-2">
                <div className="font-semibold text-foreground">Log dir</div>
                <div className="font-mono text-[10px] text-muted-foreground break-all">
                  log/2026-05-08_02-13-32-…
                </div>
                <p className="text-muted-foreground leading-snug">
                  The orchestrator's <em>session log</em>. Holds the trajectory pool, evolution
                  state, AI verdict. Created when you start mining from the chat box. Shown in:{' '}
                  <strong className="text-foreground">History</strong>.
                </p>
              </div>

              <div className="space-y-1 rounded border border-border bg-secondary/30 p-2">
                <div className="font-semibold text-foreground">Workspace</div>
                <div className="font-mono text-[10px] text-muted-foreground break-all">
                  data/results/workspace_exp_20260507_171646
                </div>
                <p className="text-muted-foreground leading-snug">
                  The rdagent <em>factor-execution sandbox</em>. Holds per-iteration sandboxes
                  with the gate-filtered <code className="font-mono">combined_factors_df.parquet</code>
                  {' '}used to train models. Shown in:{' '}
                  <strong className="text-foreground">Models → Build new</strong>.
                </p>
              </div>

              <div className="space-y-1 rounded border border-border bg-secondary/30 p-2">
                <div className="font-semibold text-foreground">Factor library</div>
                <div className="font-mono text-[10px] text-muted-foreground break-all">
                  data/factorlib/all_factors_library_exp_…json
                </div>
                <p className="text-muted-foreground leading-snug">
                  The persisted <em>factor catalog</em> — JSON of every admitted factor with
                  metrics. Shown in: <strong className="text-foreground">Factor Library</strong>.
                </p>
              </div>
            </div>

            <div className="text-muted-foreground leading-relaxed">
              <strong className="text-foreground">Linkage:</strong>{' '}
              workspace <code className="font-mono">workspace_exp_X</code> ↔ library{' '}
              <code className="font-mono">all_factors_library_exp_X.json</code> (suffix-matched).
              Log↔workspace is inferred by start-time mtime today; future runs will record the
              link explicitly via a <code className="font-mono">manifest.json</code> in the log
              dir.
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
