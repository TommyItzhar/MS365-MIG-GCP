// Enterprise design tokens — modeled on AvePoint / BitTitan migration consoles.
export const C = {
  // Surfaces — clean, neutral, enterprise
  bg: "#f6f8fb",
  surface: "#ffffff",
  surfaceAlt: "#fafbfd",
  border: "#e4e8ee",
  borderStrong: "#cdd3dc",

  // Text
  text: "#0c1322",
  textMuted: "#5a6478",
  textLight: "#9aa3b4",

  // Brand — Microsoft 365 (primary)
  ms: "#0078d4",
  msDark: "#005a9e",
  msLight: "#e8f3fc",
  msMid: "#93c5fd",

  // Brand — Google (secondary)
  gcp: "#5b21b6",
  gcpDark: "#3f1180",
  gcpLight: "#ede9fe",
  gcpMid: "#c4b5fd",

  // Brand — Google Workspace
  gw: "#1a73e8",
  gwLight: "#e8f0fe",
  gwGreen: "#34a853",
  gwYellow: "#fbbc04",
  gwRed: "#ea4335",

  // Status
  success: "#15803d",
  successLight: "#dcfce7",
  warning: "#b45309",
  warningLight: "#fef3c7",
  danger: "#b91c1c",
  dangerLight: "#fee2e2",
  info: "#0369a1",
  infoLight: "#e0f2fe",

  // Neutral
  slate: "#475569",
  slateLight: "#f1f5f9",
};

// ── Authenticated fetch helper ─────────────────────────────────────────────
export const apiFetch = (url, options = {}) => {
  const token = localStorage.getItem("auth_token");
  const headers = { ...(options.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(url, { ...options, headers }).then(res => {
    if (res.status === 401) {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("auth_user");
      window.location.reload();
    }
    return res;
  });
};
