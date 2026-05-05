import { useState } from "react";
import { C, apiFetch } from "../theme.js";
import { Card, SectionHeader, StatCard, Badge, Button, Empty } from "../components/Card.jsx";

// Pre-Migration Discovery — modeled on AvePoint Fly's "Free Pre-Migration Discovery"
export default function Discovery({ direction, notify }) {
  const [scanning, setScanning] = useState(false);
  const [results, setResults] = useState(null);

  const runScan = async () => {
    setScanning(true);
    try {
      const url = direction === "gw_to_m365" ? "/api/v1/discovery/gw" : "/api/v1/discovery/m365";
      const res = await apiFetch(url, { method: "POST" });
      if (res.ok) {
        setResults(await res.json());
        notify("Pre-migration scan complete", "success");
      } else {
        // Mock until backend implements; show realistic example
        setResults({
          scanned_at: new Date().toISOString(),
          users: 247,
          mailboxes: { count: 247, total_gb: 1842, avg_gb: 7.5, max_gb: 48.2 },
          drives: { count: 247, total_gb: 6210, avg_gb: 25.1, files: 1842309 },
          sites: 38,
          teams: 24,
          groups: 86,
          risks: [
            { severity: "high",   message: "12 mailboxes exceed 50 GB — extended migration time" },
            { severity: "medium", message: "847 files have invalid characters in name" },
            { severity: "medium", message: "4 SharePoint lists exceed 5,000 item view threshold" },
            { severity: "low",    message: "23 distribution groups have nested membership" },
          ],
        });
        notify("Pre-migration scan complete (mock data)", "info");
      }
    } catch (_) { notify("Backend unreachable — using sample data", "warning");
      setResults(null);
    } finally { setScanning(false); }
  };

  const sevColor = { high: "danger", medium: "warning", low: "info" };

  return (
    <div>
      <SectionHeader
        title="Pre-Migration Discovery"
        subtitle="Scan the source tenant to inventory data, identify risks, and estimate migration scope."
        action={
          <Button onClick={runScan} disabled={scanning} variant="primary" size="lg">
            {scanning ? "Scanning…" : "▶ Run Discovery Scan"}
          </Button>
        }
      />

      {!results && !scanning && (
        <Empty
          icon="🔍"
          title="No scan results yet"
          subtitle="Click Run Discovery Scan to inventory your source tenant. The scan analyzes mailboxes, drives, sites, teams, and groups, then surfaces complexity risks before migration begins."
        />
      )}

      {scanning && (
        <Card>
          <div style={{ textAlign: "center", padding: 30 }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>⏳</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: C.text }}>Discovery scan in progress…</div>
            <div style={{ fontSize: 13, color: C.textMuted, marginTop: 6 }}>
              Enumerating users, mailboxes, drives, sites, teams, and groups.
            </div>
          </div>
        </Card>
      )}

      {results && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            <StatCard label="Users" value={results.users.toLocaleString()} icon="👥" accent={C.ms} />
            <StatCard label="Mailboxes" value={`${results.mailboxes.total_gb.toLocaleString()} GB`} hint={`${results.mailboxes.count} mailboxes · avg ${results.mailboxes.avg_gb} GB`} icon="✉" accent={C.ms} />
            <StatCard label="Drive Storage" value={`${results.drives.total_gb.toLocaleString()} GB`} hint={`${results.drives.files.toLocaleString()} files`} icon="📁" accent={C.gcp} />
            <StatCard label="Teams & Groups" value={`${results.teams + results.groups}`} hint={`${results.teams} teams · ${results.groups} groups · ${results.sites} sites`} icon="👫" accent={C.gw} />
          </div>

          <Card>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 14 }}>
              Migration Risks <Badge color="warning">{results.risks.length} findings</Badge>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {results.risks.map((r, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 14px", borderRadius: 6,
                  background: r.severity === "high" ? C.dangerLight : r.severity === "medium" ? C.warningLight : C.infoLight,
                  border: `1px solid ${r.severity === "high" ? C.danger : r.severity === "medium" ? C.warning : C.info}33`,
                }}>
                  <Badge color={sevColor[r.severity]}>{r.severity}</Badge>
                  <span style={{ fontSize: 13, color: C.text }}>{r.message}</span>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
