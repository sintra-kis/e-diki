export const STATUS = {
  dikazetai:     { label: "Δικάζεται",    cls: "text-amber-700 bg-amber-100 border-amber-200", dot: "bg-amber-500" },
  anamenetai:    { label: "Αναμένεται",   cls: "text-sky-700 bg-sky-50 border-sky-200", dot: "bg-sky-500" },
  diakopike:     { label: "Διακόπηκε",    cls: "text-orange-700 bg-orange-50 border-orange-200", dot: "bg-orange-500" },
  oloklirothike: { label: "Ολοκληρώθηκε", cls: "text-emerald-700 bg-emerald-50 border-emerald-200", dot: "bg-emerald-500" },
  anavlithike:   { label: "Αναβλήθηκε",   cls: "text-rose-700 bg-rose-50 border-rose-200", dot: "bg-rose-500" },
  unknown:       { label: "Σε αναζήτηση", cls: "text-slate-600 bg-slate-100 border-slate-200", dot: "bg-slate-400" },
};

export const statusOf = (c) => {
  if (c?.matched === false) return "unknown";
  return STATUS[c?.status_key] ? c.status_key : (c?.started ? "anamenetai" : "unknown");
};

export function StatusBadge({ k, testid }) {
  const s = STATUS[k] || STATUS.unknown;
  return (
    <span data-testid={testid}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold ${s.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot} ${k === "dikazetai" ? "live-dot" : ""}`} />
      {s.label}
    </span>
  );
}
