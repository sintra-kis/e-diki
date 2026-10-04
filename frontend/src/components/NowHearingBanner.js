import { Radio } from "lucide-react";
import { statusOf } from "@/components/status";

export default function NowHearingBanner({ cases }) {
  // pick the most relevant active case: one being heard, else closest to its turn
  const active = cases.filter((c) => c.matched && c.started);
  if (!active.length) return null;

  const hearing = active.find((c) => statusOf(c) === "dikazetai");
  const closest = [...active]
    .filter((c) => ["anamenetai", "diakopike"].includes(statusOf(c)) && c.remaining_ahead != null)
    .sort((a, b) => a.remaining_ahead - b.remaining_ahead)[0];
  const focus = hearing || closest || active[0];
  const isHearing = statusOf(focus) === "dikazetai";

  return (
    <div data-testid="now-hearing-banner" className="card p-6 sm:p-7 mb-6">
      <div className="flex flex-wrap items-center gap-6 justify-between">
        <div>
          <div className="inline-flex items-center gap-2 mb-3">
            <Radio className="w-4 h-4 live-dot text-emerald-500" />
            <span className="label">Ζωντανή συνεδρίαση</span>
          </div>
          <div className="text-[var(--txt-2)] text-sm">Τώρα δικάζεται</div>
          <div className="text-4xl font-bold tracking-tight">
            Σειρά #{focus.now_hearing_serial || focus.target_serial || "—"}
          </div>
          {focus.now_hearing_subject && (
            <div className="text-sm text-[var(--txt-2)] mt-2 max-w-lg">{focus.now_hearing_subject}</div>
          )}
          <div className="text-xs text-[var(--txt-3)] mt-1.5">
            {focus.court_name} · {focus.court_kind || focus.court_type}
            {focus.room && focus.room !== "-" ? ` · Αίθουσα ${focus.room}` : ""}
          </div>
        </div>

        <div className="text-right">
          <div className="label mb-1">{isHearing ? "Η υπόθεσή σας" : "Για τη δική σας υπόθεση"}</div>
          {isHearing ? (
            <div className="text-2xl font-semibold text-amber-600">Δικάζεται!</div>
          ) : (
            <div>
              <span className="text-6xl font-bold tracking-tight tabular-nums">{focus.remaining_ahead ?? "—"}</span>
              <div className="text-xs text-[var(--txt-3)]">{focus.remaining_ahead === 1 ? "υπόθεση μπροστά" : "υποθέσεις μπροστά"} (#{focus.target_serial})</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
