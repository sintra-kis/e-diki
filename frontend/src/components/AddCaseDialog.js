import { useEffect, useState } from "react";
import { toast } from "sonner";
import { X, Loader2, Plus, Mail, MessageSquare, PhoneCall } from "lucide-react";
import api, { errMsg } from "@/lib/api";
import ContactVerify, { normalizeContact } from "@/components/ContactVerify";

const TYPES = ["Πολιτικό", "Ποινικό", "Διοικητικό"];
const CHANNELS = [
  { id: "email", label: "Email", icon: Mail },
  { id: "sms", label: "SMS", icon: MessageSquare, needsTwilio: true },
  { id: "call", label: "Τηλεφωνική κλήση", icon: PhoneCall, needsTwilio: true },
];

// Defined at module level: a component declared inside AddCaseDialog gets a new identity on every
// render, which remounts the inputs and drops focus after each keystroke.
const Field = ({ label, children }) => (
  <div><label className="label block mb-1.5">{label}</label>{children}</div>
);

export default function AddCaseDialog({ open, onClose, onAdded, groups, defaultEmail }) {
  const [f, setF] = useState({
    court_type: "Πολιτικό", court_date: "", court_name: "", court_kind: "", court_category: "",
    case_number: "", notify_email: defaultEmail || "", notify_channels: ["email"], phone: "",
    threshold: 5, group_id: "", label: "",
  });
  const [twilioOn, setTwilioOn] = useState(false);
  const [verified, setVerified] = useState([]); // [{kind, value}] proven by the current user
  const [names, setNames] = useState([]);
  const [kinds, setKinds] = useState([]);
  const [cats, setCats] = useState([]);
  const [loading, setLoading] = useState({ names: false, kinds: false, cats: false });
  const [saving, setSaving] = useState(false);

  const upd = (k, v) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    api.get("/config").then((r) => setTwilioOn(!!r.data?.twilio_enabled)).catch(() => {});
    api.get("/contacts").then((r) => setVerified(r.data || [])).catch(() => {});
  }, []);

  // The full list of courts comes straight from e-diki and depends on the type only:
  // filtering by date would hide every court without a docket that day.
  useEffect(() => {
    setNames([]); setKinds([]); setCats([]);
    upd("court_name", ""); upd("court_kind", ""); upd("court_category", "");
    if (!f.court_type) return;
    setLoading((l) => ({ ...l, names: true }));
    let stale = false; // a slower, older answer must not overwrite the current selection
    api.get("/ediki/court-names", { params: { courtType: f.court_type, date: f.court_date || undefined } })
      .then((r) => { if (!stale) setNames(r.data || []); })
      .catch(() => { if (!stale) { setNames([]); toast.error("Δεν ήταν δυνατή η φόρτωση των καταστημάτων από το e-diki."); } })
      .finally(() => { if (!stale) setLoading((l) => ({ ...l, names: false })); });
    return () => { stale = true; };
    // eslint-disable-next-line
  }, [f.court_type]);

  useEffect(() => {
    setKinds([]); setCats([]); upd("court_kind", ""); upd("court_category", "");
    if (!f.court_name) return;
    setLoading((l) => ({ ...l, kinds: true }));
    let stale = false;
    api.get("/ediki/court-kinds", { params: { courtType: f.court_type, courtName: f.court_name, date: f.court_date } })
      .then((r) => { if (!stale) setKinds(r.data || []); })
      .catch(() => { if (!stale) setKinds([]); })
      .finally(() => { if (!stale) setLoading((l) => ({ ...l, kinds: false })); });
    return () => { stale = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.court_name]);

  useEffect(() => {
    setCats([]); upd("court_category", "");
    if (!f.court_name) return;
    setLoading((l) => ({ ...l, cats: true }));
    let stale = false;
    api.get("/ediki/court-categories", { params: { courtType: f.court_type, courtName: f.court_name, courtKind: f.court_kind, date: f.court_date } })
      .then((r) => { if (!stale) setCats(r.data || []); })
      .catch(() => { if (!stale) setCats([]); })
      .finally(() => { if (!stale) setLoading((l) => ({ ...l, cats: false })); });
    return () => { stale = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.court_name, f.court_kind]);

  if (!open) return null;

  const toggleChannel = (id) => setF((p) => {
    const has = p.notify_channels.includes(id);
    const next = has ? p.notify_channels.filter((x) => x !== id) : [...p.notify_channels, id];
    return { ...p, notify_channels: next };
  });
  const needsPhone = f.notify_channels.some((c) => c === "sms" || c === "call");
  const needsEmail = f.notify_channels.includes("email");
  const isVerified = (kind, value) => verified.some((v) => v.kind === kind && v.value === normalizeContact(kind, value));
  const emailOk = !needsEmail || isVerified("email", f.notify_email);
  const phoneOk = !needsPhone || isVerified("phone", f.phone);
  const markVerified = (kind, value) => setVerified((p) => (p.some((v) => v.kind === kind && v.value === value) ? p : [...p, { kind, value }]));

  const submit = async (e) => {
    e.preventDefault();
    if (!f.notify_channels.length) { toast.error("Επιλέξτε τουλάχιστον έναν τρόπο ειδοποίησης."); return; }
    if (!emailOk || !phoneOk) { toast.error("Επαληθεύστε πρώτα το email/τηλέφωνο ειδοποιήσεων."); return; }
    setSaving(true);
    try {
      const payload = {
        ...f, group_id: f.group_id || null,
        notify_email: needsEmail ? f.notify_email : (f.notify_email || null),
        phone: needsPhone ? f.phone : null,
      };
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

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" data-testid="add-case-dialog"
      style={{ background: "rgba(245,245,247,0.6)", backdropFilter: "saturate(180%) blur(20px)", WebkitBackdropFilter: "saturate(180%) blur(20px)" }} onClick={onClose}>
      <div className="card w-full max-w-2xl max-h-[92vh] overflow-y-auto p-6 fadeup" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-2xl font-semibold tracking-tight">Νέα υπόθεση προς παρακολούθηση</h3>
          <button data-testid="add-case-close" onClick={onClose} className="btn-ghost w-9 h-9 grid place-items-center">
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
          <Field label={`Κατάστημα ${loading.names ? "…" : names.length ? `(${names.length})` : ""}`}>
            <select data-testid="field-courtname" required disabled={!names.length} className="field w-full px-3 py-2.5 text-sm"
              value={f.court_name} onChange={(e) => upd("court_name", e.target.value)}>
              <option value="">{loading.names ? "Φόρτωση από e-diki…" : "— Επιλέξτε —"}</option>
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
          <div className="sm:col-span-2" data-testid="channels">
            <label className="label block mb-1.5">Τρόπος ειδοποίησης</label>
            <div className="flex flex-wrap gap-2">
              {CHANNELS.map(({ id, label, icon: Icon, needsTwilio }) => {
                const on = f.notify_channels.includes(id);
                const off = needsTwilio && !twilioOn;
                return (
                  <button type="button" key={id} data-testid={`channel-${id}`} disabled={off}
                    aria-pressed={on} onClick={() => toggleChannel(id)}
                    title={off ? "Μη διαθέσιμο: δεν έχει ρυθμιστεί το Twilio στον διακομιστή" : undefined}
                    className={`px-4 py-2 text-sm flex items-center gap-2 rounded-full border transition ${on ? "bg-[var(--accent)] text-white border-transparent" : "btn-ghost"} ${off ? "opacity-40 cursor-not-allowed" : ""}`}>
                    <Icon className="w-4 h-4" />{label}
                  </button>
                );
              })}
            </div>
            {!twilioOn && <p className="text-[11px] text-[var(--txt-3)] mt-1.5">Το SMS και η κλήση απαιτούν ρύθμιση Twilio στον διακομιστή.</p>}
          </div>
          {needsEmail && (
            <Field label="Email ειδοποιήσεων">
              <input data-testid="field-email" type="email" required value={f.notify_email}
                onChange={(e) => upd("notify_email", e.target.value)} className="field w-full px-3 py-2.5 text-sm"
                placeholder="dikigoros@lawfirm.gr" />
              <ContactVerify kind="email" value={f.notify_email} verified={emailOk} onVerified={markVerified} />
            </Field>
          )}
          {needsPhone && (
            <Field label="Κινητό τηλέφωνο">
              <input data-testid="field-phone" type="tel" required value={f.phone}
                onChange={(e) => upd("phone", e.target.value)} className="field w-full px-3 py-2.5 text-sm"
                placeholder="69XXXXXXXX ή +30…" />
              <ContactVerify kind="phone" value={f.phone} verified={phoneOk} onVerified={markVerified} />
            </Field>
          )}
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
            <button type="button" onClick={onClose} className="btn-ghost px-5 py-2.5">Άκυρο</button>
            <button data-testid="add-case-submit" disabled={saving || !emailOk || !phoneOk}
              className="btn-primary px-6 py-2.5 flex items-center gap-2">
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Προσθήκη & Παρακολούθηση
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
