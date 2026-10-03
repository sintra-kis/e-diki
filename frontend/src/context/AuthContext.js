import { createContext, useContext, useEffect, useState } from "react";
import api from "@/lib/api";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=anon, obj=user
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("edikimou_token");
    if (!token) { setUser(false); setReady(true); return; }
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => { localStorage.removeItem("edikimou_token"); setUser(false); })
      .finally(() => setReady(true));
  }, []);

  const auth = async (path, payload) => {
    const { data } = await api.post(`/auth/${path}`, payload);
    localStorage.setItem("edikimou_token", data.access_token);
    setUser(data.user);
    return data.user;
  };

  const login = (email, password) => auth("login", { email, password });
  const register = (name, email, password) => auth("register", { name, email, password });
  const logout = () => { localStorage.removeItem("edikimou_token"); setUser(false); };

  return (
    <AuthCtx.Provider value={{ user, ready, login, register, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}
