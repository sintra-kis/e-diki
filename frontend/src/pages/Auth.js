import { useState } from "react";
import { toast } from "sonner";
import { Scale, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { errMsg } from "@/lib/api";

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
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen grid lg:grid-cols-2">
      {/* hero */}
      <div className="relative hidden lg:block overflow-hidden">
        <img
          src="https://images.unsplash.com/photo-1761700971099-6696edc79a8b?crop=entropy&cs=srgb&fm=jpg&q=85&w=1400"
          alt="" className="absolute inset-0 w-full h-full object-cover opacity-40" />
        <div className="absolute inset-0" style={{ background: "linear-gradient(120deg,#0B0F17 10%,rgba(11,15,23,0.4))" }} />
        <div className="relative z-10 h-full flex flex-col justify-between p-12">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl grid place-items-center" style={{ background: "var(--gold-soft)", border: "1px solid var(--gold)" }}>
              <Scale className="w-6 h-6" style={{ color: "var(--gold)" }} />
            </div>
            <span className="font-serif text-2xl">e-diki<span style={{ color: "var(--gold)" }}>Μου</span></span>
          </div>
          <div>
            <h1 className="font-serif text-5xl leading-tight mb-4">Το πινάκιο<br />στην παλάμη σας.</h1>
            <p className="text-[var(--txt-2)] max-w-md leading-relaxed">
              Παρακολούθηση δικασίμων σε πραγματικό χρόνο από το επίσημο e-diki. Ειδοποίηση τη στιγμή
              που η υπόθεσή σας πλησιάζει στη σειρά της — με email και μέσα στην εφαρμογή.
            </p>
          </div>
        </div>
      </div>

      {/* form */}
      <div className="relative z-10 flex items-center justify-center p-6">
        <div className="w-full max-w-sm fadeup">
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <Scale className="w-7 h-7" style={{ color: "var(--gold)" }} />
            <span className="font-serif text-2xl">e-diki<span style={{ color: "var(--gold)" }}>Μου</span></span>
          </div>
          <h2 className="font-serif text-3xl mb-1">{mode === "login" ? "Σύνδεση" : "Εγγραφή"}</h2>
          <p className="text-[var(--txt-3)] text-sm mb-7">
            {mode === "login" ? "Συνδεθείτε για να δείτε τις υποθέσεις σας." : "Δημιουργήστε λογαριασμό για να ξεκινήσετε."}
          </p>

          <form onSubmit={submit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="label block mb-1.5">Ονοματεπώνυμο</label>
                <input data-testid="auth-name-input" required value={form.name} onChange={upd("name")}
                  className="field w-full px-3.5 py-2.5 text-sm" placeholder="π.χ. Μαρία Παπαδοπούλου" />
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
              className="btn-gold w-full py-2.5 rounded-xl flex items-center justify-center gap-2">
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {mode === "login" ? "Σύνδεση" : "Εγγραφή"}
            </button>
          </form>

          <button data-testid="auth-toggle-btn" onClick={() => setMode(mode === "login" ? "register" : "login")}
            className="mt-5 text-sm text-[var(--txt-2)] hover:text-[var(--gold)] transition-colors">
            {mode === "login" ? "Δεν έχετε λογαριασμό; Εγγραφείτε" : "Έχετε ήδη λογαριασμό; Σύνδεση"}
          </button>
        </div>
      </div>
    </div>
  );
}
