import { useState, useEffect, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, Legend
} from "recharts";

// ── Design Tokens ────────────────────────────────────────────────────────────
// White / Purple (Google) / Blue (Microsoft) palette
const C = {
  bg: "#f8f9fc",
  surface: "#ffffff",
  border: "#e2e8f0",
  borderStrong: "#cbd5e1",
  text: "#0f172a",
  textMuted: "#64748b",
  textLight: "#94a3b8",

  // Microsoft Blue
  ms: "#0078d4",
  msDark: "#005a9e",
  msLight: "#dbeafe",
  msMid: "#93c5fd",

  // Google / GCP Purple
  gcp: "#7c3aed",
  gcpDark: "#5b21b6",
  gcpLight: "#ede9fe",
  gcpMid: "#c4b5fd",

  // Status
  success: "#059669",
  successLight: "#d1fae5",
  warning: "#d97706",
  warningLight: "#fef3c7",
  danger: "#dc2626",
  dangerLight: "#fee2e2",
  info: "#0284c7",
  infoLight: "#e0f2fe",

  // Neutral
  slate: "#475569",
  slateLight: "#f1f5f9",
};

const PHASES = [
  { id: "pre_migration", label: "1. Pre-Migration", color: C.ms, icon: "📋" },
  { id: "env_preparation", label: "2. Env Preparation", color: C.msLight, icon: "⚙️" },
  { id: "intune_offboarding", label: "3. Intune Off-board", color: "#1e40af", icon: "🔵" },
  { id: "google_mdm_onboarding", label: "4. Google MDM", color: C.gcp, icon: "🟣" },
  { id: "migration_execution", label: "5. Migration Exec", color: C.gcpDark, icon: "🚀" },
  { id: "cutover", label: "6. Cutover", color: "#7e22ce", icon: "✂️" },
  { id: "post_migration", label: "7. Post-Migration", color: "#4c1d95", icon: "✅" },
];

const WORKPLAN = [
  // Phase 1
  { num: "1", phase: "pre_migration", title: "Provision AvePoint Fly license and configure access", owner: "IT Admin", scope: "Migration team", priority: "High", notes: "SaaS or on-premises deployment", status: "not_started", progress: 0 },
  { num: "1.1", phase: "pre_migration", title: "Create dedicated M365 migration service account with full mailbox access", owner: "IT Admin", scope: "M365 tenant", priority: "High", notes: "Use API Permissions — Impersonation being deprecated", status: "not_started", progress: 0 },
  { num: "1.2", phase: "pre_migration", title: "Create GCP project and enable required APIs (Admin SDK, Gmail, Drive, Calendar, Contacts)", owner: "Cloud Admin", scope: "GCP Console", priority: "High", notes: "Sign in as Google Super Admin", status: "not_started", progress: 0 },
  { num: "1.3", phase: "pre_migration", title: "Run AvePoint Fly pre-migration discovery scan — assess mailbox sizes, data volumes, user list", owner: "Migration Lead", scope: "All mailboxes & drives", priority: "Medium", notes: "Export report to CSV for review", status: "not_started", progress: 0 },
  { num: "1.4", phase: "pre_migration", title: "Identify oversized files, forbidden characters, and deep folder structures", owner: "Migration Lead", scope: "OneDrive / SharePoint", priority: "Medium", notes: "Address issues before migration starts", status: "not_started", progress: 0 },
  { num: "1.5", phase: "pre_migration", title: "Document all shared mailboxes, resource mailboxes, and distribution groups", owner: "IT Admin", scope: "Exchange Online", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "1.6", phase: "pre_migration", title: "Define migration scope — Teams, SharePoint, OneDrive, Exchange, Groups", owner: "Migration Lead", scope: "Full M365 environment", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "1.7", phase: "pre_migration", title: "Define user batches (50–100 users per wave) and migration schedule", owner: "Project Manager", scope: "All users", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "1.8", phase: "pre_migration", title: "Define rollback plan and escalation path", owner: "Project Manager", scope: "Project governance", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "1.9", phase: "pre_migration", title: "Communicate migration timeline and impact to end users", owner: "Change Manager", scope: "All staff", priority: "Low", notes: "Include cutover date, new login instructions", status: "not_started", progress: 0 },
  // Phase 2
  { num: "2", phase: "env_preparation", title: "Configure MX routing subdomain for parallel mail flow during migration", owner: "IT Admin", scope: "DNS", priority: "High", notes: "Prevents mail loss during cutover", status: "not_started", progress: 0 },
  { num: "2.1", phase: "env_preparation", title: "Enable Gmail, Drive, Calendar, and Contacts services for all Google Workspace users", owner: "Cloud Admin", scope: "Google Admin Console", priority: "High", notes: "", status: "not_started", progress: 0 },
  { num: "2.2", phase: "env_preparation", title: "Register Azure AD application with Microsoft Graph API permissions (replacing EWS — blocked Oct 2026)", owner: "IT Admin", scope: "Azure AD / M365", priority: "High", notes: "EWS blocked Exchange Online Oct 1 2026", status: "not_started", progress: 0 },
  { num: "2.3", phase: "env_preparation", title: "Set up Google Groups to mirror M365 Groups and distribution lists", owner: "IT Admin", scope: "Google Workspace", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "2.4", phase: "env_preparation", title: "Connect AvePoint Fly to M365 as source and Google Workspace as destination", owner: "Migration Lead", scope: "AvePoint Fly", priority: "Low", notes: "", status: "not_started", progress: 0 },
  { num: "2.5", phase: "env_preparation", title: "Run Fly initial connectivity scan and validate service account permissions", owner: "Migration Lead", scope: "AvePoint Fly", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  // Phase 3
  { num: "3", phase: "intune_offboarding", title: "Identify all Autopilot-registered devices and document hardware hashes", owner: "IT Admin", scope: "Intune / Autopilot", priority: "High", notes: "Required for Autopilot deregistration", status: "not_started", progress: 0 },
  { num: "3.1", phase: "intune_offboarding", title: "Remove Autopilot device registrations from Microsoft Intune", owner: "IT Admin", scope: "Intune / Autopilot", priority: "High", notes: "Devices must be deregistered before re-enrollment", status: "not_started", progress: 0 },
  { num: "3.2", phase: "intune_offboarding", title: "Retire and wipe corporate-owned devices from Intune (or selective wipe for BYOD)", owner: "IT Admin", scope: "Intune / MEM", priority: "High", notes: "Retire = remove corporate data; Wipe = factory reset", status: "not_started", progress: 0 },
  { num: "3.3", phase: "intune_offboarding", title: "Remove Intune MDM compliance policies, configuration profiles, and app protection policies", owner: "IT Admin", scope: "Intune / MEM", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "3.4", phase: "intune_offboarding", title: "Unenroll devices from Azure AD / Entra ID (Azure AD Join or Hybrid Join)", owner: "IT Admin", scope: "Azure AD / Entra ID", priority: "High", notes: "Devices must be removed from Azure AD before joining Google", status: "not_started", progress: 0 },
  { num: "3.5", phase: "intune_offboarding", title: "Uninstall Microsoft Intune Company Portal app and Authenticator from devices", owner: "IT Admin", scope: "All managed endpoints", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "3.6", phase: "intune_offboarding", title: "Disable and decommission Intune connector / on-premises infrastructure (if hybrid)", owner: "IT Admin", scope: "On-prem / Intune", priority: "Low", notes: "", status: "not_started", progress: 0 },
  // Phase 4
  { num: "4", phase: "google_mdm_onboarding", title: "Configure Google Endpoint Management policies (password, encryption, screen lock, compliance)", owner: "Cloud Admin", scope: "Google Admin Console", priority: "High", notes: "", status: "not_started", progress: 0 },
  { num: "4.1", phase: "google_mdm_onboarding", title: "Enroll Windows devices into Google Endpoint Management using GCPW", owner: "IT Admin", scope: "Windows endpoints", priority: "High", notes: "GCPW replaces Azure AD login on Windows", status: "not_started", progress: 0 },
  { num: "4.2", phase: "google_mdm_onboarding", title: "Enroll macOS devices into Google MDM (via MDM enrollment profile)", owner: "IT Admin", scope: "macOS endpoints", priority: "High", notes: "", status: "not_started", progress: 0 },
  { num: "4.3", phase: "google_mdm_onboarding", title: "Enroll iOS/Android devices into Google Endpoint Management", owner: "IT Admin", scope: "Mobile devices", priority: "Medium", notes: "Android Enterprise or iOS supervised mode", status: "not_started", progress: 0 },
  { num: "4.4", phase: "google_mdm_onboarding", title: "Deploy Google Chrome browser and/or ChromeOS policies via Admin Console", owner: "Cloud Admin", scope: "All managed endpoints", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "4.5", phase: "google_mdm_onboarding", title: "Push Google Workspace apps (Drive, Gmail, Calendar, Meet) to managed devices", owner: "Cloud Admin", scope: "All managed endpoints", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "4.6", phase: "google_mdm_onboarding", title: "Configure Context-Aware Access (replaces Intune Conditional Access)", owner: "Security Admin", scope: "Google Admin Console", priority: "Medium", notes: "Replaces Intune Conditional Access", status: "not_started", progress: 0 },
  { num: "4.7", phase: "google_mdm_onboarding", title: "Validate device compliance and MDM reporting in Google Admin Console", owner: "IT Admin", scope: "Google Admin Console", priority: "Low", notes: "", status: "not_started", progress: 0 },
  // Phase 5
  { num: "5", phase: "migration_execution", title: "Configure migration filter policies (Contacts, Calendars, Mails, Tasks, Rules)", owner: "Migration Lead", scope: "AvePoint Fly", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "5.1", phase: "migration_execution", title: "Run pilot migration (5–10 users) — validate mail, calendar, contacts, and Drive fidelity", owner: "Migration Lead", scope: "Pilot user group", priority: "High", notes: "Fix issues before full migration", status: "not_started", progress: 0 },
  { num: "5.2", phase: "migration_execution", title: "Migrate Exchange Online → Gmail (mailboxes, calendars, contacts)", owner: "Migration Lead", scope: "All user mailboxes", priority: "High", notes: "", status: "not_started", progress: 0 },
  { num: "5.3", phase: "migration_execution", title: "Migrate OneDrive → Google Drive", owner: "Migration Lead", scope: "All user OneDrives", priority: "High", notes: "", status: "not_started", progress: 0 },
  { num: "5.4", phase: "migration_execution", title: "Migrate SharePoint Online → Google Shared Drives (review permission remapping manually)", owner: "Migration Lead", scope: "SharePoint sites", priority: "Medium", notes: "Permission models differ — manual review required", status: "not_started", progress: 0 },
  { num: "5.5", phase: "migration_execution", title: "Migrate shared mailboxes and resource mailboxes", owner: "Migration Lead", scope: "Exchange Online", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "5.6", phase: "migration_execution", title: "Migrate Microsoft Teams Chat → Google Workspace Chat (where supported by Fly)", owner: "Migration Lead", scope: "Teams / Chat", priority: "Low", notes: "", status: "not_started", progress: 0 },
  { num: "5.7", phase: "migration_execution", title: "Run delta passes to capture data modified after initial migration pass", owner: "Migration Lead", scope: "All workloads", priority: "Medium", notes: "Run close to cutover date", status: "not_started", progress: 0 },
  { num: "5.8", phase: "migration_execution", title: "Monitor AvePoint Fly dashboard — review job errors and warnings per batch", owner: "Migration Lead", scope: "AvePoint Fly", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  // Phase 6
  { num: "6", phase: "cutover", title: "Update DNS — SPF, DKIM, DMARC records for Google Workspace", owner: "IT Admin", scope: "DNS", priority: "High", notes: "", status: "not_started", progress: 0 },
  { num: "6.1", phase: "cutover", title: "Confirm end-to-end mail flow is working in Google Workspace", owner: "IT Admin", scope: "Gmail", priority: "High", notes: "", status: "not_started", progress: 0 },
  { num: "6.2", phase: "cutover", title: "Manually verify permissions on sensitive Shared Drive libraries post-migration", owner: "Security Admin", scope: "Google Shared Drives", priority: "Medium", notes: "Automated mapping is imperfect — review critical content", status: "not_started", progress: 0 },
  { num: "6.3", phase: "cutover", title: "Update embedded links and bookmarks from SharePoint/OneDrive to Google Drive URLs", owner: "Migration Lead", scope: "All migrated content", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "6.4", phase: "cutover", title: "Reconfigure user email clients (Outlook → Gmail) or deploy Google Workspace desktop clients", owner: "IT Admin", scope: "All endpoints", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "6.5", phase: "cutover", title: "Notify all users of new Google Workspace login credentials and support channels", owner: "Change Manager", scope: "All staff", priority: "High", notes: "", status: "not_started", progress: 0 },
  // Phase 7
  { num: "7", phase: "post_migration", title: "Validate migrated data volumes and review migration trend reports", owner: "Migration Lead", scope: "AvePoint Fly", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "7.1", phase: "post_migration", title: "Revoke M365 migration service account permissions and remove Azure AD app registration", owner: "IT Admin", scope: "Azure AD / M365", priority: "High", notes: "Security cleanup — remove all elevated access", status: "not_started", progress: 0 },
  { num: "7.2", phase: "post_migration", title: "Decommission M365 licenses (retain briefly for reference access)", owner: "IT Admin", scope: "M365 tenant", priority: "Medium", notes: "Agree retention period with business before cancelling", status: "not_started", progress: 0 },
  { num: "7.3", phase: "post_migration", title: "Archive or remove GCP migration project credentials", owner: "Cloud Admin", scope: "GCP Console", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "7.4", phase: "post_migration", title: "Monitor Google Workspace audit logs for anomalies post-cutover (30 days)", owner: "Security Admin", scope: "Google Admin Console", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "7.5", phase: "post_migration", title: "Confirm all devices are fully enrolled and compliant in Google MDM", owner: "IT Admin", scope: "Google Endpoint Mgmt", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "7.6", phase: "post_migration", title: "Conduct end-user training on Google Workspace (Gmail, Drive, Meet, Calendar)", owner: "Change Manager", scope: "All staff", priority: "Medium", notes: "", status: "not_started", progress: 0 },
  { num: "7.7", phase: "post_migration", title: "Document lessons learned and close migration project", owner: "Project Manager", scope: "Project team", priority: "Low", notes: "", status: "not_started", progress: 0 },
];

const MOCK_DEVICES = [
  { id: "d1", display_name: "WIN-LAPTOP-001", os_type: "windows", assigned_user: "Alice Johnson", assigned_user_email: "alice@company.com", compliance_state: "compliant", autopilot_enrolled: true, is_byod: false, status: "discovered", serial_number: "SN001" },
  { id: "d2", display_name: "WIN-DESKTOP-002", os_type: "windows", assigned_user: "Bob Smith", assigned_user_email: "bob@company.com", compliance_state: "compliant", autopilot_enrolled: false, is_byod: false, status: "discovered", serial_number: "SN002" },
  { id: "d3", display_name: "MAC-PRO-003", os_type: "macos", assigned_user: "Carol White", assigned_user_email: "carol@company.com", compliance_state: "compliant", autopilot_enrolled: false, is_byod: false, status: "intune_offboarded", serial_number: "SN003" },
  { id: "d4", display_name: "IPHONE-CEO-004", os_type: "ios", assigned_user: "David Lee", assigned_user_email: "david@company.com", compliance_state: "noncompliant", autopilot_enrolled: false, is_byod: true, status: "google_enrolled", serial_number: "SN004" },
  { id: "d5", display_name: "ANDROID-005", os_type: "android", assigned_user: "Eva Brown", assigned_user_email: "eva@company.com", compliance_state: "compliant", autopilot_enrolled: false, is_byod: true, status: "discovered", serial_number: "SN005" },
  { id: "d6", display_name: "WIN-LAPTOP-006", os_type: "windows", assigned_user: "Frank Davis", assigned_user_email: "frank@company.com", compliance_state: "compliant", autopilot_enrolled: true, is_byod: false, status: "intune_offboarding", serial_number: "SN006" },
  { id: "d7", display_name: "MAC-AIR-007", os_type: "macos", assigned_user: "Grace Wilson", assigned_user_email: "grace@company.com", compliance_state: "compliant", autopilot_enrolled: false, is_byod: false, status: "google_enrolled", serial_number: "SN007" },
  { id: "d8", display_name: "WIN-SERVER-008", os_type: "windows", assigned_user: "Henry Martin", assigned_user_email: "henry@company.com", compliance_state: "error", autopilot_enrolled: false, is_byod: false, status: "error", serial_number: "SN008" },
];

// ── Helper Components ─────────────────────────────────────────────────────────

const StatusBadge = ({ status }) => {
  const cfg = {
    not_started: { bg: C.slateLight, color: C.slate, label: "Not Started" },
    in_progress: { bg: C.infoLight, color: C.info, label: "In Progress" },
    completed: { bg: C.successLight, color: C.success, label: "Completed" },
    failed: { bg: C.dangerLight, color: C.danger, label: "Failed" },
    skipped: { bg: C.warningLight, color: C.warning, label: "Skipped" },
    // device statuses
    discovered: { bg: C.infoLight, color: C.info, label: "Discovered" },
    intune_offboarding: { bg: C.msLight, color: C.msDark, label: "Offboarding" },
    intune_offboarded: { bg: "#dbeafe", color: "#1d4ed8", label: "Offboarded" },
    google_enrolling: { bg: C.gcpLight, color: C.gcpDark, label: "Enrolling" },
    google_enrolled: { bg: C.gcpLight, color: C.gcp, label: "Enrolled" },
    compliant: { bg: C.successLight, color: C.success, label: "Compliant" },
    error: { bg: C.dangerLight, color: C.danger, label: "Error" },
  };
  const s = cfg[status] || cfg.not_started;
  return (
    <span style={{
      padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      letterSpacing: "0.04em", textTransform: "uppercase",
      background: s.bg, color: s.color,
      border: `1px solid ${s.color}30`,
    }}>
      {s.label}
    </span>
  );
};

const PriorityDot = ({ priority }) => {
  const colors = { High: C.danger, Medium: C.warning, Low: C.success };
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: "50%",
      background: colors[priority] || C.slate, marginRight: 6
    }} />
  );
};

const ProgressBar = ({ value, color = C.ms }) => (
  <div style={{ width: "100%", height: 6, background: C.slateLight, borderRadius: 3, overflow: "hidden" }}>
    <div style={{
      width: `${value}%`, height: "100%",
      background: `linear-gradient(90deg, ${color}, ${color}cc)`,
      borderRadius: 3,
      transition: "width 0.5s ease",
    }} />
  </div>
);

const Card = ({ children, style = {} }) => (
  <div style={{
    background: C.surface, border: `1px solid ${C.border}`,
    borderRadius: 8, padding: 20, ...style
  }}>
    {children}
  </div>
);

const OsIcon = ({ os }) => {
  const icons = { windows: "🪟", macos: "🍎", ios: "📱", android: "🤖", chromeos: "🌐" };
  return <span style={{ fontSize: 16 }}>{icons[os] || "💻"}</span>;
};

// ── Main App ──────────────────────────────────────────────────────────────────

export default function MigrationPlatform() {
  const [activeView, setActiveView] = useState("dashboard");
  const [tasks, setTasks] = useState(() =>
    WORKPLAN.map((t, i) => ({ ...t, id: `task-${i}` }))
  );
  const [devices, setDevices] = useState(MOCK_DEVICES);
  const [selectedDevices, setSelectedDevices] = useState([]);
  const [selectedPhase, setSelectedPhase] = useState("all");
  const [runningTasks, setRunningTasks] = useState({});
  const [notification, setNotification] = useState(null);
  const [deviceSearch, setDeviceSearch] = useState("");
  const [expandedTask, setExpandedTask] = useState(null);
  const [discoveryRunning, setDiscoveryRunning] = useState(false);

  // ── Tenants Connection state ─────────────────────────────────────────────
  const [tcConfig, setTcConfig] = useState({
    azure_tenant_id: "", azure_tenant_domain: "",
    azure_client_id: "", azure_client_secret: "",
    gcp_project_id: "", gcp_gcs_bucket: "",
    gcp_region: "us-central1", gcp_firestore_database: "(default)",
    gcp_service_account_json: "", active_environment: "dev",
  });
  const [tcLoading, setTcLoading] = useState(false);
  const [tcSaving, setTcSaving] = useState(false);
  const [tcAzureStatus, setTcAzureStatus] = useState(null);
  const [tcGcpStatus, setTcGcpStatus] = useState(null);
  const [tcAzureError, setTcAzureError] = useState(null);
  const [tcGcpError, setTcGcpError] = useState(null);
  const [tcShowSecret, setTcShowSecret] = useState(false);
  const [tcShowSaJson, setTcShowSaJson] = useState(false);
  const [tcRegisterOpen, setTcRegisterOpen] = useState(false);
  const [tcAdminToken, setTcAdminToken] = useState("");
  const [tcRegisterLoading, setTcRegisterLoading] = useState(false);
  const [tcRegisterResult, setTcRegisterResult] = useState(null);

  const notify = (msg, type = "info") => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 4000);
  };

  // Stats
  const totalTasks = tasks.length;
  const completed = tasks.filter(t => t.status === "completed").length;
  const inProgress = tasks.filter(t => t.status === "in_progress").length;
  const failed = tasks.filter(t => t.status === "failed").length;
  const overallProgress = Math.round(tasks.reduce((s, t) => s + t.progress, 0) / totalTasks);

  const phaseProgress = PHASES.map(p => ({
    ...p,
    tasks: tasks.filter(t => t.phase === p.id),
    progress: (() => {
      const pt = tasks.filter(t => t.phase === p.id);
      if (!pt.length) return 0;
      return Math.round(pt.reduce((s, t) => s + t.progress, 0) / pt.length);
    })(),
  }));

  const devicesByOs = ["windows", "macos", "ios", "android"].map(os => ({
    name: os.charAt(0).toUpperCase() + os.slice(1),
    value: devices.filter(d => d.os_type === os).length,
    color: os === "windows" ? C.ms : os === "macos" ? "#6b7280" : os === "ios" ? "#9ca3af" : C.gcp,
  }));

  const devicesByStatus = [
    { name: "Discovered", value: devices.filter(d => d.status === "discovered").length, color: C.info },
    { name: "Offboarding", value: devices.filter(d => d.status === "intune_offboarding").length, color: C.ms },
    { name: "Offboarded", value: devices.filter(d => d.status === "intune_offboarded").length, color: "#1d4ed8" },
    { name: "Enrolled (GCP)", value: devices.filter(d => d.status === "google_enrolled").length, color: C.gcp },
    { name: "Error", value: devices.filter(d => d.status === "error").length, color: C.danger },
  ];

  // Simulate task execution
  const runTask = useCallback((taskId) => {
    setTasks(prev => prev.map(t => t.id === taskId
      ? { ...t, status: "in_progress", progress: 0 }
      : t
    ));
    setRunningTasks(prev => ({ ...prev, [taskId]: true }));

    let progress = 0;
    const interval = setInterval(() => {
      progress += Math.random() * 15 + 5;
      if (progress >= 100) {
        clearInterval(interval);
        setTasks(prev => prev.map(t => t.id === taskId
          ? { ...t, status: "completed", progress: 100 }
          : t
        ));
        setRunningTasks(prev => {
          const next = { ...prev };
          delete next[taskId];
          return next;
        });
        notify("Task completed successfully", "success");
      } else {
        setTasks(prev => prev.map(t => t.id === taskId
          ? { ...t, progress: Math.round(progress) }
          : t
        ));
      }
    }, 400);
  }, []);

  const runAllInPhase = (phaseId) => {
    const phaseTasks = tasks.filter(t => t.phase === phaseId && t.status === "not_started");
    phaseTasks.forEach((t, i) => {
      setTimeout(() => runTask(t.id), i * 800);
    });
    notify(`Running all ${phaseTasks.length} tasks in phase`, "info");
  };

  const runDiscovery = () => {
    setDiscoveryRunning(true);
    notify("Device discovery started — scanning Intune...", "info");
    setTimeout(() => {
      setDiscoveryRunning(false);
      notify(`Discovery complete: ${devices.length} devices found`, "success");
    }, 3000);
  };

  const toggleDevice = (id) => {
    setSelectedDevices(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const selectAllDevices = () => {
    if (selectedDevices.length === filteredDevices.length) {
      setSelectedDevices([]);
    } else {
      setSelectedDevices(filteredDevices.map(d => d.id));
    }
  };

  const offboardSelected = () => {
    const targets = selectedDevices.length > 0 ? selectedDevices : devices.map(d => d.id);
    setDevices(prev => prev.map(d =>
      targets.includes(d.id) && d.status === "discovered"
        ? { ...d, status: "intune_offboarding" }
        : d
    ));
    notify(`Offboarding ${targets.length} device(s) from Intune...`, "info");
    setTimeout(() => {
      setDevices(prev => prev.map(d =>
        targets.includes(d.id) && d.status === "intune_offboarding"
          ? { ...d, status: "intune_offboarded" }
          : d
      ));
      notify("Intune offboarding complete", "success");
    }, 4000);
    setSelectedDevices([]);
  };

  const enrollGoogle = () => {
    const targets = devices.filter(d => d.status === "intune_offboarded").map(d => d.id);
    setDevices(prev => prev.map(d =>
      targets.includes(d.id) ? { ...d, status: "google_enrolling" } : d
    ));
    notify(`Enrolling ${targets.length} device(s) into Google MDM...`, "info");
    setTimeout(() => {
      setDevices(prev => prev.map(d =>
        targets.includes(d.id) && d.status === "google_enrolling"
          ? { ...d, status: "google_enrolled" }
          : d
      ));
      notify("Google MDM enrollment complete", "success");
    }, 5000);
  };

  // ── Tenants Connection API ───────────────────────────────────────────────
  const fetchTenantConfig = useCallback(async () => {
    setTcLoading(true);
    try {
      const res = await fetch("/api/v1/setup/tenant-config");
      if (res.ok) {
        const data = await res.json();
        setTcConfig(prev => ({ ...prev, ...data }));
      }
    } catch (_) {}
    finally { setTcLoading(false); }
  }, []);

  useEffect(() => {
    if (activeView === "tenants") fetchTenantConfig();
  }, [activeView, fetchTenantConfig]);

  const saveTenantConfig = async () => {
    setTcSaving(true);
    try {
      const res = await fetch("/api/v1/setup/tenant-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(tcConfig),
      });
      if (res.ok) { notify("Configuration saved successfully", "success"); }
      else { const e = await res.json(); notify(e.detail || "Save failed", "error"); }
    } catch (_) { notify("Backend unreachable", "error"); }
    finally { setTcSaving(false); }
  };

  const testAzure = async () => {
    setTcAzureStatus("testing"); setTcAzureError(null);
    try {
      const body = {
        tenant_id: tcConfig.azure_tenant_id,
        client_id: tcConfig.azure_client_id,
        client_secret: tcConfig.azure_client_secret !== "••••••••" ? tcConfig.azure_client_secret : undefined,
      };
      const res = await fetch("/api/v1/setup/validate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      const m = data.services?.m365;
      if (m?.ok) { setTcAzureStatus("ok"); }
      else { setTcAzureStatus("error"); setTcAzureError(m?.error || "Connection failed"); }
    } catch (_) { setTcAzureStatus("error"); setTcAzureError("Network error"); }
  };

  const testGcp = async () => {
    setTcGcpStatus("testing"); setTcGcpError(null);
    try {
      const res = await fetch("/api/v1/setup/validate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gcp_project_id: tcConfig.gcp_project_id }),
      });
      const data = await res.json();
      const g = data.services?.gcp;
      if (g?.ok) { setTcGcpStatus("ok"); }
      else { setTcGcpStatus("error"); setTcGcpError(g?.error || "Connection failed"); }
    } catch (_) { setTcGcpStatus("error"); setTcGcpError("Network error"); }
  };

  const registerAzureApp = async () => {
    if (!tcAdminToken.trim()) { notify("Paste a Global Admin access token first", "error"); return; }
    setTcRegisterLoading(true); setTcRegisterResult(null);
    try {
      const res = await fetch("/api/v1/setup/register-azure-app", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          admin_token: tcAdminToken,
          update_environment: tcConfig.active_environment,
          grant_admin_consent: true,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setTcRegisterResult(data);
        setTcConfig(prev => ({
          ...prev,
          azure_client_id: data.client_id || prev.azure_client_id,
          azure_client_secret: data.client_secret || prev.azure_client_secret,
          azure_tenant_id: data.tenant_id || prev.azure_tenant_id,
        }));
        notify("App registration created! Save the client secret now.", "success");
      } else {
        notify(data.detail?.message || data.detail || "Registration failed", "error");
      }
    } catch (_) { notify("Network error during registration", "error"); }
    finally { setTcRegisterLoading(false); }
  };

  const filteredDevices = devices.filter(d =>
    deviceSearch === "" ||
    d.display_name.toLowerCase().includes(deviceSearch.toLowerCase()) ||
    (d.assigned_user_email || "").toLowerCase().includes(deviceSearch.toLowerCase())
  );

  const filteredTasks = selectedPhase === "all"
    ? tasks
    : tasks.filter(t => t.phase === selectedPhase);

  const phaseColor = (phaseId) => {
    const p = PHASES.find(p => p.id === phaseId);
    return p ? p.color : C.slate;
  };

  // Navigation
  const NAV = [
    { id: "dashboard", icon: "◈", label: "Dashboard" },
    { id: "devices", icon: "⬡", label: "Devices" },
    { id: "workplan", icon: "≡", label: "Workplan" },
    { id: "phases", icon: "◫", label: "Phases" },
    { id: "tenants", icon: "⚿", label: "Tenants Connection" },
  ];

  return (
    <div style={{
      minHeight: "100vh", background: C.bg,
      fontFamily: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif",
      color: C.text, display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <header style={{
        background: C.surface,
        borderBottom: `2px solid ${C.border}`,
        padding: "0 32px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        height: 56, position: "sticky", top: 0, zIndex: 100,
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "4px 14px", background: `linear-gradient(135deg, ${C.ms}15, ${C.gcp}15)`,
            border: `1px solid ${C.border}`, borderRadius: 6,
          }}>
            <span style={{ color: C.ms, fontWeight: 700, fontSize: 13 }}>M365</span>
            <span style={{ color: C.textLight, fontSize: 12 }}>→</span>
            <span style={{ color: C.gcp, fontWeight: 700, fontSize: 13 }}>GCP</span>
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.text, letterSpacing: "-0.01em" }}>
              Migration Platform
            </div>
            <div style={{ fontSize: 10, color: C.textMuted, letterSpacing: "0.06em", textTransform: "uppercase" }}>
              Itzhar Olivera Solutions & Strategy
            </div>
          </div>
        </div>

        <nav style={{ display: "flex", gap: 2 }}>
          {NAV.map(n => (
            <button key={n.id} onClick={() => setActiveView(n.id)}
              style={{
                padding: "6px 16px", border: "none", cursor: "pointer",
                borderRadius: 6, fontSize: 13, fontWeight: 500,
                background: activeView === n.id ? `${C.gcp}12` : "transparent",
                color: activeView === n.id ? C.gcp : C.textMuted,
                borderBottom: activeView === n.id ? `2px solid ${C.gcp}` : "2px solid transparent",
                transition: "all 0.15s",
              }}>
              {n.icon} {n.label}
            </button>
          ))}
        </nav>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            padding: "4px 12px", borderRadius: 20,
            background: overallProgress >= 75 ? C.successLight : overallProgress >= 40 ? C.warningLight : C.infoLight,
            color: overallProgress >= 75 ? C.success : overallProgress >= 40 ? C.warning : C.info,
            fontSize: 12, fontWeight: 700,
          }}>
            {overallProgress}% Complete
          </div>
          <div style={{ fontSize: 11, color: C.textLight, textAlign: "right" }}>
            <div style={{ fontWeight: 600, color: C.textMuted }}>Tom Yair Tommy Itzhar Olivera</div>
            <div>Itzhar Olivera S&S</div>
          </div>
        </div>
      </header>

      {/* Notification */}
      {notification && (
        <div style={{
          position: "fixed", top: 64, right: 24, zIndex: 999,
          background: notification.type === "success" ? C.successLight :
            notification.type === "error" ? C.dangerLight : C.infoLight,
          color: notification.type === "success" ? C.success :
            notification.type === "error" ? C.danger : C.info,
          border: `1px solid currentColor`,
          borderRadius: 8, padding: "12px 20px",
          fontSize: 13, fontWeight: 500,
          boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
          animation: "fadeIn 0.2s ease",
        }}>
          {notification.msg}
        </div>
      )}

      <main style={{ flex: 1, padding: "24px 32px", maxWidth: 1400, width: "100%", margin: "0 auto" }}>

        {/* ── DASHBOARD VIEW ── */}
        {activeView === "dashboard" && (
          <div>
            <div style={{ marginBottom: 24 }}>
              <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: C.text }}>Migration Dashboard</h1>
              <p style={{ margin: "4px 0 0", color: C.textMuted, fontSize: 13 }}>
                Microsoft 365 → Google Workspace · End-to-end orchestration
              </p>
            </div>

            {/* KPI row */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 16, marginBottom: 24 }}>
              {[
                { label: "Total Tasks", value: totalTasks, color: C.slate, bg: C.slateLight },
                { label: "Completed", value: completed, color: C.success, bg: C.successLight },
                { label: "In Progress", value: inProgress, color: C.info, bg: C.infoLight },
                { label: "Failed", value: failed, color: C.danger, bg: C.dangerLight },
                { label: "Devices", value: devices.length, color: C.gcp, bg: C.gcpLight },
              ].map(k => (
                <Card key={k.label} style={{ textAlign: "center", padding: "16px 20px" }}>
                  <div style={{ fontSize: 30, fontWeight: 800, color: k.color, lineHeight: 1 }}>{k.value}</div>
                  <div style={{ fontSize: 11, color: C.textMuted, marginTop: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>{k.label}</div>
                </Card>
              ))}
            </div>

            {/* Overall progress */}
            <Card style={{ marginBottom: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>Overall Migration Progress</span>
                <span style={{ fontSize: 20, fontWeight: 800, color: C.gcp }}>{overallProgress}%</span>
              </div>
              <div style={{ width: "100%", height: 12, background: C.slateLight, borderRadius: 6, overflow: "hidden" }}>
                <div style={{
                  width: `${overallProgress}%`, height: "100%", borderRadius: 6,
                  background: `linear-gradient(90deg, ${C.ms}, ${C.gcp})`,
                  transition: "width 0.6s ease",
                }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: C.textLight }}>
                <span>Pre-Migration</span>
                <span>Post-Migration</span>
              </div>
            </Card>

            {/* Phase progress + device charts */}
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, marginBottom: 24 }}>
              <Card>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 16 }}>Progress by Phase</div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={phaseProgress} barSize={24}>
                    <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: C.textMuted }} tickLine={false} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: C.textMuted }} tickLine={false} axisLine={false} />
                    <Tooltip
                      formatter={(v) => [`${v}%`, "Progress"]}
                      contentStyle={{ fontSize: 12, border: `1px solid ${C.border}`, borderRadius: 6 }}
                    />
                    <Bar dataKey="progress" radius={[4, 4, 0, 0]}>
                      {phaseProgress.map((p, i) => (
                        <Cell key={i} fill={p.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </Card>

              <Card>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Device Status</div>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={devicesByStatus} dataKey="value" cx="50%" cy="50%"
                      innerRadius={50} outerRadius={80} paddingAngle={3}>
                      {devicesByStatus.map((d, i) => (
                        <Cell key={i} fill={d.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ fontSize: 12, border: `1px solid ${C.border}`, borderRadius: 6 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                  {devicesByStatus.map(d => (
                    <div key={d.name} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: C.textMuted }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: d.color, display: "inline-block" }} />
                      {d.name} ({d.value})
                    </div>
                  ))}
                </div>
              </Card>
            </div>

            {/* Phase cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
              {phaseProgress.map(p => (
                <Card key={p.id} style={{
                  borderLeft: `3px solid ${p.color}`,
                  cursor: "pointer",
                  transition: "box-shadow 0.15s",
                }}
                  onClick={() => { setActiveView("workplan"); setSelectedPhase(p.id); }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: p.color, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      {p.icon} {p.id.replace(/_/g, " ")}
                    </span>
                    <span style={{ fontSize: 14, fontWeight: 800, color: p.color }}>{p.progress}%</span>
                  </div>
                  <ProgressBar value={p.progress} color={p.color} />
                  <div style={{ marginTop: 8, fontSize: 11, color: C.textMuted }}>
                    {p.tasks.filter(t => t.status === "completed").length}/{p.tasks.length} tasks
                  </div>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* ── DEVICES VIEW ── */}
        {activeView === "devices" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
              <div>
                <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Device Management</h1>
                <p style={{ margin: "4px 0 0", color: C.textMuted, fontSize: 13 }}>
                  Discover, select, and migrate devices through Intune off-boarding to Google MDM
                </p>
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <button onClick={runDiscovery} disabled={discoveryRunning}
                  style={{
                    padding: "8px 18px", borderRadius: 6, cursor: "pointer",
                    border: `1px solid ${C.ms}`, fontSize: 13, fontWeight: 600,
                    background: discoveryRunning ? C.msLight : C.ms,
                    color: discoveryRunning ? C.msDark : "#fff",
                    display: "flex", alignItems: "center", gap: 6,
                  }}>
                  {discoveryRunning ? "⟳ Scanning..." : "🔍 Run Discovery"}
                </button>
                <button onClick={offboardSelected}
                  style={{
                    padding: "8px 18px", borderRadius: 6, cursor: "pointer",
                    border: `1px solid #1d4ed8`,
                    background: "#1d4ed8", color: "#fff",
                    fontSize: 13, fontWeight: 600,
                  }}>
                  ⬇ Offboard from Intune
                </button>
                <button onClick={enrollGoogle}
                  style={{
                    padding: "8px 18px", borderRadius: 6, cursor: "pointer",
                    border: `1px solid ${C.gcp}`,
                    background: C.gcp, color: "#fff",
                    fontSize: 13, fontWeight: 600,
                  }}>
                  ⬆ Enroll Google MDM
                </button>
              </div>
            </div>

            {/* Device stat cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
              {devicesByOs.map(o => (
                <Card key={o.name} style={{ padding: "12px 16px", borderTop: `3px solid ${o.color}` }}>
                  <div style={{ fontSize: 24, fontWeight: 800, color: o.color }}>{o.value}</div>
                  <div style={{ fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginTop: 2 }}>{o.name}</div>
                </Card>
              ))}
            </div>

            {/* Search + filter */}
            <Card style={{ marginBottom: 16, padding: "12px 16px" }}>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <input
                  value={deviceSearch}
                  onChange={e => setDeviceSearch(e.target.value)}
                  placeholder="Search devices..."
                  style={{
                    flex: 1, padding: "7px 12px", borderRadius: 6,
                    border: `1px solid ${C.border}`, fontSize: 13,
                    outline: "none", color: C.text, background: C.bg,
                  }}
                />
                <span style={{ fontSize: 12, color: C.textMuted }}>
                  {selectedDevices.length} selected of {filteredDevices.length}
                </span>
              </div>
            </Card>

            {/* Device table */}
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: C.slateLight, borderBottom: `1px solid ${C.border}` }}>
                    <th style={{ padding: "10px 16px", textAlign: "left", width: 40 }}>
                      <input type="checkbox"
                        checked={selectedDevices.length === filteredDevices.length && filteredDevices.length > 0}
                        onChange={selectAllDevices}
                        style={{ cursor: "pointer" }}
                      />
                    </th>
                    {["Device", "OS", "User", "Compliance", "Type", "Status", "Actions"].map(h => (
                      <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredDevices.map((d, i) => (
                    <tr key={d.id} style={{
                      borderBottom: `1px solid ${C.border}`,
                      background: selectedDevices.includes(d.id) ? `${C.gcp}08` : i % 2 === 0 ? C.surface : C.bg,
                    }}>
                      <td style={{ padding: "10px 16px" }}>
                        <input type="checkbox"
                          checked={selectedDevices.includes(d.id)}
                          onChange={() => toggleDevice(d.id)}
                          style={{ cursor: "pointer" }}
                        />
                      </td>
                      <td style={{ padding: "10px 12px", fontWeight: 600, color: C.text }}>{d.display_name}</td>
                      <td style={{ padding: "10px 12px" }}>
                        <OsIcon os={d.os_type} />
                        <span style={{ marginLeft: 6, color: C.textMuted }}>{d.os_type}</span>
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <div style={{ fontSize: 12, fontWeight: 500 }}>{d.assigned_user}</div>
                        <div style={{ fontSize: 11, color: C.textMuted }}>{d.assigned_user_email}</div>
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <span style={{
                          padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                          background: d.compliance_state === "compliant" ? C.successLight : C.dangerLight,
                          color: d.compliance_state === "compliant" ? C.success : C.danger,
                        }}>
                          {d.compliance_state}
                        </span>
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        {d.autopilot_enrolled && (
                          <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: C.msLight, color: C.msDark, marginRight: 4 }}>
                            AUTOPILOT
                          </span>
                        )}
                        {d.is_byod && (
                          <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: C.warningLight, color: C.warning }}>
                            BYOD
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "10px 12px" }}><StatusBadge status={d.status} /></td>
                      <td style={{ padding: "10px 12px" }}>
                        {d.status === "discovered" && (
                          <button onClick={() => {
                            setDevices(prev => prev.map(x => x.id === d.id ? { ...x, status: "intune_offboarding" } : x));
                            setTimeout(() => setDevices(prev => prev.map(x => x.id === d.id && x.status === "intune_offboarding" ? { ...x, status: "intune_offboarded" } : x)), 3000);
                            notify(`Offboarding ${d.display_name}...`, "info");
                          }}
                            style={{ padding: "4px 10px", borderRadius: 4, border: `1px solid ${C.ms}`, background: "transparent", color: C.ms, fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                            Offboard
                          </button>
                        )}
                        {d.status === "intune_offboarded" && (
                          <button onClick={() => {
                            setDevices(prev => prev.map(x => x.id === d.id ? { ...x, status: "google_enrolling" } : x));
                            setTimeout(() => setDevices(prev => prev.map(x => x.id === d.id && x.status === "google_enrolling" ? { ...x, status: "google_enrolled" } : x)), 3000);
                            notify(`Enrolling ${d.display_name} in Google MDM...`, "info");
                          }}
                            style={{ padding: "4px 10px", borderRadius: 4, border: `1px solid ${C.gcp}`, background: "transparent", color: C.gcp, fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                            Enroll GCP
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        )}

        {/* ── WORKPLAN VIEW ── */}
        {activeView === "workplan" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
              <div>
                <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Migration Workplan</h1>
                <p style={{ margin: "4px 0 0", color: C.textMuted, fontSize: 13 }}>
                  {totalTasks} tasks across 7 phases · {completed} completed
                </p>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <select value={selectedPhase} onChange={e => setSelectedPhase(e.target.value)}
                  style={{ padding: "7px 12px", borderRadius: 6, border: `1px solid ${C.border}`, fontSize: 13, background: C.surface, color: C.text, cursor: "pointer" }}>
                  <option value="all">All Phases</option>
                  {PHASES.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
                {selectedPhase !== "all" && (
                  <button onClick={() => runAllInPhase(selectedPhase)}
                    style={{ padding: "7px 16px", borderRadius: 6, border: `1px solid ${C.gcp}`, background: C.gcp, color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                    ▶ Run All in Phase
                  </button>
                )}
              </div>
            </div>

            {/* Group by phase */}
            {(selectedPhase === "all" ? PHASES : PHASES.filter(p => p.id === selectedPhase)).map(phase => {
              const phaseTasks = filteredTasks.filter(t => t.phase === phase.id);
              if (!phaseTasks.length) return null;
              const phaseCompleted = phaseTasks.filter(t => t.status === "completed").length;
              const phaseProgressVal = Math.round(phaseTasks.reduce((s, t) => s + t.progress, 0) / phaseTasks.length);

              return (
                <div key={phase.id} style={{ marginBottom: 24 }}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 12, marginBottom: 10,
                    padding: "10px 16px", borderRadius: 8,
                    background: `${phase.color}10`, borderLeft: `4px solid ${phase.color}`,
                  }}>
                    <span style={{ fontSize: 16 }}>{phase.icon}</span>
                    <span style={{ fontWeight: 700, color: phase.color, fontSize: 14 }}>{phase.label}</span>
                    <span style={{ fontSize: 12, color: C.textMuted }}>{phaseCompleted}/{phaseTasks.length} tasks</span>
                    <div style={{ flex: 1 }}>
                      <ProgressBar value={phaseProgressVal} color={phase.color} />
                    </div>
                    <span style={{ fontWeight: 800, color: phase.color, fontSize: 14 }}>{phaseProgressVal}%</span>
                    <button onClick={() => runAllInPhase(phase.id)}
                      style={{ padding: "4px 12px", borderRadius: 4, border: `1px solid ${phase.color}`, background: "transparent", color: phase.color, fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                      Run All
                    </button>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {phaseTasks.map(task => (
                      <Card key={task.id} style={{
                        padding: "14px 16px",
                        borderLeft: `3px solid ${task.status === "completed" ? C.success : task.status === "in_progress" ? C.info : task.status === "failed" ? C.danger : C.border}`,
                        cursor: "pointer",
                      }} onClick={() => setExpandedTask(expandedTask === task.id ? null : task.id)}>
                        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: C.textLight, minWidth: 32 }}>#{task.num}</span>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: task.status === "completed" ? C.textMuted : C.text }}>
                              {task.title}
                            </div>
                            {expandedTask === task.id && (
                              <div style={{ marginTop: 8, fontSize: 12, color: C.textMuted, display: "flex", gap: 20 }}>
                                <span><b>Owner:</b> {task.owner}</span>
                                <span><b>Scope:</b> {task.scope}</span>
                                {task.notes && <span><b>Notes:</b> {task.notes}</span>}
                              </div>
                            )}
                          </div>
                          <PriorityDot priority={task.priority} />
                          <span style={{ fontSize: 11, color: C.textMuted }}>{task.priority}</span>

                          {task.status === "in_progress" && (
                            <div style={{ width: 80 }}>
                              <ProgressBar value={task.progress} color={C.info} />
                              <div style={{ fontSize: 10, color: C.info, marginTop: 2, textAlign: "right" }}>{task.progress}%</div>
                            </div>
                          )}

                          <StatusBadge status={task.status} />

                          {task.status === "not_started" && (
                            <button onClick={e => { e.stopPropagation(); runTask(task.id); }}
                              style={{ padding: "4px 12px", borderRadius: 4, border: `1px solid ${phase.color}`, background: "transparent", color: phase.color, fontSize: 11, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap" }}>
                              ▶ Run
                            </button>
                          )}
                          {task.status === "failed" && (
                            <button onClick={e => { e.stopPropagation(); runTask(task.id); }}
                              style={{ padding: "4px 12px", borderRadius: 4, border: `1px solid ${C.warning}`, background: "transparent", color: C.warning, fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                              ↺ Retry
                            </button>
                          )}
                        </div>
                      </Card>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ── PHASES VIEW ── */}
        {activeView === "phases" && (
          <div>
            <div style={{ marginBottom: 24 }}>
              <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Migration Phases</h1>
              <p style={{ margin: "4px 0 0", color: C.textMuted, fontSize: 13 }}>
                Visual overview of all 7 phases with progress and quick-run capabilities
              </p>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {phaseProgress.map((phase, idx) => {
                const completed = phase.tasks.filter(t => t.status === "completed").length;
                const inProg = phase.tasks.filter(t => t.status === "in_progress").length;
                return (
                  <Card key={phase.id} style={{
                    borderLeft: `4px solid ${phase.color}`,
                    background: phase.progress === 100 ? `${phase.color}06` : C.surface,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
                      <div style={{
                        width: 40, height: 40, borderRadius: 8,
                        background: `${phase.color}20`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 18,
                      }}>
                        {phase.icon}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 15, fontWeight: 700, color: C.text }}>{phase.label}</div>
                        <div style={{ fontSize: 12, color: C.textMuted, marginTop: 2 }}>
                          {completed} completed · {inProg} in progress · {phase.tasks.length - completed - inProg} remaining
                        </div>
                      </div>
                      <div style={{ fontSize: 28, fontWeight: 900, color: phase.color }}>{phase.progress}%</div>
                      <button onClick={() => runAllInPhase(phase.id)}
                        style={{ padding: "8px 20px", borderRadius: 6, border: `1px solid ${phase.color}`, background: "transparent", color: phase.color, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                        ▶ Execute Phase
                      </button>
                    </div>
                    <ProgressBar value={phase.progress} color={phase.color} />

                    <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                      {phase.tasks.slice(0, 6).map(t => (
                        <div key={t.id} style={{
                          padding: "3px 10px", borderRadius: 4, fontSize: 11,
                          background: t.status === "completed" ? C.successLight :
                            t.status === "in_progress" ? C.infoLight :
                              t.status === "failed" ? C.dangerLight : C.slateLight,
                          color: t.status === "completed" ? C.success :
                            t.status === "in_progress" ? C.info :
                              t.status === "failed" ? C.danger : C.slate,
                          fontWeight: 500,
                          border: "1px solid transparent",
                        }}>
                          {t.num}: {t.title.slice(0, 35)}{t.title.length > 35 ? "…" : ""}
                        </div>
                      ))}
                      {phase.tasks.length > 6 && (
                        <div style={{ padding: "3px 10px", fontSize: 11, color: C.textMuted }}>
                          +{phase.tasks.length - 6} more
                        </div>
                      )}
                    </div>
                  </Card>
                );
              })}
            </div>
          </div>
        )}

        {/* ── TENANTS CONNECTION VIEW ── */}
        {activeView === "tenants" && (() => {
          const inp = (val, onChange, placeholder, type = "text", mono = false) => (
            <input
              type={type} value={val} onChange={e => onChange(e.target.value)}
              placeholder={placeholder}
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "8px 12px", border: `1px solid ${C.border}`,
                borderRadius: 6, fontSize: 13, color: C.text,
                background: C.surface, outline: "none",
                fontFamily: mono ? "'IBM Plex Mono', monospace" : "inherit",
              }}
            />
          );

          const fieldRow = (label, hint, children) => (
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{label}</label>
                {hint && <span style={{ fontSize: 11, color: C.textLight }}>{hint}</span>}
              </div>
              {children}
            </div>
          );

          const statusBadge = (status, error) => {
            if (!status) return null;
            const cfg = {
              testing: { bg: C.infoLight, color: C.info, label: "Testing…" },
              ok:      { bg: C.successLight, color: C.success, label: "Connected ✓" },
              error:   { bg: C.dangerLight, color: C.danger, label: "Failed ✗" },
            }[status];
            return (
              <div>
                <span style={{ padding: "3px 10px", borderRadius: 12, fontSize: 12, fontWeight: 600, background: cfg.bg, color: cfg.color }}>
                  {cfg.label}
                </span>
                {error && <div style={{ fontSize: 11, color: C.danger, marginTop: 6 }}>{error}</div>}
              </div>
            );
          };

          const sectionHeader = (color, colorLight, icon, title, subtitle, status, error) => (
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.border}`, background: `${color}08` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: colorLight, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>
                    {icon}
                  </div>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color }}>{title}</div>
                    <div style={{ fontSize: 11, color: C.textMuted }}>{subtitle}</div>
                  </div>
                </div>
                {statusBadge(status, error)}
              </div>
            </div>
          );

          const btn = (label, onClick, loading, colorBg, colorText, outline = false) => (
            <button onClick={onClick} disabled={loading}
              style={{
                padding: "8px 18px", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: loading ? "wait" : "pointer",
                border: outline ? `1.5px solid ${colorBg}` : "none",
                background: outline ? "transparent" : colorBg,
                color: outline ? colorBg : colorText,
                opacity: loading ? 0.6 : 1, transition: "opacity 0.15s",
              }}>
              {loading ? "…" : label}
            </button>
          );

          return (
            <div>
              {/* Page header */}
              <div style={{ marginBottom: 24, display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
                <div>
                  <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: C.text }}>Tenants Connection</h1>
                  <p style={{ margin: "4px 0 0", color: C.textMuted, fontSize: 13 }}>
                    Configure Microsoft 365 and Google Cloud Platform credentials. Secrets are stored locally and never committed to version control.
                  </p>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, color: C.textMuted }}>Active environment</label>
                  <select
                    value={tcConfig.active_environment}
                    onChange={e => setTcConfig(p => ({ ...p, active_environment: e.target.value }))}
                    style={{ padding: "6px 12px", borderRadius: 6, border: `1px solid ${C.border}`, fontSize: 13, background: C.surface, color: C.text, cursor: "pointer" }}
                  >
                    <option value="dev">Development</option>
                    <option value="test">Testing</option>
                    <option value="prod">Production</option>
                  </select>
                </div>
              </div>

              {tcLoading && (
                <div style={{ textAlign: "center", padding: 40, color: C.textMuted, fontSize: 13 }}>Loading saved configuration…</div>
              )}

              {/* Two-column: Azure + GCP */}
              {!tcLoading && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>

                  {/* ── Microsoft 365 / Azure ── */}
                  <Card style={{ padding: 0, overflow: "hidden" }}>
                    {sectionHeader(C.ms, C.msLight, "☁", "Microsoft 365 / Azure", "Entra ID · Microsoft Graph API", tcAzureStatus, tcAzureError)}
                    <div style={{ padding: 20 }}>
                      {fieldRow("Tenant ID", "Entra admin center → Overview → Tenant ID",
                        inp(tcConfig.azure_tenant_id, v => setTcConfig(p => ({ ...p, azure_tenant_id: v })), "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", "text", true)
                      )}
                      {fieldRow("Tenant Domain", "e.g. yourcompany.onmicrosoft.com",
                        inp(tcConfig.azure_tenant_domain, v => setTcConfig(p => ({ ...p, azure_tenant_domain: v })), "yourcompany.onmicrosoft.com")
                      )}
                      {fieldRow("App Client ID", "App Registrations → your app → Application (client) ID",
                        inp(tcConfig.azure_client_id, v => setTcConfig(p => ({ ...p, azure_client_id: v })), "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", "text", true)
                      )}
                      {fieldRow("Client Secret", "App Registrations → Certificates & secrets",
                        <div style={{ position: "relative" }}>
                          <input
                            type={tcShowSecret ? "text" : "password"}
                            value={tcConfig.azure_client_secret}
                            onChange={e => setTcConfig(p => ({ ...p, azure_client_secret: e.target.value }))}
                            placeholder="Paste client secret value"
                            style={{ width: "100%", boxSizing: "border-box", padding: "8px 40px 8px 12px", border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, color: C.text, background: C.surface, outline: "none", fontFamily: "'IBM Plex Mono', monospace" }}
                          />
                          <button onClick={() => setTcShowSecret(v => !v)}
                            style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: 14, color: C.textMuted }}>
                            {tcShowSecret ? "🙈" : "👁"}
                          </button>
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                        {btn("Test Connection", testAzure, tcAzureStatus === "testing", C.ms, "#fff")}
                        {btn("Auto-Register App →", () => setTcRegisterOpen(v => !v), false, C.ms, "#fff", true)}
                      </div>
                    </div>
                  </Card>

                  {/* ── Google Cloud Platform ── */}
                  <Card style={{ padding: 0, overflow: "hidden" }}>
                    {sectionHeader(C.gcp, C.gcpLight, "☁", "Google Cloud Platform", "Cloud Storage · Firestore · Pub/Sub", tcGcpStatus, tcGcpError)}
                    <div style={{ padding: 20 }}>
                      {fieldRow("Project ID", "console.cloud.google.com → project selector",
                        inp(tcConfig.gcp_project_id, v => setTcConfig(p => ({ ...p, gcp_project_id: v })), "my-migration-project", "text", true)
                      )}
                      {fieldRow("GCS Bucket", "Cloud Storage bucket for migrated data",
                        inp(tcConfig.gcp_gcs_bucket, v => setTcConfig(p => ({ ...p, gcp_gcs_bucket: v })), "my-migration-bucket")
                      )}
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                        {fieldRow("Region",  null,
                          <select value={tcConfig.gcp_region} onChange={e => setTcConfig(p => ({ ...p, gcp_region: e.target.value }))}
                            style={{ width: "100%", padding: "8px 12px", border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, background: C.surface, color: C.text }}>
                            {["us-central1","us-east1","us-west1","europe-west1","europe-west2","europe-west4","asia-east1","asia-southeast1","australia-southeast1"].map(r => (
                              <option key={r} value={r}>{r}</option>
                            ))}
                          </select>
                        )}
                        {fieldRow("Firestore Database", null,
                          inp(tcConfig.gcp_firestore_database, v => setTcConfig(p => ({ ...p, gcp_firestore_database: v })), "(default)")
                        )}
                      </div>
                      {fieldRow("Service Account JSON",
                        <span>IAM → Service Accounts → Keys → <span style={{ color: C.gcp, fontWeight: 600 }}>Add Key (JSON)</span></span>,
                        <div style={{ position: "relative" }}>
                          <textarea
                            value={tcShowSaJson ? tcConfig.gcp_service_account_json : (tcConfig.gcp_service_account_json ? "••••••••  (click 👁 to reveal)" : "")}
                            onChange={e => setTcConfig(p => ({ ...p, gcp_service_account_json: e.target.value }))}
                            onFocus={() => setTcShowSaJson(true)}
                            placeholder='Paste full contents of your service account .json key file'
                            rows={tcShowSaJson ? 5 : 2}
                            style={{ width: "100%", boxSizing: "border-box", padding: "8px 12px", border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 12, color: C.text, background: C.surface, outline: "none", fontFamily: "'IBM Plex Mono', monospace", resize: "vertical" }}
                          />
                          <button onClick={() => setTcShowSaJson(v => !v)}
                            style={{ position: "absolute", right: 8, top: 8, background: "none", border: "none", cursor: "pointer", fontSize: 14, color: C.textMuted }}>
                            {tcShowSaJson ? "🙈" : "👁"}
                          </button>
                        </div>
                      )}
                      <div style={{ marginTop: 8 }}>
                        {btn("Test Connection", testGcp, tcGcpStatus === "testing", C.gcp, "#fff")}
                      </div>
                    </div>
                  </Card>
                </div>
              )}

              {/* ── Auto App Registration panel ── */}
              {tcRegisterOpen && (
                <Card style={{ marginBottom: 24, padding: 0, overflow: "hidden", border: `1px solid ${C.msMid}` }}>
                  <div style={{ padding: "14px 20px", background: C.msLight, borderBottom: `1px solid ${C.msMid}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: C.msDark }}>Auto App Registration</div>
                      <div style={{ fontSize: 12, color: C.slate, marginTop: 2 }}>
                        Creates an Entra ID App Registration with all 15 required Graph permissions and grants admin consent automatically.
                      </div>
                    </div>
                    <button onClick={() => setTcRegisterOpen(false)} style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: C.textMuted }}>✕</button>
                  </div>
                  <div style={{ padding: 20 }}>
                    <div style={{ background: C.warningLight, border: `1px solid ${C.warning}`, borderRadius: 6, padding: "10px 14px", marginBottom: 16, fontSize: 12, color: C.warning }}>
                      <strong>Requires a Global Admin delegated token.</strong> To get one: open a terminal and run<br />
                      <code style={{ fontFamily: "monospace", background: "#0001", padding: "2px 6px", borderRadius: 4 }}>
                        az login --scope https://graph.microsoft.com/Application.ReadWrite.All
                      </code>
                      <br />then copy the access token from the output (or use the Azure portal → Cloud Shell).
                    </div>
                    {fieldRow("Global Admin Access Token", "Delegated token — not your client secret",
                      <div style={{ position: "relative" }}>
                        <textarea
                          value={tcAdminToken}
                          onChange={e => setTcAdminToken(e.target.value)}
                          placeholder="eyJ0eXAiOiJKV1QiLCJhbGciO…"
                          rows={3}
                          style={{ width: "100%", boxSizing: "border-box", padding: "8px 12px", border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 12, color: C.text, background: C.surface, outline: "none", fontFamily: "'IBM Plex Mono', monospace", resize: "none" }}
                        />
                      </div>
                    )}
                    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                      {btn("Create App Registration", registerAzureApp, tcRegisterLoading, C.ms, "#fff")}
                      {tcRegisterLoading && <span style={{ fontSize: 12, color: C.textMuted }}>Creating app, assigning permissions, granting consent…</span>}
                    </div>

                    {tcRegisterResult && (
                      <div style={{ marginTop: 16, background: C.successLight, border: `1px solid ${C.success}`, borderRadius: 8, padding: 16 }}>
                        <div style={{ fontWeight: 700, color: C.success, marginBottom: 10 }}>App registration created successfully!</div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 12, fontFamily: "monospace" }}>
                          {[
                            ["Client ID", tcRegisterResult.client_id],
                            ["Tenant ID", tcRegisterResult.tenant_id],
                            ["Object ID", tcRegisterResult.object_id],
                            ["SP ID", tcRegisterResult.service_principal_id],
                            ["Permissions granted", `${tcRegisterResult.permissions_granted_count} / 15`],
                            ["Secret expires", tcRegisterResult.client_secret_expires?.slice(0, 10)],
                          ].map(([k, v]) => v && (
                            <div key={k}>
                              <div style={{ color: C.textMuted, fontSize: 11 }}>{k}</div>
                              <div style={{ color: C.text, wordBreak: "break-all" }}>{v}</div>
                            </div>
                          ))}
                        </div>
                        {tcRegisterResult.client_secret && (
                          <div style={{ marginTop: 12, padding: "10px 14px", background: C.dangerLight, borderRadius: 6, border: `1px solid ${C.danger}` }}>
                            <div style={{ fontWeight: 700, color: C.danger, fontSize: 12, marginBottom: 4 }}>Client Secret — copy this now, it will not be shown again</div>
                            <code style={{ fontSize: 12, wordBreak: "break-all", color: C.text }}>{tcRegisterResult.client_secret}</code>
                          </div>
                        )}
                        {tcRegisterResult.permissions_failed?.length > 0 && (
                          <div style={{ marginTop: 10, fontSize: 12, color: C.warning }}>
                            <strong>Permissions not auto-granted</strong> (grant manually in Entra ID → API permissions):<br />
                            {tcRegisterResult.permissions_failed.join(", ")}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </Card>
              )}

              {/* Save bar */}
              <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 16, padding: "16px 0", borderTop: `1px solid ${C.border}` }}>
                <span style={{ fontSize: 12, color: C.textLight }}>
                  Secrets are stored locally and never committed to version control.
                </span>
                {btn(tcSaving ? "Saving…" : "Save Configuration", saveTenantConfig, tcSaving, C.gcp, "#fff")}
              </div>
            </div>
          );
        })()}

      </main>

      {/* Footer */}
      <footer style={{
        borderTop: `1px solid ${C.border}`,
        padding: "12px 32px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        background: C.surface, fontSize: 11, color: C.textLight,
      }}>
        <div>
          <span style={{ fontWeight: 700, color: C.textMuted }}>© Itzhar Olivera Solutions & Strategy</span>
          {" · "}Tom Yair Tommy Itzhar Olivera
        </div>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <span style={{ color: C.ms }}>● M365 Blue</span>
          <span style={{ color: C.gcp }}>● GCP Purple</span>
          <span style={{ padding: "2px 8px", background: C.successLight, color: C.success, borderRadius: 4, fontWeight: 600 }}>
            Platform v1.0 · Dev Branch
          </span>
        </div>
      </footer>
    </div>
  );
}
