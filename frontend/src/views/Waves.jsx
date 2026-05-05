import { useState } from "react";
import { C } from "../theme.js";
import { Card, SectionHeader, Button, Badge, Empty } from "../components/Card.jsx";

// Migration Waves — batches of users (50–100 typical), scheduled separately.
// Modeled on AvePoint Fly's wave management and BitTitan's user/tenant bundles.
export default function Waves({ direction, notify }) {
  const [waves, setWaves] = useState([
    { id: "pilot", name: "Pilot",     users: 5,    scheduled: "2026-05-12 09:00", status: "scheduled", priority: "high" },
    { id: "wave1", name: "Wave 1 — Engineering",    users: 87,   scheduled: "2026-05-19 22:00", status: "draft",     priority: "high" },
    { id: "wave2", name: "Wave 2 — Sales",          users: 64,   scheduled: "2026-05-26 22:00", status: "draft",     priority: "medium" },
    { id: "wave3", name: "Wave 3 — Operations",     users: 91,   scheduled: "2026-06-02 22:00", status: "draft",     priority: "medium" },
  ]);

  const total = waves.reduce((s, w) => s + w.users, 0);

  const statusColor = { scheduled: "info", draft: "neutral", running: "warning", completed: "success", failed: "danger" };
  const priorityColor = { high: "danger", medium: "warning", low: "info" };

  const promote = (idx) => {
    setWaves(prev => prev.map((w, i) => i === idx ? { ...w, status: "scheduled" } : w));
    notify(`${waves[idx].name} promoted to Scheduled`, "success");
  };

  return (
    <div>
      <SectionHeader
        title="Migration Waves"
        subtitle="Schedule users in batches (waves) of 50–100 to control load on source and destination tenants. Pilot waves should run before full waves to validate configuration."
        action={
          <Button variant="primary" onClick={() => notify("Wave creation requires user mappings — see Planning → User Mapping", "info")}>
            + Create Wave
          </Button>
        }
      />

      {/* Summary strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        <Card padding={14}>
          <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>Total Waves</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.text, marginTop: 2 }}>{waves.length}</div>
        </Card>
        <Card padding={14}>
          <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>Total Users</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.text, marginTop: 2 }}>{total}</div>
        </Card>
        <Card padding={14}>
          <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>Scheduled</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.info, marginTop: 2 }}>{waves.filter(w => w.status === "scheduled").length}</div>
        </Card>
        <Card padding={14}>
          <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>Draft</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.textMuted, marginTop: 2 }}>{waves.filter(w => w.status === "draft").length}</div>
        </Card>
      </div>

      {waves.length === 0 ? (
        <Empty
          icon="🌊"
          title="No migration waves defined"
          subtitle="Create your first wave to organize users into manageable batches. Run a Pilot wave first with 5–10 users to validate your configuration before scheduling full waves."
        />
      ) : (
        <Card padding={0}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: C.surfaceAlt, borderBottom: `1px solid ${C.border}` }}>
                {["Wave", "Users", "Priority", "Scheduled", "Status", "Actions"].map(h => (
                  <th key={h} style={{ padding: "12px 16px", textAlign: h === "Actions" ? "right" : "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {waves.map((w, i) => (
                <tr key={w.id} style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: "12px 16px", color: C.text, fontWeight: 600 }}>
                    <div>{w.name}</div>
                    <div style={{ fontSize: 11, color: C.textLight, fontFamily: "'IBM Plex Mono', monospace" }}>{w.id}</div>
                  </td>
                  <td style={{ padding: "12px 16px", color: C.text, fontWeight: 700 }}>{w.users}</td>
                  <td style={{ padding: "12px 16px" }}><Badge color={priorityColor[w.priority]}>{w.priority}</Badge></td>
                  <td style={{ padding: "12px 16px", color: C.textMuted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{w.scheduled}</td>
                  <td style={{ padding: "12px 16px" }}><Badge color={statusColor[w.status]}>{w.status}</Badge></td>
                  <td style={{ padding: "12px 16px", textAlign: "right" }}>
                    {w.status === "draft" ? (
                      <Button size="sm" variant="primary" onClick={() => promote(i)}>Promote to Scheduled</Button>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => notify(`Inspect ${w.name} — full UI coming`, "info")}>View</Button>
                    )}
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
