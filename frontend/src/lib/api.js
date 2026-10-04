import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const api = axios.create({ baseURL: API });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("edikimou_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// An expired or invalid session on any protected call sends the user back to the login screen.
api.interceptors.response.use(
  (r) => r,
  (error) => {
    const url = error?.config?.url || "";
    if (error?.response?.status === 401 && !url.startsWith("/auth/") && localStorage.getItem("edikimou_token")) {
      localStorage.removeItem("edikimou_token");
      window.location.reload();
    }
    return Promise.reject(error);
  }
);

export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || "").join(" ");
  return e?.message || "Κάτι πήγε στραβά";
};

export default api;
