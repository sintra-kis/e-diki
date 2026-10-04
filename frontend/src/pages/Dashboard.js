import { useEffect, useMemo, useState } from "react";
import { Bell, Plus, Users, LogOut, Scroll, ShieldAlert } from "lucide-react";
import { Wordmark } from "@/constants/brand";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import CaseCard from "@/components/CaseCard";
import AddCaseDialog from "@/components/AddCaseDialog";
import NowHearingBanner from "@/components/NowHearingBanner";
import Notifications from "@/components/Notifications";
import GroupsDialog from "@/components/GroupsDialog";
import ContactsDialog from "@/components/ContactsDialog";

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [cases, setCases] = useState([]);
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [showGroups, setShowGroups] = useState(false);
  const [showNotes, setShowNotes] = useState(false);
  const [unread, setUnread] = useState(0);
  const [pending, setPending] = useState([]); // unverified emails/numbers used by existing cases
  const [showContacts, setShowContacts] = useState(false);

  const loadCases = () => api.get("/cases").then((r) => setCases(r.data))
    .catch(() => {}) // keep the last known state on a transient network error
    .finally(() => setLoading(false));
  const loadPending = () => api.get("/contacts/pending").then((r) => setPending(r.data || [])).catch(() => {});
  const loadGroups = () => api.get("/groups").then((r) => setGroups(r.data)).catch(() => {});

  useEffect(() => {
    loadCases(); loadGroups(); loadPending();
    const t = setInterval(loadCases, 30000); // keep cards fresh
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, []);

  const groupName = useMemo(() => Object.fromEntries(groups.map((g) => [g.id, g.name])), [groups]);
  const feedDown = cases.length > 0 && cases.every((c) => c.feed_ok === false);

  const upsert = (c) => setCases((p) => {
    const i = p.findIndex((x) => x.id === c.id);
    if (i === -1) return [c, ...p];
    const n = [...p]; n[i] = c; return n;
  });

  return (
    <div className="relative z-10 min-h-screen">
      {/* Header */}
      <header className="glass sticky top-0 z-40 border-b border-[var(--border)]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Wordmark logoSize={34} />
            <div className="text-[11px] text-[var(--txt-3)] hidden md:block border-l border-[var(--border-strong)] pl-3 leading-tight">
              Παρακολούθηση πινακίων<br />σε πραγματικό χρόνο
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
              style={{ background: "var(--surface)", border: "1px solid var(--border-strong)" }}
              data-testid="feed-health">
              <span className={`w-1.5 h-1.5 rounded-full ${feedDown ? "bg-rose-500" : "bg-emerald-500 live-dot"}`} />
              <span className="text-[var(--txt-2)]">{feedDown ? "e-diki εκτός" : "e-diki ενεργό"}</span>
            </div>

            <button data-testid="groups-btn" onClick={() => setShowGroups(true)} className="btn-ghost w-9 h-9 grid place-items-center"><Users className="w-4 h-4" /></button>

            <div className="relative">
              <button data-testid="notifications-btn" onClick={() => setShowNotes((s) => !s)} className="btn-ghost w-9 h-9 grid place-items-center relative">
                <Bell className="w-4 h-4" />
                {unread > 0 && <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-rose-500 text-[10px] font-bold text-white grid place-items-center">{unread}</span>}
              </button>
              <Notifications open={showNotes} onToggle={() => setShowNotes(false)} onCountChange={setUnread} />
            </div>

            <button data-testid="add-case-btn" onClick={() => setShowAdd(true)} className="btn-primary px-4 h-9 flex items-center gap-1.5 text-sm">
              <Plus className="w-4 h-4" /><span className="hidden sm:inline">Νέα υπόθεση</span>
            </button>
            <button data-testid="logout-btn" onClick={logout} className="btn-ghost w-9 h-9 grid place-items-center"><LogOut className="w-4 h-4" /></button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">Καλησπέρα, {user?.name?.split(" ")[0] || "συνάδελφε"}.</h1>
          <p className="text-[var(--txt-2)] mt-1">Οι υποθέσεις που παρακολουθείτε και η κατάστασή τους στο πινάκιο.</p>
        </div>

        {pending.length > 0 && (
          <div className="card p-4 mb-6 flex flex-wrap items-center justify-between gap-3" data-testid="verify-banner">
            <div className="flex items-start gap-3">
              <ShieldAlert className="w-5 h-5 mt-0.5 text-amber-600 shrink-0" />
              <div className="text-sm">
                <div className="font-semibold">Οι ειδοποιήσεις email/SMS είναι σε αναμονή</div>
                <div className="text-[var(--txt-2)]">Επαληθεύστε {pending.length === 1 ? "το στοιχείο" : "τα στοιχεία"} ειδοποίησης για να συνεχίσετε να τις λαμβάνετε.</div>
              </div>
            </div>
            <button data-testid="verify-banner-btn" onClick={() => setShowContacts(true)} className="btn-primary px-4 py-2 text-sm">Επαλήθευση</button>
          </div>
        )}

        <NowHearingBanner cases={cases} />

        {loading ? (
          <div className="text-center py-20 text-[var(--txt-3)]">Φόρτωση…</div>
        ) : cases.length === 0 ? (
          <div className="card p-12 text-center" data-testid="empty-state">
            <Scroll className="w-12 h-12 mx-auto mb-4 text-[var(--txt-3)]" strokeWidth={1.25} />
            <h3 className="text-2xl font-semibold tracking-tight mb-2">Καμία υπόθεση ακόμη</h3>
            <p className="text-[var(--txt-2)] max-w-md mx-auto mb-6">
              Προσθέστε την πρώτη σας υπόθεση για παρακολούθηση. Θα αντλήσουμε το πινάκιο από το e-diki
              και θα σας ειδοποιήσουμε μόλις πλησιάσει η σειρά της.
            </p>
            <button onClick={() => setShowAdd(true)} className="btn-primary px-6 py-2.5 inline-flex items-center gap-2">
              <Plus className="w-4 h-4" /> Προσθήκη υπόθεσης
            </button>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="cases-grid">
            {cases.map((c) => (
              <CaseCard key={c.id} c={c} groupName={c.group_id ? groupName[c.group_id] : null}
                onChange={upsert} onDelete={(id) => setCases((p) => p.filter((x) => x.id !== id))} />
            ))}
          </div>
        )}
      </main>

      <ContactsDialog open={showContacts} onClose={() => { setShowContacts(false); loadPending(); }} pending={pending}
        onVerified={(kind, value) => setPending((p) => p.filter((x) => !(x.kind === kind && x.value === value)))} />
      <AddCaseDialog open={showAdd} onClose={() => setShowAdd(false)} onAdded={upsert} groups={groups} defaultEmail={user?.email} />
      <GroupsDialog open={showGroups} onClose={() => setShowGroups(false)} groups={groups} onChange={() => { loadGroups(); loadCases(); }} />
    </div>
  );
}
