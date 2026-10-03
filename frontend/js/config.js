/**
 * Z-TRACS Road Intelligence - Frontend Configuration
 * window.API_BASE defines the base URL for backend API requests.
 * Empty string ("") means same origin (unified mode on port 8000).
 * In split mode (frontend served on port 3000), set to "http://127.0.0.1:8000".
 */
window.API_BASE = window.API_BASE || "";

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
