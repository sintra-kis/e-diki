import { useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { errMsg } from "@/lib/api";
import { Logo } from "@/constants/brand";

export default function Auth() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const upd = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === "login") await login(form.email, form.password);
      else await register(form.name, form.email, form.password);
      toast.success("Καλώς ήρθατε!");
    } catch (err) { toast.error(errMsg(err)); } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen grid place-items-center px-5 py-10" style={{ background: "var(--bg)" }}>
      <div className="w-full max-w-[400px] fadeup">
        <div className="flex flex-col items-center text-center mb-8">
          <Logo size={72} className="mb-5" />
          <h1 className="text-[34px] font-bold tracking-tight leading-none">
            e-diki<span style={{ color: "var(--gold)" }}>Μου</span>
          </h1>
          <p className="text-[var(--txt-2)] mt-3 text-[15px] leading-relaxed max-w-[320px]">
            Παρακολούθηση δικασίμων σε πραγματικό χρόνο. Ειδοποίηση μόλις η υπόθεσή σας πλησιάζει στη σειρά της.
          </p>
        </div>

        <div className="card p-7">
          <div className="flex p-1 rounded-full mb-6" style={{ background: "#ECECEF" }}>
            {[["login", "Σύνδεση"], ["register", "Εγγραφή"]].map(([m, lbl]) => (
              <button key={m} data-testid={`tab-${m}`} onClick={() => setMode(m)}
                className={`flex-1 py-2 rounded-full text-sm font-semibold transition-all ${mode === m ? "bg-white shadow-sm" : "text-[var(--txt-2)]"}`}>
                {lbl}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="label block mb-1.5">Ονοματεπώνυμο</label>
                <input data-testid="auth-name-input" required value={form.name} onChange={upd("name")}
                  className="field w-full px-3.5 py-2.5 text-sm" placeholder="Μαρία Παπαδοπούλου" />
              </div>
            )}
            <div>
              <label className="label block mb-1.5">Email</label>
              <input data-testid="auth-email-input" type="email" required value={form.email} onChange={upd("email")}
                className="field w-full px-3.5 py-2.5 text-sm" placeholder="dikigoros@lawfirm.gr" />
            </div>
            <div>
              <label className="label block mb-1.5">Κωδικός</label>
              <input data-testid="auth-password-input" type="password" required value={form.password} onChange={upd("password")}
                className="field w-full px-3.5 py-2.5 text-sm" placeholder="••••••••" />
            </div>
            <button data-testid="auth-submit-btn" disabled={loading}
              className="btn-primary w-full py-3 flex items-center justify-center gap-2 text-[15px]">
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {mode === "login" ? "Σύνδεση" : "Δημιουργία λογαριασμού"}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-[var(--txt-3)] mt-6 leading-relaxed">
          Τα δεδομένα αντλούνται από το δημόσιο πινάκιο<br />e-diki.justice.gov.gr
        </p>
      </div>
    </div>
  );
}
