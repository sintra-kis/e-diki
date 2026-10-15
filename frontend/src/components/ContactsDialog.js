import { X, Mail, Phone } from "lucide-react";
import ContactVerify from "@/components/ContactVerify";

// Lists the emails/numbers used by existing cases that are not verified yet. Until the owner proves
// them, the server keeps in-app notifications going but pauses email/SMS/call alerts.
export default function ContactsDialog({ open, onClose, pending, onVerified }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" data-testid="contacts-dialog"
      style={{ background: "rgba(245,245,247,0.6)", backdropFilter: "saturate(180%) blur(20px)", WebkitBackdropFilter: "saturate(180%) blur(20px)" }}
      onClick={onClose}>
      <div className="card w-full max-w-md p-6 fadeup" style={{ boxShadow: "var(--shadow-lg)" }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-2xl font-semibold tracking-tight">Επαλήθευση στοιχείων</h3>
          <button onClick={onClose} className="btn-ghost w-9 h-9 grid place-items-center"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-sm text-[var(--txt-2)] mb-5">
          Για να στέλνουμε ειδοποιήσεις σε email ή τηλέφωνο, πρέπει να βεβαιωθούμε ότι σας ανήκουν.
          Θα σας στείλουμε έναν κωδικό μίας χρήσης.
        </p>
        {pending.length === 0 && <div className="text-sm text-emerald-700" data-testid="contacts-all-verified">Όλα τα στοιχεία σας είναι επαληθευμένα.</div>}
        <div className="space-y-4">
          {pending.map((p) => {
            const Icon = p.kind === "email" ? Mail : Phone;
            return (
              <div key={`${p.kind}:${p.value}`} className="elev rounded-xl p-3" data-testid={`pending-${p.kind}`}>
                <div className="flex items-center gap-2 text-sm font-medium"><Icon className="w-4 h-4 text-[var(--txt-3)]" />{p.value}</div>
                <ContactVerify kind={p.kind} value={p.value} verified={false} onVerified={onVerified} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
