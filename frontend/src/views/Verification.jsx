import { useState } from "react";
import { C } from "../theme.js";
import { Card, SectionHeader, Button, Badge, StatCard, Empty } from "../components/Card.jsx";

// Verification — post-migration fidelity checks (count, checksum, metadata match).
// Equivalent to AvePoint Fly's "Validate Results" with full-fidelity checks.
export default function Verification({ direction, notify }) {
  const [results] = useState([
    { id: "v-001", workload: "exchange",  user: "alice@source.com", source_count: 12483, dest_count: 12483, checksum: "match", metadata: "match", status: "passed" },
    { id: "v-002", workload: "onedrive",  user: "alice@source.com", source_count: 4218,  dest_count: 4218,  checksum: "match", metadata: "match", status: "passed" },
    { id: "v-003", workload: "exchange",  user: "bob@source.com",   source_count: 8920,  dest_count: 8917,  checksum: "match", metadata: "mismatch", status: "warning" },
    { id: "v-004", workload: "sharepoint",user: "Site/Operations",  source_count: 2134,  dest_count: 2098,  checksum: "mismatch", metadata: "match", status: "failed" },
  ]);

  const passed = results.filter(r => r.status === "passed").length;
  const warning = results.filter(r => r.status === "warning").length;
  const failed = results.filter(r => r.status === "failed").length;

  const statusColor = { passed: "success", warning: "warning", failed: "danger" };

  return (
    <div>
      <SectionHeader
        title="Verification & Validation"
        subtitle="Post-migration fidelity checks confirm that source items are present at the destination with matching count, checksum, and metadata."
        action={<Button variant="primary" onClick={() => notify("Running verification on completed jobs…", "info")}>▶ Run Verification</Button>}
      />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <StatCard label="Passed" value={passed} hint="full fidelity" icon="✓" accent={C.success} />
        <StatCard label="Warnings" value={warning} hint="partial fidelity" icon="⚠" accent={C.warning} />
        <StatCard label="Failed" value={failed} hint="needs investigation" icon="✗" accent={C.danger} />
      </div>

      {results.length === 0 ? (
        <Empty
          icon="🔬"
          title="No verification runs yet"
          subtitle="Verification runs automatically after each migration job completes, and can be re-run on demand."
        />
      ) : (
        <Card padding={0}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: C.surfaceAlt, borderBottom: `1px solid ${C.border}` }}>
                {["Workload", "Subject", "Source", "Destination", "Checksum", "Metadata", "Status", "Actions"].map(h => (
                  <th key={h} style={{ padding: "12px 14px", textAlign: h === "Actions" ? "right" : "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map(r => (
                <tr key={r.id} style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: "10px 14px", color: C.text, fontWeight: 600 }}>{r.workload}</td>
                  <td style={{ padding: "10px 14px", color: C.text, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{r.user}</td>
                  <td style={{ padding: "10px 14px", color: C.text, fontVariantNumeric: "tabular-nums" }}>{r.source_count.toLocaleString()}</td>
                  <td style={{ padding: "10px 14px", color: r.dest_count !== r.source_count ? C.danger : C.text, fontWeight: r.dest_count !== r.source_count ? 700 : 400, fontVariantNumeric: "tabular-nums" }}>
                    {r.dest_count.toLocaleString()}
                  </td>
                  <td style={{ padding: "10px 14px" }}><Badge color={r.checksum === "match" ? "success" : "danger"}>{r.checksum}</Badge></td>
                  <td style={{ padding: "10px 14px" }}><Badge color={r.metadata === "match" ? "success" : "warning"}>{r.metadata}</Badge></td>
                  <td style={{ padding: "10px 14px" }}><Badge color={statusColor[r.status]}>{r.status}</Badge></td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <Button size="sm" variant="ghost" onClick={() => notify(`Inspecting ${r.id}`, "info")}>Details</Button>
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
