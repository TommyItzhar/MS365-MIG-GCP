import { useState } from "react";
import { C } from "../theme.js";
import { Card, SectionHeader, Button, Badge, Empty } from "../components/Card.jsx";

// Schedule — calendar view of upcoming migrations.
export default function Schedule({ direction, notify }) {
  const [items] = useState([
    { id: "s-1", date: "2026-05-12", time: "09:00", wave: "Pilot",     users: 5,   workloads: ["exchange", "onedrive"] },
    { id: "s-2", date: "2026-05-19", time: "22:00", wave: "Wave 1",    users: 87,  workloads: ["exchange", "onedrive", "teams"] },
    { id: "s-3", date: "2026-05-26", time: "22:00", wave: "Wave 2",    users: 64,  workloads: ["exchange", "onedrive", "sharepoint"] },
    { id: "s-4", date: "2026-06-02", time: "22:00", wave: "Wave 3",    users: 91,  workloads: ["exchange", "onedrive", "teams", "sharepoint"] },
  ]);

  return (
    <div>
      <SectionHeader
        title="Migration Schedule"
        subtitle="Upcoming migration windows. Schedule waves during off-hours to minimize user impact."
        action={<Button variant="primary" onClick={() => notify("Schedule editor coming soon", "info")}>+ Schedule Wave</Button>}
      />

      {items.length === 0 ? (
        <Empty icon="📅" title="Nothing scheduled" subtitle="Schedule a migration wave to populate this view." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {items.map(item => (
            <Card key={item.id}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <div style={{
                    width: 64, height: 64, borderRadius: 8,
                    background: `linear-gradient(135deg, ${C.ms}, ${C.gcp})`,
                    color: "#fff", display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center",
                    flexShrink: 0,
                  }}>
                    <div style={{ fontSize: 11, fontWeight: 600, opacity: 0.85 }}>{item.date.split("-")[1]}/{item.date.split("-")[2]}</div>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{item.time}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 4 }}>{item.wave}</div>
                    <div style={{ fontSize: 12, color: C.textMuted, display: "flex", gap: 12 }}>
                      <span>👥 {item.users} users</span>
                      <span>•</span>
                      <span>{item.workloads.length} workload{item.workloads.length === 1 ? "" : "s"}</span>
                    </div>
                    <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                      {item.workloads.map(w => (
                        <Badge key={w} color="info" size="sm">{w}</Badge>
                      ))}
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <Button size="sm" variant="ghost" onClick={() => notify(`Editing ${item.wave}`, "info")}>Edit</Button>
                  <Button size="sm" variant="primary" onClick={() => notify(`${item.wave} promoted`, "success")}>Run Now</Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
