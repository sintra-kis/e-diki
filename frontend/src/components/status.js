export const STATUS = {
  dikazetai:     { label: "Δικάζεται",    cls: "text-amber-300 bg-amber-500/15 border-amber-500/50 shadow-[0_0_14px_rgba(245,158,11,0.3)]", dot: "bg-amber-400" },
  anamenetai:    { label: "Αναμένεται",   cls: "text-sky-300 bg-sky-500/10 border-sky-500/40", dot: "bg-sky-400" },
  diakopike:     { label: "Διακόπηκε",    cls: "text-orange-300 bg-orange-500/10 border-orange-500/40", dot: "bg-orange-400" },
  oloklirothike: { label: "Ολοκληρώθηκε", cls: "text-emerald-300 bg-emerald-500/10 border-emerald-500/40", dot: "bg-emerald-400" },
  anavlithike:   { label: "Αναβλήθηκε",   cls: "text-rose-300 bg-rose-500/10 border-rose-500/40", dot: "bg-rose-400" },
  unknown:       { label: "Σε αναζήτηση", cls: "text-slate-300 bg-slate-500/10 border-slate-500/40", dot: "bg-slate-400" },
};

export const statusOf = (c) => {
  if (c?.matched === false) return "unknown";
  return STATUS[c?.status_key] ? c.status_key : (c?.started ? "anamenetai" : "unknown");
};

export function StatusBadge({ k, testid }) {
  const s = STATUS[k] || STATUS.unknown;
  return (
    <span data-testid={testid}
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-bold ${s.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot} ${k === "dikazetai" ? "live-dot" : ""}`} />
      {s.label}
    </span>
  );
}
