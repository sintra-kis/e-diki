import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Auth from "@/pages/Auth";
import Dashboard from "@/pages/Dashboard";

function Gate({ children }) {
  const { user, ready } = useAuth();
  if (!ready) return <div className="min-h-screen grid place-items-center text-[var(--txt-2)]">Φόρτωση…</div>;
  return user ? children : <Navigate to="/login" replace />;
}

function Entry() {
  const { user, ready } = useAuth();
  if (!ready) return null;
  return user ? <Navigate to="/" replace /> : <Auth />;
}

export default function App() {
  return (
    <AuthProvider>
      <Toaster position="top-right" theme="light" closeButton toastOptions={{ style: { borderRadius: 16, boxShadow: "var(--shadow-md)" } }} />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Entry />} />
          <Route path="/" element={<Gate><Dashboard /></Gate>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
