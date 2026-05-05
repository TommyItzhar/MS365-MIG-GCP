import { useState } from "react";
import { C } from "../theme.js";
import { Card, SectionHeader, Button, Badge, Empty } from "../components/Card.jsx";

// Audit Log — compliance-grade record of all admin actions.
// Required by SOC 2, ISO 27001, GDPR for migration tooling.
export default function AuditLog() {
  const [entries] = useState([
    { id: "a-001", time: "2026-05-04 14:38:21", user: "admin", action: "JOB_STARTED",        target: "Wave 1 — Engineering",       result: "success" },
    { id: "a-002", time: "2026-05-04 14:35:02", user: "admin", action: "WAVE_PROMOTED",      target: "Wave 1 — Engineering",       result: "success" },
    { id: "a-003", time: "2026-05-04 14:30:14", user: "admin", action: "USER_MAPPING_IMPORT",target: "87 mappings from CSV",       result: "success" },
    { id: "a-004", time: "2026-05-04 14:18:09", user: "admin", action: "TENANT_CONFIG_SAVED",target: "Microsoft 365 + GCP",        result: "success" },
    { id: "a-005", time: "2026-05-04 14:15:42", user: "admin", action: "DISCOVERY_RUN",      target: "Source tenant",              result: "success" },
    { id: "a-006", time: "2026-05-04 13:58:33", user: "admin", action: "AZURE_APP_REGISTERED",target: "MS365-GCP-Migration-Engine",result: "success" },
    { id: "a-007", time: "2026-05-04 13:55:01", user: "admin", action: "LOGIN",              target: "GUI session",                 result: "success" },
  ]);

  const resultColor = { success: "success", warning: "warning", failure: "danger" };

  return (
    <div>
      <SectionHeader
        title="Audit Log"
        subtitle="Tamper-evident record of every administrative action. Required for SOC 2 / ISO 27001 / GDPR compliance reviews."
        action={<Button variant="ghost">📥 Export Audit Trail</Button>}
      />

      {entries.length === 0 ? (
        <Empty icon="📜" title="No audit entries" subtitle="Admin actions are recorded here automatically." />
      ) : (
        <Card padding={0}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: C.surfaceAlt, borderBottom: `1px solid ${C.border}` }}>
                {["Timestamp", "User", "Action", "Target", "Result"].map(h => (
                  <th key={h} style={{ padding: "12px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map(e => (
                <tr key={e.id} style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: "10px 14px", color: C.textMuted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11 }}>{e.time}</td>
                  <td style={{ padding: "10px 14px", color: C.text, fontWeight: 600 }}>{e.user}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <code style={{ background: C.slateLight, padding: "2px 8px", borderRadius: 4, fontSize: 11, color: C.text, fontFamily: "'IBM Plex Mono', monospace" }}>
                      {e.action}
                    </code>
                  </td>
                  <td style={{ padding: "10px 14px", color: C.text }}>{e.target}</td>
                  <td style={{ padding: "10px 14px" }}><Badge color={resultColor[e.result]}>{e.result}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
