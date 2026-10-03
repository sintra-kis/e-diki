import { Radio, Gavel } from "lucide-react";
import { statusOf } from "@/components/status";

export default function NowHearingBanner({ cases }) {
  // pick the most relevant active case: one being heard, else closest to its turn
  const active = cases.filter((c) => c.matched && c.started);
  if (!active.length) return null;

  const hearing = active.find((c) => statusOf(c) === "dikazetai");
  const closest = [...active]
    .filter((c) => statusOf(c) === "anamenetai" && c.remaining_ahead != null)
    .sort((a, b) => a.remaining_ahead - b.remaining_ahead)[0];
  const focus = hearing || closest || active[0];
  const isHearing = statusOf(focus) === "dikazetai";

  return (
    <div data-testid="now-hearing-banner" className="card p-6 mb-6 relative overflow-hidden"
      style={{ borderColor: "var(--gold)", background: "linear-gradient(120deg,#151b28,#0f1420)" }}>
      <div className="absolute -right-10 -top-10 w-48 h-48 rounded-full" style={{ background: "var(--gold-soft)", filter: "blur(40px)" }} />
      <div className="relative z-10 flex flex-wrap items-center gap-6 justify-between">
        <div>
          <div className="inline-flex items-center gap-2 mb-3">
            <Radio className="w-4 h-4 live-dot" style={{ color: "var(--gold)" }} />
            <span className="label" style={{ color: "var(--gold)" }}>Ζωντανή Συνεδρίαση</span>
          </div>
          <div className="flex items-center gap-3">
            <Gavel className="w-7 h-7 text-amber-300" />
            <div>
              <div className="text-[var(--txt-2)] text-sm">Τώρα δικάζεται</div>
              <div className="font-serif text-3xl">
                Σειρά <span style={{ color: "var(--gold)" }}>#{focus.now_hearing_serial || focus.target_serial || "—"}</span>
              </div>
            </div>
          </div>
          {focus.now_hearing_subject && (
            <div className="text-sm text-[var(--txt-2)] mt-2 max-w-lg">{focus.now_hearing_subject}</div>
          )}
          <div className="text-xs text-[var(--txt-3)] mt-1">
            {focus.court_name} · {focus.court_kind || focus.court_type}
            {focus.room && focus.room !== "-" ? ` · Αίθουσα ${focus.room}` : ""}
          </div>
        </div>

        <div className="text-right">
          <div className="label mb-1">{isHearing ? "Η υπόθεσή σας" : "Για τη δική σας υπόθεση"}</div>
          {isHearing ? (
            <div className="font-serif text-2xl text-amber-300">Δικάζεται!</div>
          ) : (
            <div>
              <span className="font-mono text-5xl font-bold" style={{ color: "var(--gold)" }}>
                {focus.remaining_ahead ?? "—"}
              </span>
              <div className="text-xs text-[var(--txt-3)]">υποθέσεις μπροστά (#{focus.target_serial})</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
