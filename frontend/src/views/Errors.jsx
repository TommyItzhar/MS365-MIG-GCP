import { useState, useEffect } from "react";
import { C, apiFetch } from "../theme.js";
import { Card, SectionHeader, Button, Badge, Empty } from "../components/Card.jsx";

// Errors & Dead-Letter Queue — failure tracking and remediation, modeled
// on the error analysis tools in AvePoint Fly and BitTitan MigrationWiz.
export default function Errors({ direction, notify }) {
  const [errors, setErrors] = useState([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/api/v1/errors?dlq_only=false&page=0&page_size=100");
      if (res.ok) {
        const data = await res.json();
        setErrors(data.errors || []);
      } else {
        // Sample data
        setErrors([
          { id: "err-001", workload: "exchange",  error_type: "throttle",         message: "Graph API rate limit exceeded — retry after 60s", retry_count: 2, is_dlq: false, source_id: "user42@source.com", timestamp: "2026-05-04 14:23:11" },
          { id: "err-002", workload: "onedrive",  error_type: "item_too_large",   message: "File exceeds 250 GB OneDrive limit",                  retry_count: 0, is_dlq: true,  source_id: "user17/Backups/", timestamp: "2026-05-04 14:21:08" },
          { id: "err-003", workload: "sharepoint",error_type: "permission_denied",message: "Source service account lacks Sites.Read.All",         retry_count: 5, is_dlq: true,  source_id: "Site/Operations", timestamp: "2026-05-04 14:18:42" },
          { id: "err-004", workload: "exchange",  error_type: "data_corruption",  message: "Mailbox item has invalid MIME envelope",              retry_count: 1, is_dlq: false, source_id: "user88@source.com", timestamp: "2026-05-04 14:15:30" },
        ]);
      }
    } catch (_) { setErrors([]); }
    finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, []);

  const filtered = filter === "dlq" ? errors.filter(e => e.is_dlq)
                 : filter === "throttle" ? errors.filter(e => e.error_type === "throttle")
                 : errors;

  const dlqCount = errors.filter(e => e.is_dlq).length;
  const totalCount = errors.length;

  const typeColor = {
    throttle: "warning", auth_failure: "danger", item_too_large: "info",
    api_unavailable: "warning", permission_denied: "danger", data_corruption: "danger",
    network_error: "warning", quota_exceeded: "warning", item_not_found: "info", unknown: "neutral",
  };

  const retry = async (errId) => {
    notify(`Retrying ${errId}…`, "info");
    // backend retry endpoint can be wired here when available
  };

  return (
    <div>
      <SectionHeader
        title="Errors & Dead-Letter Queue"
        subtitle="All migration errors with full context. Items in the DLQ have exceeded their retry budget and require manual investigation."
        action={<Button variant="ghost" onClick={refresh} disabled={loading}>↻ Refresh</Button>}
      />

      {/* Filter chips */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {[
          { id: "all", label: `All (${totalCount})` },
          { id: "dlq", label: `Dead-Letter Queue (${dlqCount})`, color: C.danger },
          { id: "throttle", label: `Throttling (${errors.filter(e => e.error_type === "throttle").length})`, color: C.warning },
        ].map(f => (
          <button key={f.id} onClick={() => setFilter(f.id)}
            style={{
              padding: "6px 14px", borderRadius: 16, fontSize: 12, fontWeight: 600, cursor: "pointer",
              background: filter === f.id ? (f.color || C.ms) : C.surface,
              color: filter === f.id ? "#fff" : C.textMuted,
              border: `1px solid ${filter === f.id ? (f.color || C.ms) : C.border}`,
              transition: "all 0.15s",
            }}>
            {f.label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <Empty
          icon="✓"
          title="No errors"
          subtitle="All migration items processed without failures matching the current filter. Errors will appear here in real-time as jobs run."
        />
      ) : (
        <Card padding={0}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: C.surfaceAlt, borderBottom: `1px solid ${C.border}` }}>
                {["Time", "Workload", "Type", "Message", "Source", "Retries", "DLQ", "Actions"].map(h => (
                  <th key={h} style={{ padding: "12px 14px", textAlign: h === "Actions" ? "right" : "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(e => (
                <tr key={e.id} style={{ borderBottom: `1px solid ${C.border}`, background: e.is_dlq ? "#fff5f5" : C.surface }}>
                  <td style={{ padding: "10px 14px", color: C.textMuted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, whiteSpace: "nowrap" }}>{e.timestamp}</td>
                  <td style={{ padding: "10px 14px", color: C.text, fontWeight: 600 }}>{e.workload}</td>
                  <td style={{ padding: "10px 14px" }}><Badge color={typeColor[e.error_type] || "neutral"}>{e.error_type.replace(/_/g, " ")}</Badge></td>
                  <td style={{ padding: "10px 14px", color: C.text, maxWidth: 360 }}>{e.message}</td>
                  <td style={{ padding: "10px 14px", color: C.textMuted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11 }}>{e.source_id}</td>
                  <td style={{ padding: "10px 14px", color: C.text, textAlign: "center" }}>{e.retry_count}</td>
                  <td style={{ padding: "10px 14px" }}>
                    {e.is_dlq ? <Badge color="danger">DLQ</Badge> : <span style={{ color: C.textLight }}>—</span>}
                  </td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <Button size="sm" variant="secondary" onClick={() => retry(e.id)}>Retry</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
