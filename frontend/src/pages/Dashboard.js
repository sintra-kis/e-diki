import { useEffect, useMemo, useState } from "react";
import { Scale, Bell, Plus, Users, LogOut, Scroll } from "lucide-react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import CaseCard from "@/components/CaseCard";
import AddCaseDialog from "@/components/AddCaseDialog";
import NowHearingBanner from "@/components/NowHearingBanner";
import Notifications from "@/components/Notifications";
import GroupsDialog from "@/components/GroupsDialog";

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [cases, setCases] = useState([]);
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [showGroups, setShowGroups] = useState(false);
  const [showNotes, setShowNotes] = useState(false);
  const [unread, setUnread] = useState(0);

  const loadCases = () => api.get("/cases").then((r) => setCases(r.data)).finally(() => setLoading(false));
  const loadGroups = () => api.get("/groups").then((r) => setGroups(r.data)).catch(() => {});

  useEffect(() => {
    loadCases(); loadGroups();
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
      <header className="sticky top-0 z-40 border-b border-[var(--border)]" style={{ background: "rgba(11,15,23,0.85)", backdropFilter: "blur(12px)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg grid place-items-center" style={{ background: "var(--gold-soft)", border: "1px solid var(--gold)" }}>
              <Scale className="w-5 h-5" style={{ color: "var(--gold)" }} />
            </div>
            <div>
              <div className="font-serif text-lg leading-none">e-diki<span style={{ color: "var(--gold)" }}>Μου</span></div>
              <div className="text-[10px] text-[var(--txt-3)] hidden sm:block">Παρακολούθηση Πινακίων σε Πραγματικό Χρόνο</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
              style={{ background: feedDown ? "rgba(244,63,94,0.12)" : "rgba(16,185,129,0.12)", border: `1px solid ${feedDown ? "rgba(244,63,94,0.4)" : "rgba(16,185,129,0.4)"}` }}
              data-testid="feed-health">
              <span className={`w-1.5 h-1.5 rounded-full ${feedDown ? "bg-rose-400" : "bg-emerald-400 live-dot"}`} />
              <span className={feedDown ? "text-rose-300" : "text-emerald-300"}>{feedDown ? "e-diki εκτός" : "e-diki ενεργό"}</span>
            </div>

            <button data-testid="groups-btn" onClick={() => setShowGroups(true)} className="btn-ghost w-9 h-9 rounded-lg grid place-items-center"><Users className="w-4 h-4" /></button>

            <div className="relative">
              <button data-testid="notifications-btn" onClick={() => setShowNotes((s) => !s)} className="btn-ghost w-9 h-9 rounded-lg grid place-items-center relative">
                <Bell className="w-4 h-4" />
                {unread > 0 && <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-amber-400 text-[10px] font-bold text-black grid place-items-center">{unread}</span>}
              </button>
              <Notifications open={showNotes} onToggle={() => setShowNotes(false)} onCountChange={setUnread} />
            </div>

            <button data-testid="add-case-btn" onClick={() => setShowAdd(true)} className="btn-gold px-3.5 h-9 rounded-lg flex items-center gap-1.5 text-sm">
              <Plus className="w-4 h-4" /><span className="hidden sm:inline">Νέα υπόθεση</span>
            </button>
            <button data-testid="logout-btn" onClick={logout} className="btn-ghost w-9 h-9 rounded-lg grid place-items-center"><LogOut className="w-4 h-4" /></button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <h1 className="font-serif text-3xl sm:text-4xl">Καλησπέρα, {user?.name?.split(" ")[0] || "συνάδελφε"}.</h1>
          <p className="text-[var(--txt-2)] mt-1">Οι υποθέσεις που παρακολουθείτε και η κατάστασή τους στο πινάκιο.</p>
        </div>

        <NowHearingBanner cases={cases} />

        {loading ? (
          <div className="text-center py-20 text-[var(--txt-3)]">Φόρτωση…</div>
        ) : cases.length === 0 ? (
          <div className="card p-12 text-center" data-testid="empty-state">
            <Scroll className="w-12 h-12 mx-auto mb-4" style={{ color: "var(--gold)" }} />
            <h3 className="font-serif text-2xl mb-2">Καμία υπόθεση ακόμη</h3>
            <p className="text-[var(--txt-2)] max-w-md mx-auto mb-6">
              Προσθέστε την πρώτη σας υπόθεση για παρακολούθηση. Θα αντλήσουμε το πινάκιο από το e-diki
              και θα σας ειδοποιήσουμε μόλις πλησιάσει η σειρά της.
            </p>
            <button onClick={() => setShowAdd(true)} className="btn-gold px-6 py-2.5 rounded-xl inline-flex items-center gap-2">
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

      <AddCaseDialog open={showAdd} onClose={() => setShowAdd(false)} onAdded={upsert} groups={groups} defaultEmail={user?.email} />
      <GroupsDialog open={showGroups} onClose={() => setShowGroups(false)} groups={groups} onChange={() => { loadGroups(); loadCases(); }} />
    </div>
  );
}
