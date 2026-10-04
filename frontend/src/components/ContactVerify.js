import { useEffect, useState } from "react";
import { toast } from "sonner";
import { BadgeCheck, Loader2 } from "lucide-react";
import api, { errMsg } from "@/lib/api";

// Mirrors the backend normalisation so an already-verified number is recognised as typed.
export function normalizeContact(kind, value) {
  const v = (value || "").trim();
  if (kind === "email") return v.toLowerCase();
  const p = v.replace(/[^\d+]/g, "");
  if (!p) return "";
  if (p.startsWith("+")) return p;
  if (p.startsWith("00")) return "+" + p.slice(2);
  if (p.startsWith("0")) return "+30" + p.slice(1);
  if (p.length === 10) return "+30" + p;
  return "+" + p;
}

export default function ContactVerify({ kind, value, verified, onVerified }) {
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  // a different address/number needs a fresh code
  useEffect(() => { setSent(false); setCode(""); }, [kind, value]);

  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  if (!value) return null;
  if (verified) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-emerald-700 mt-1.5" data-testid={`verified-${kind}`}>
        <BadgeCheck className="w-3.5 h-3.5" /> Επαληθευμένο
      </div>
    );
  }

  const request = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/contacts/request", { kind, value });
      if (data.already_verified) { onVerified(kind, data.value); return; }
      setSent(true); setCooldown(60);
      toast.success(kind === "email" ? "Στάλθηκε κωδικός στο email σας." : "Στάλθηκε κωδικός με SMS.");
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/contacts/verify", { kind, value, code: code.trim() });
      onVerified(kind, data.value);
      toast.success("Η επαλήθευση ολοκληρώθηκε.");
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2" data-testid={`verify-${kind}`}>
      {!sent ? (
        <button type="button" onClick={request} disabled={busy} data-testid={`send-code-${kind}`}
          className="btn-ghost px-3 py-1 text-xs flex items-center gap-1.5">
          {busy && <Loader2 className="w-3 h-3 animate-spin" />} Αποστολή κωδικού επαλήθευσης
        </button>
      ) : (
        <>
          <input data-testid={`code-input-${kind}`} inputMode="numeric" maxLength={6} value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="field px-3 py-1.5 text-sm font-mono w-28 tracking-widest" placeholder="6 ψηφία" />
          <button type="button" onClick={confirm} disabled={busy || code.length < 6} data-testid={`confirm-code-${kind}`}
            className="btn-primary px-3 py-1.5 text-xs flex items-center gap-1.5">
            {busy && <Loader2 className="w-3 h-3 animate-spin" />} Επιβεβαίωση
          </button>
          <button type="button" onClick={request} disabled={busy || cooldown > 0}
            className="text-xs text-[var(--txt-2)] underline disabled:no-underline disabled:opacity-60">
            {cooldown > 0 ? `Νέος κωδικός σε ${cooldown}″` : "Νέος κωδικός"}
          </button>
        </>
      )}
    </div>
  );
}
