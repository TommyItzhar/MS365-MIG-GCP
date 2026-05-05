import { C } from "../theme.js";
import { Card, SectionHeader, Button, Badge, StatCard } from "../components/Card.jsx";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, Legend
} from "recharts";

// Reports — modeled on AvePoint Fly's "Validate Results" report dashboard.
// Migrated volumes, item counts, fidelity, and trends across sources/destinations.
export default function Reports({ direction, notify }) {
  const volumeByWorkload = [
    { workload: "Exchange",   migrated: 1842, failed: 12 },
    { workload: "OneDrive",   migrated: 6210, failed: 89 },
    { workload: "SharePoint", migrated: 3420, failed: 24 },
    { workload: "Teams",      migrated: 312,  failed: 7 },
    { workload: "Groups",     migrated: 86,   failed: 2 },
  ];

  const trend = [
    { day: "Mon", items: 124000 },
    { day: "Tue", items: 187000 },
    { day: "Wed", items: 215000 },
    { day: "Thu", items: 198000 },
    { day: "Fri", items: 234000 },
    { day: "Sat", items: 156000 },
    { day: "Sun", items: 89000 },
  ];

  const status = [
    { name: "Migrated",  value: 1203412, color: C.success },
    { name: "Skipped",   value: 14820,   color: C.info },
    { name: "Failed",    value: 1842,    color: C.danger },
    { name: "Pending",   value: 87320,   color: C.warning },
  ];

  return (
    <div>
      <SectionHeader
        title="Migration Reports"
        subtitle="End-to-end visibility into migration outcomes — volumes, item counts, fidelity, and trends."
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="ghost" onClick={() => notify("CSV export coming soon", "info")}>📄 Export CSV</Button>
            <Button variant="secondary" onClick={() => notify("PDF export coming soon", "info")}>🗎 Export PDF</Button>
          </div>
        }
      />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        <StatCard label="Total Migrated" value={status[0].value.toLocaleString()} hint="items completed" icon="✓" accent={C.success} />
        <StatCard label="Total Volume" value="11.9 TB" hint="data transferred" icon="📦" accent={C.ms} />
        <StatCard label="Avg Throughput" value="12.4 MB/s" hint="last 24h" icon="⚡" accent={C.gcp} />
        <StatCard label="Success Rate" value="99.8%" hint={`${status[2].value.toLocaleString()} failed`} icon="📈" accent={C.success} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, marginBottom: 16 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 14 }}>Items Migrated by Workload</div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={volumeByWorkload}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
              <XAxis dataKey="workload" tick={{ fontSize: 11, fill: C.textMuted }} />
              <YAxis tick={{ fontSize: 11, fill: C.textMuted }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="migrated" fill={C.success} name="Migrated" radius={[4, 4, 0, 0]} />
              <Bar dataKey="failed"   fill={C.danger}  name="Failed"   radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 14 }}>Status Distribution</div>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={status} dataKey="value" nameKey="name" outerRadius={90} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false}>
                {status.map((s, i) => <Cell key={i} fill={s.color} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 14 }}>Throughput — Last 7 Days (items/day)</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={trend}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
            <XAxis dataKey="day" tick={{ fontSize: 11, fill: C.textMuted }} />
            <YAxis tick={{ fontSize: 11, fill: C.textMuted }} tickFormatter={v => `${(v/1000).toFixed(0)}k`} />
            <Tooltip formatter={v => v.toLocaleString()} />
            <Line type="monotone" dataKey="items" stroke={C.ms} strokeWidth={2} dot={{ fill: C.ms, r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}
