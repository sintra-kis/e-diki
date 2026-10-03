import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw, Trash2, MapPin, Gavel, Users, AlertTriangle, WifiOff } from "lucide-react";
import api, { errMsg } from "@/lib/api";
import { StatusBadge, statusOf } from "@/components/status";

function Ahead({ c }) {
  const k = statusOf(c);
  if (k === "dikazetai") return <span className="text-amber-300 font-bold">Δικάζεται τώρα</span>;
  if (k === "oloklirothike") return <span className="text-emerald-300 font-bold">Ολοκληρώθηκε</span>;
  if (k === "anavlithike") return <span className="text-rose-300 font-bold">Αναβλήθηκε</span>;
  if (c.remaining_ahead == null) return <span className="text-[var(--txt-3)]">—</span>;
  return (
    <span>
      <span className="font-mono text-2xl font-bold" style={{ color: "var(--gold)" }}>{c.remaining_ahead}</span>
      <span className="text-[var(--txt-3)] text-xs ml-1.5">υποθέσεις μπροστά</span>
    </span>
  );
}

export default function CaseCard({ c, onChange, onDelete, groupName }) {
  const [busy, setBusy] = useState(false);
  const k = statusOf(c);

  const refresh = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/cases/${c.id}/refresh`);
      onChange(data);
      toast.success("Ενημερώθηκε από το e-diki");
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const del = async () => {
    if (!window.confirm("Διαγραφή αυτής της υπόθεσης;")) return;
    try { await api.delete(`/cases/${c.id}`); onDelete(c.id); toast.success("Διαγράφηκε"); }
    catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <div data-testid={`case-card-${c.id}`} className="card p-5 fadeup relative overflow-hidden">
      {k === "dikazetai" && <div className="absolute inset-x-0 top-0 h-0.5 bg-amber-400 live-dot" />}

      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-sm font-bold" style={{ color: "var(--gold)" }}>{c.case_number}</span>
            {c.target_serial && <span className="text-xs text-[var(--txt-3)]">· σειρά #{c.target_serial}</span>}
          </div>
          {c.label && <div className="text-sm text-[var(--txt)] truncate">{c.label}</div>}
        </div>
        <StatusBadge k={k} testid={`status-badge-${c.id}`} />
      </div>

      <div className="space-y-1.5 text-sm text-[var(--txt-2)] mb-4">
        <div className="flex items-center gap-2"><MapPin className="w-3.5 h-3.5 shrink-0 text-[var(--txt-3)]" />
          <span className="truncate">{c.court_name} · {new Date(c.court_date).toLocaleDateString("el-GR")}</span></div>
        <div className="flex items-center gap-2"><Gavel className="w-3.5 h-3.5 shrink-0 text-[var(--txt-3)]" />
          <span className="truncate">{c.court_kind || c.court_type}{c.court_category ? ` · ${c.court_category}` : ""}</span></div>
        {groupName && <div className="flex items-center gap-2"><Users className="w-3.5 h-3.5 shrink-0 text-[var(--txt-3)]" />
          <span className="truncate">Ομάδα: {groupName}</span></div>}
      </div>

      {c.matched === false && (
        <div className="flex items-center gap-2 text-xs text-sky-300 bg-sky-500/10 border border-sky-500/30 rounded-lg px-3 py-2 mb-3">
          <RefreshCw className="w-3.5 h-3.5" /> Αναζήτηση στο πινάκιο… δεν εντοπίστηκε ακόμη.
        </div>
      )}
      {c.feed_ok === false && (
        <div className="flex items-center gap-2 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2 mb-3">
          <WifiOff className="w-3.5 h-3.5" /> Προσωρινό πρόβλημα σύνδεσης με το e-diki.
        </div>
      )}
      {c.stuck && (
        <div className="flex items-center gap-2 text-xs text-orange-300 bg-orange-500/10 border border-orange-500/40 rounded-lg px-3 py-2 mb-3">
          <AlertTriangle className="w-3.5 h-3.5" /> Το πινάκιο φαίνεται στάσιμο — ελέγξτε χειροκίνητα.
        </div>
      )}

      <div className="flex items-end justify-between border-t border-[var(--border)] pt-3">
        <div>
          <div className="label mb-1">Υπολείπονται</div>
          <Ahead c={c} />
        </div>
        <div className="text-right">
          {c.now_hearing_serial && (
            <div className="text-xs text-[var(--txt-2)] mb-0.5">Τώρα: <span className="font-mono text-amber-300">#{c.now_hearing_serial}</span></div>
          )}
          {c.total_cases != null && <div className="text-[11px] text-[var(--txt-3)]">{c.completed_count || 0}/{c.total_cases} ολοκληρωμένες</div>}
        </div>
      </div>

      <div className="flex gap-2 mt-4">
        <button data-testid={`refresh-case-${c.id}`} onClick={refresh} disabled={busy}
          className="btn-ghost flex-1 py-2 rounded-lg text-sm flex items-center justify-center gap-2">
          <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} /> Έλεγχος τώρα
        </button>
        <button data-testid={`delete-case-${c.id}`} onClick={del}
          className="btn-ghost w-10 rounded-lg grid place-items-center hover:!border-rose-500/60 hover:text-rose-300">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
