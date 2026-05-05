import { useState } from "react";
import { C } from "../theme.js";
import { Card, SectionHeader, Button, Badge, Empty } from "../components/Card.jsx";

// User Mapping — central to AvePoint/BitTitan: bulk source→destination user pairing.
export default function UserMapping({ direction, notify }) {
  const [mappings, setMappings] = useState([]);
  const [csvText, setCsvText] = useState("");
  const [showImport, setShowImport] = useState(false);

  const sourceLabel = direction === "gw_to_m365" ? "Google Workspace User" : "Microsoft 365 User";
  const destLabel   = direction === "gw_to_m365" ? "Microsoft 365 UPN"   : "GCP Identity";

  const parseCsv = () => {
    const rows = csvText.trim().split("\n").map(line => line.split(",").map(s => s.trim())).filter(r => r.length >= 2 && r[0] && r[1]);
    const newMappings = rows.map(([source, dest, license]) => ({
      source, dest, license: license || "(none)", status: "pending",
    }));
    setMappings(prev => [...prev, ...newMappings]);
    setCsvText(""); setShowImport(false);
    notify(`Imported ${newMappings.length} user mappings`, "success");
  };

  const removeMapping = (idx) => {
    setMappings(prev => prev.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <SectionHeader
        title="User Mapping"
        subtitle="Map source users to their destination accounts. Required before migration jobs can be scheduled."
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="secondary" onClick={() => setShowImport(v => !v)}>{showImport ? "Cancel" : "📥 Import CSV"}</Button>
            <Button variant="primary" onClick={() => notify("Use Import CSV to add users in bulk", "info")}>+ Add User</Button>
          </div>
        }
      />

      {showImport && (
        <Card style={{ marginBottom: 16, border: `1.5px solid ${C.ms}` }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 8 }}>
            Bulk Import — CSV format
          </div>
          <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 10 }}>
            One mapping per line: <code style={{ background: C.slateLight, padding: "1px 6px", borderRadius: 3, fontFamily: "monospace" }}>source@example.com,destination@example.com,License-SKU</code>
          </div>
          <textarea
            value={csvText} onChange={e => setCsvText(e.target.value)}
            placeholder={"alice@source.com,alice@dest.com,E3\nbob@source.com,bob@dest.com,E5"}
            rows={6}
            style={{
              width: "100%", boxSizing: "border-box", padding: "10px 12px",
              border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 12,
              color: C.text, background: C.surface, fontFamily: "'IBM Plex Mono', monospace",
              resize: "vertical",
            }}
          />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
            <Button variant="ghost" onClick={() => setShowImport(false)}>Cancel</Button>
            <Button variant="primary" onClick={parseCsv} disabled={!csvText.trim()}>Import Mappings</Button>
          </div>
        </Card>
      )}

      {mappings.length === 0 ? (
        <Empty
          icon="👥"
          title="No user mappings yet"
          subtitle="Import a CSV with source-to-destination user pairs to begin planning your migration. Each user will be assigned to a migration wave for batched execution."
          action={<Button variant="primary" onClick={() => setShowImport(true)}>📥 Import CSV</Button>}
        />
      ) : (
        <Card padding={0}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: C.surfaceAlt, borderBottom: `1px solid ${C.border}` }}>
                <th style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>{sourceLabel}</th>
                <th style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>→</th>
                <th style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>{destLabel}</th>
                <th style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>License</th>
                <th style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>Status</th>
                <th style={{ padding: "12px 16px", textAlign: "right", fontSize: 11, fontWeight: 700, color: C.textMuted, letterSpacing: "0.04em", textTransform: "uppercase" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((m, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: "10px 16px", color: C.text, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{m.source}</td>
                  <td style={{ padding: "10px 16px", color: C.textLight }}>→</td>
                  <td style={{ padding: "10px 16px", color: C.text, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{m.dest}</td>
                  <td style={{ padding: "10px 16px", color: C.textMuted }}>{m.license}</td>
                  <td style={{ padding: "10px 16px" }}><Badge color="neutral">{m.status}</Badge></td>
                  <td style={{ padding: "10px 16px", textAlign: "right" }}>
                    <Button size="sm" variant="ghost" onClick={() => removeMapping(i)}>Remove</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding: "10px 16px", background: C.surfaceAlt, borderTop: `1px solid ${C.border}`, fontSize: 12, color: C.textMuted }}>
            <strong>{mappings.length}</strong> user mapping{mappings.length === 1 ? "" : "s"} configured
          </div>
        </Card>
      )}
    </div>
  );
}
