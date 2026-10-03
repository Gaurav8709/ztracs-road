/**
 * Z-TRACS Road Intelligence - Frontend Configuration
 * window.API_BASE defines the base URL for backend API requests.
 */
if (!window.API_BASE) {
  if (typeof window !== "undefined" && window.location && window.location.hostname) {
    if (window.location.hostname.includes("vercel.app")) {
      window.API_BASE = "http://3.109.28.196:8000";
    } else if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
      window.API_BASE = "http://127.0.0.1:8000";
    } else {
      window.API_BASE = "";
    }
  } else {
    window.API_BASE = "";
  }
}

function resolveApiUrl(path) {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("blob:") || path.startsWith("data:")) {
    return path;
  }
  const base = window.API_BASE || "";
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${cleanPath}`;
}
window.resolveApiUrl = resolveApiUrl;
