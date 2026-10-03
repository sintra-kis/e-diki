import { useState } from "react";
import { toast } from "sonner";
import { X, Users, Copy, Plus, LogIn } from "lucide-react";
import api, { errMsg } from "@/lib/api";

export default function GroupsDialog({ open, onClose, groups, onChange }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");

  if (!open) return null;

  const create = async () => {
    if (!name.trim()) return;
    try { await api.post("/groups", { name: name.trim() }); setName(""); toast.success("Η ομάδα δημιουργήθηκε"); onChange(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  const join = async () => {
    if (!code.trim()) return;
    try { await api.post("/groups/join", { code: code.trim() }); setCode(""); toast.success("Μπήκατε στην ομάδα"); onChange(); }
    catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" data-testid="groups-dialog"
      style={{ background: "rgba(5,8,13,0.7)", backdropFilter: "blur(6px)" }} onClick={onClose}>
      <div className="card w-full max-w-md p-6 fadeup" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-serif text-2xl flex items-center gap-2"><Users className="w-5 h-5" style={{ color: "var(--gold)" }} />Ομάδες / Γραφείο</h3>
          <button onClick={onClose} className="btn-ghost w-9 h-9 rounded-lg grid place-items-center"><X className="w-4 h-4" /></button>
        </div>

        <p className="text-sm text-[var(--txt-2)] mb-4">Οι υποθέσεις που μοιράζεστε σε μια ομάδα είναι ορατές σε όλα τα μέλη της ταυτόχρονα.</p>

        <div className="space-y-2 mb-5">
          {groups.length === 0 && <div className="text-sm text-[var(--txt-3)]">Δεν ανήκετε σε καμία ομάδα ακόμη.</div>}
          {groups.map((g) => (
            <div key={g.id} data-testid={`group-row-${g.id}`} className="elev rounded-lg px-3 py-2.5 flex items-center justify-between">
              <span className="text-sm font-medium">{g.name}</span>
              <button onClick={() => { navigator.clipboard?.writeText(g.code); toast.success("Αντιγράφηκε ο κωδικός"); }}
                className="flex items-center gap-1.5 text-xs font-mono btn-ghost px-2 py-1 rounded-md" style={{ color: "var(--gold)" }}>
                {g.code} <Copy className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>

        <div className="space-y-4">
          <div>
            <label className="label block mb-1.5">Δημιουργία νέας ομάδας</label>
            <div className="flex gap-2">
              <input data-testid="group-name-input" value={name} onChange={(e) => setName(e.target.value)}
                className="field flex-1 px-3 py-2.5 text-sm" placeholder="π.χ. Δικηγορικό Γραφείο Α" />
              <button data-testid="create-group-btn" onClick={create} className="btn-gold px-4 rounded-xl flex items-center gap-1.5"><Plus className="w-4 h-4" />Δημιουργία</button>
            </div>
          </div>
          <div>
            <label className="label block mb-1.5">Είσοδος με κωδικό</label>
            <div className="flex gap-2">
              <input data-testid="group-code-input" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())}
                className="field flex-1 px-3 py-2.5 text-sm font-mono" placeholder="π.χ. A1B2C3" />
              <button data-testid="join-group-btn" onClick={join} className="btn-ghost px-4 rounded-xl flex items-center gap-1.5"><LogIn className="w-4 h-4" />Είσοδος</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
