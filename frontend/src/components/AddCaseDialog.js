import { useEffect, useState } from "react";
import { toast } from "sonner";
import { X, Loader2, Plus } from "lucide-react";
import api, { errMsg } from "@/lib/api";

const TYPES = ["Πολιτικό", "Ποινικό", "Διοικητικό"];

export default function AddCaseDialog({ open, onClose, onAdded, groups, defaultEmail }) {
  const [f, setF] = useState({
    court_type: "Πολιτικό", court_date: "", court_name: "", court_kind: "", court_category: "",
    case_number: "", notify_email: defaultEmail || "", threshold: 5, group_id: "", label: "",
  });
  const [names, setNames] = useState([]);
  const [kinds, setKinds] = useState([]);
  const [cats, setCats] = useState([]);
  const [loading, setLoading] = useState({ names: false, kinds: false, cats: false });
  const [saving, setSaving] = useState(false);

  const upd = (k, v) => setF((p) => ({ ...p, [k]: v }));

  // cascade: names depend on type+date
  useEffect(() => {
    setNames([]); setKinds([]); setCats([]);
    upd("court_name", ""); upd("court_kind", ""); upd("court_category", "");
    if (!f.court_type || !f.court_date) return;
    setLoading((l) => ({ ...l, names: true }));
    api.get("/ediki/court-names", { params: { courtType: f.court_type, date: f.court_date } })
      .then((r) => setNames(r.data || []))
      .catch(() => setNames([]))
      .finally(() => setLoading((l) => ({ ...l, names: false })));
  }, [f.court_type, f.court_date]);

  useEffect(() => {
    setKinds([]); setCats([]); upd("court_kind", ""); upd("court_category", "");
    if (!f.court_name) return;
    setLoading((l) => ({ ...l, kinds: true }));
    api.get("/ediki/court-kinds", { params: { courtType: f.court_type, courtName: f.court_name, date: f.court_date } })
      .then((r) => setKinds(r.data || []))
      .catch(() => setKinds([]))
      .finally(() => setLoading((l) => ({ ...l, kinds: false })));
  }, [f.court_name]);

  useEffect(() => {
    setCats([]); upd("court_category", "");
    if (!f.court_name) return;
    setLoading((l) => ({ ...l, cats: true }));
    api.get("/ediki/court-categories", { params: { courtType: f.court_type, courtName: f.court_name, courtKind: f.court_kind, date: f.court_date } })
      .then((r) => setCats(r.data || []))
      .catch(() => setCats([]))
      .finally(() => setLoading((l) => ({ ...l, cats: false })));
  }, [f.court_name, f.court_kind]);

  if (!open) return null;

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...f, group_id: f.group_id || null };
      const { data } = await api.post("/cases", payload);
      if (data.matched === false)
        toast.warning("Αποθηκεύτηκε, αλλά η υπόθεση δεν εντοπίστηκε ακόμη στο πινάκιο. Θα συνεχίσουμε να ελέγχουμε.");
      else toast.success("Η υπόθεση προστέθηκε και εντοπίστηκε στο πινάκιο.");
      onAdded(data);
      onClose();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSaving(false);
    }
  };

  const Field = ({ label, children }) => (
    <div><label className="label block mb-1.5">{label}</label>{children}</div>
  );

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" data-testid="add-case-dialog"
      style={{ background: "rgba(5,8,13,0.7)", backdropFilter: "blur(6px)" }} onClick={onClose}>
      <div className="card w-full max-w-2xl max-h-[92vh] overflow-y-auto p-6 fadeup" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-serif text-2xl">Νέα υπόθεση προς παρακολούθηση</h3>
          <button data-testid="add-case-close" onClick={onClose} className="btn-ghost w-9 h-9 rounded-lg grid place-items-center">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={submit} className="grid sm:grid-cols-2 gap-4">
          <Field label="Ημερομηνία">
            <input data-testid="field-date" type="date" required value={f.court_date}
              onChange={(e) => upd("court_date", e.target.value)} className="field w-full px-3 py-2.5 text-sm" />
          </Field>
          <Field label="Τύπος">
            <select data-testid="field-type" className="field w-full px-3 py-2.5 text-sm" value={f.court_type}
              onChange={(e) => upd("court_type", e.target.value)}>
              {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label={`Κατάστημα ${loading.names ? "…" : ""}`}>
            <select data-testid="field-courtname" required disabled={!names.length} className="field w-full px-3 py-2.5 text-sm"
              value={f.court_name} onChange={(e) => upd("court_name", e.target.value)}>
              <option value="">{f.court_date ? "— Επιλέξτε —" : "Επιλέξτε πρώτα ημερομηνία"}</option>
              {names.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </Field>
          <Field label={`Δικαστήριο ${loading.kinds ? "…" : ""}`}>
            <select data-testid="field-courtkind" disabled={!kinds.length} className="field w-full px-3 py-2.5 text-sm"
              value={f.court_kind} onChange={(e) => upd("court_kind", e.target.value)}>
              <option value="">— Όλα —</option>
              {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </Field>
          <Field label={`Διαδικασία ${loading.cats ? "…" : ""}`}>
            <select data-testid="field-category" disabled={!cats.length} className="field w-full px-3 py-2.5 text-sm"
              value={f.court_category} onChange={(e) => upd("court_category", e.target.value)}>
              <option value="">— Όλες —</option>
              {cats.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </Field>
          <Field label="Αριθμός Υπόθεσης (ΓΑΚ/ΕΑΚ/ΑΒΜ ή Α/Α)">
            <input data-testid="field-casenumber" required value={f.case_number}
              onChange={(e) => upd("case_number", e.target.value)} className="field w-full px-3 py-2.5 text-sm font-mono"
              placeholder="π.χ. 11545/2026" />
          </Field>
          <Field label="Email ειδοποιήσεων">
            <input data-testid="field-email" type="email" required value={f.notify_email}
              onChange={(e) => upd("notify_email", e.target.value)} className="field w-full px-3 py-2.5 text-sm"
              placeholder="dikigoros@lawfirm.gr" />
          </Field>
          <Field label="Ειδοποίηση όταν απομένουν">
            <select data-testid="field-threshold" className="field w-full px-3 py-2.5 text-sm" value={f.threshold}
              onChange={(e) => upd("threshold", parseInt(e.target.value))}>
              {[1, 2, 3, 5, 8, 10].map((n) => <option key={n} value={n}>{n} υποθέσεις</option>)}
            </select>
          </Field>
          {groups?.length > 0 && (
            <Field label="Διαμοιρασμός σε ομάδα">
              <select data-testid="field-group" className="field w-full px-3 py-2.5 text-sm" value={f.group_id}
                onChange={(e) => upd("group_id", e.target.value)}>
                <option value="">Μόνο εγώ</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            </Field>
          )}
          <Field label="Ετικέτα (προαιρετικό)">
            <input data-testid="field-label" value={f.label} onChange={(e) => upd("label", e.target.value)}
              className="field w-full px-3 py-2.5 text-sm" placeholder="π.χ. Υπόθεση Παπαδόπουλου" />
          </Field>

          <div className="sm:col-span-2 flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-ghost px-5 py-2.5 rounded-xl">Άκυρο</button>
            <button data-testid="add-case-submit" disabled={saving}
              className="btn-gold px-6 py-2.5 rounded-xl flex items-center gap-2">
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Προσθήκη & Παρακολούθηση
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
