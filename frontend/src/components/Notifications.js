import { useEffect, useRef, useState } from "react";
import { Bell, Check, X } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";

const TYPE_ICON = {
  approaching: "🔔", status_change: "⚖️", progress: "➡️", stuck: "⚠️", feed_down: "📡", feed_restored: "✅", verify_needed: "🛡️",
};

export default function Notifications({ open, onToggle, onCountChange }) {
  const [notes, setNotes] = useState([]);
  const seen = useRef(new Set());
  const first = useRef(true);

  const load = async () => {
    try {
      const { data } = await api.get("/notifications");
      // toast newly-arrived unread notifications (skip initial load)
      if (!first.current) {
        data.filter((n) => !seen.current.has(n.id) && !n.read).forEach((n) => {
          const fn = (n.type === "stuck" || n.type === "feed_down") ? toast.warning : n.type === "approaching" ? toast.success : toast;
          fn(n.title, { description: n.message });
        });
      }
      data.forEach((n) => seen.current.add(n.id));
      first.current = false;
      setNotes(data);
      onCountChange(data.filter((n) => !n.read).length);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, []);

  const markAll = async () => { await api.post("/notifications/read-all"); load(); };

  if (!open) return null;
  const unread = notes.filter((n) => !n.read).length;

  return (
    <div data-testid="notifications-panel" className="absolute right-0 top-14 w-[360px] max-w-[92vw] card z-50 fadeup overflow-hidden" style={{ boxShadow: "var(--shadow-lg)" }}>
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2"><Bell className="w-4 h-4 text-[var(--txt-2)]" />
          <span className="font-semibold text-sm">Ειδοποιήσεις</span>
          {unread > 0 && <span className="text-[11px] px-1.5 rounded-full bg-rose-500 text-white">{unread}</span>}
        </div>
        <div className="flex gap-1">
          {unread > 0 && <button data-testid="mark-all-read" onClick={markAll} className="btn-ghost px-2.5 py-1 text-xs flex items-center gap-1"><Check className="w-3 h-3" />Όλα</button>}
          <button onClick={onToggle} className="btn-ghost w-7 h-7 grid place-items-center"><X className="w-3.5 h-3.5" /></button>
        </div>
      </div>
      <div className="max-h-[60vh] overflow-y-auto">
        {notes.length === 0 && <div className="p-8 text-center text-sm text-[var(--txt-3)]">Καμία ειδοποίηση ακόμη.</div>}
        {notes.map((n) => (
          <div key={n.id} data-testid={`notification-${n.id}`}
            className={`px-4 py-3 border-b border-[var(--border)] ${n.read ? "opacity-60" : ""}`}>
            <div className="flex gap-2.5">
              <span className="text-lg leading-none">{TYPE_ICON[n.type] || "🔔"}</span>
              <div className="min-w-0">
                <div className="text-sm font-semibold">{n.title}</div>
                <div className="text-xs text-[var(--txt-2)] mt-0.5 leading-relaxed">{n.message}</div>
                <div className="text-[10px] text-[var(--txt-3)] mt-1">{new Date(n.created_at).toLocaleString("el-GR")}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
