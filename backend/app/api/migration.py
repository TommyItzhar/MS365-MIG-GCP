"""Migration workplan API.

Seeds the 54-task workplan from the customer's Excel doc, lets operators
view, filter, and update individual tasks.
"""
from flask import Blueprint, jsonify, request

from app import db
from app.models.models import MigrationPhase, MigrationTask, TaskStatus

bp = Blueprint("migration", __name__)

WORKPLAN: list[dict] = [
    # ── Phase 1: Pre-Migration ─────────────────────────────────────────
    {"num": "1",   "phase": "pre_migration", "title": "Provision AvePoint Fly license and configure access", "owner": "IT Admin", "scope": "Migration team", "priority": "High", "notes": "SaaS or on-premises deployment"},
    {"num": "1.1", "phase": "pre_migration", "title": "Create dedicated M365 migration service account with full mailbox access", "owner": "IT Admin", "scope": "M365 tenant", "priority": "High", "notes": "Use API Permissions; ApplicationImpersonation deprecated."},
    {"num": "1.2", "phase": "pre_migration", "title": "Create GCP project and enable required APIs (Admin SDK, Gmail, Drive, Calendar, Contacts)", "owner": "Cloud Admin", "scope": "GCP Console", "priority": "High", "notes": "Sign in as Google Super Admin"},
    {"num": "1.3", "phase": "pre_migration", "title": "Run pre-migration discovery scan", "owner": "Migration Lead", "scope": "All mailboxes & drives", "priority": "Medium", "notes": "Export to CSV"},
    {"num": "1.4", "phase": "pre_migration", "title": "Identify oversized files, forbidden characters, deep folder structures", "owner": "Migration Lead", "scope": "OneDrive / SharePoint", "priority": "Medium", "notes": "Address pre-migration"},
    {"num": "1.5", "phase": "pre_migration", "title": "Document shared mailboxes, resource mailboxes, distribution groups", "owner": "IT Admin", "scope": "Exchange Online", "priority": "Medium", "notes": ""},
    {"num": "1.6", "phase": "pre_migration", "title": "Define migration scope (Teams, SharePoint, OneDrive, Exchange, Groups)", "owner": "Migration Lead", "scope": "Full M365", "priority": "Medium", "notes": ""},
    {"num": "1.7", "phase": "pre_migration", "title": "Define user batches (50–100 users per wave) and schedule", "owner": "Project Manager", "scope": "All users", "priority": "Medium", "notes": ""},
    {"num": "1.8", "phase": "pre_migration", "title": "Define rollback plan and escalation path", "owner": "Project Manager", "scope": "Project governance", "priority": "Medium", "notes": ""},
    {"num": "1.9", "phase": "pre_migration", "title": "Communicate migration timeline to end users", "owner": "Change Manager", "scope": "All staff", "priority": "Low", "notes": ""},
    # ── Phase 2: Environment Preparation ───────────────────────────────
    {"num": "2",   "phase": "env_preparation", "title": "Configure MX routing subdomain for parallel mail flow", "owner": "IT Admin", "scope": "DNS", "priority": "High", "notes": "Prevents mail loss"},
    {"num": "2.1", "phase": "env_preparation", "title": "Enable Gmail/Drive/Calendar/Contacts for all Workspace users", "owner": "Cloud Admin", "scope": "Google Admin Console", "priority": "High", "notes": ""},
    {"num": "2.2", "phase": "env_preparation", "title": "Register Azure AD app with Microsoft Graph API permissions", "owner": "IT Admin", "scope": "Azure AD / M365", "priority": "High", "notes": "EWS blocked Oct 1 2026"},
    {"num": "2.3", "phase": "env_preparation", "title": "Set up Google Groups to mirror M365 Groups", "owner": "IT Admin", "scope": "Google Workspace", "priority": "Medium", "notes": ""},
    {"num": "2.4", "phase": "env_preparation", "title": "Connect AvePoint Fly to M365 source and Workspace destination", "owner": "Migration Lead", "scope": "AvePoint Fly", "priority": "Low", "notes": ""},
    {"num": "2.5", "phase": "env_preparation", "title": "Run Fly initial connectivity scan", "owner": "Migration Lead", "scope": "AvePoint Fly", "priority": "Medium", "notes": ""},
    # ── Phase 3: Intune Off-boarding ───────────────────────────────────
    {"num": "3",   "phase": "intune_offboarding", "title": "Identify Autopilot devices and document hardware hashes", "owner": "IT Admin", "scope": "Intune / Autopilot", "priority": "High", "notes": ""},
    {"num": "3.1", "phase": "intune_offboarding", "title": "Remove Autopilot device registrations", "owner": "IT Admin", "scope": "Intune / Autopilot", "priority": "High", "notes": ""},
    {"num": "3.2", "phase": "intune_offboarding", "title": "Retire/wipe corporate devices (selective for BYOD)", "owner": "IT Admin", "scope": "Intune / MEM", "priority": "High", "notes": ""},
    {"num": "3.3", "phase": "intune_offboarding", "title": "Remove Intune compliance, configuration, and app-protection policies", "owner": "IT Admin", "scope": "Intune / MEM", "priority": "Medium", "notes": ""},
    {"num": "3.4", "phase": "intune_offboarding", "title": "Unenroll devices from Azure AD / Entra ID", "owner": "IT Admin", "scope": "Azure AD", "priority": "High", "notes": ""},
    {"num": "3.5", "phase": "intune_offboarding", "title": "Uninstall Company Portal and Authenticator", "owner": "IT Admin", "scope": "All endpoints", "priority": "Medium", "notes": ""},
    {"num": "3.6", "phase": "intune_offboarding", "title": "Decommission Intune connector / on-prem infrastructure", "owner": "IT Admin", "scope": "On-prem / Intune", "priority": "Low", "notes": ""},
    # ── Phase 4: Google MDM On-boarding ────────────────────────────────
    {"num": "4",   "phase": "google_mdm_onboarding", "title": "Configure Google Endpoint Management policies", "owner": "Cloud Admin", "scope": "Google Admin Console", "priority": "High", "notes": ""},
    {"num": "4.1", "phase": "google_mdm_onboarding", "title": "Enroll Windows devices via GCPW", "owner": "IT Admin", "scope": "Windows endpoints", "priority": "High", "notes": "GCPW MSI install required on each device"},
    {"num": "4.2", "phase": "google_mdm_onboarding", "title": "Enroll macOS devices via MDM enrollment profile", "owner": "IT Admin", "scope": "macOS endpoints", "priority": "High", "notes": ""},
    {"num": "4.3", "phase": "google_mdm_onboarding", "title": "Enroll iOS/Android devices", "owner": "IT Admin", "scope": "Mobile devices", "priority": "Medium", "notes": "Android Enterprise / iOS supervised"},
    {"num": "4.4", "phase": "google_mdm_onboarding", "title": "Deploy Chrome browser / ChromeOS policies", "owner": "Cloud Admin", "scope": "All endpoints", "priority": "Medium", "notes": ""},
    {"num": "4.5", "phase": "google_mdm_onboarding", "title": "Push Workspace apps (Drive, Gmail, Calendar, Meet)", "owner": "Cloud Admin", "scope": "All endpoints", "priority": "Medium", "notes": ""},
    {"num": "4.6", "phase": "google_mdm_onboarding", "title": "Configure Context-Aware Access", "owner": "Security Admin", "scope": "Google Admin Console", "priority": "Medium", "notes": "Replaces Conditional Access"},
    {"num": "4.7", "phase": "google_mdm_onboarding", "title": "Validate device compliance and MDM reporting", "owner": "IT Admin", "scope": "Google Admin Console", "priority": "Low", "notes": ""},
    # ── Phase 5: Migration Execution ───────────────────────────────────
    {"num": "5",   "phase": "migration_execution", "title": "Configure migration filter policies", "owner": "Migration Lead", "scope": "AvePoint Fly", "priority": "Medium", "notes": ""},
    {"num": "5.1", "phase": "migration_execution", "title": "Pilot migration (5–10 users)", "owner": "Migration Lead", "scope": "Pilot user group", "priority": "High", "notes": "Fix issues before full"},
    {"num": "5.2", "phase": "migration_execution", "title": "Migrate Exchange Online → Gmail (mail/cal/contacts)", "owner": "Migration Lead", "scope": "All mailboxes", "priority": "High", "notes": ""},
    {"num": "5.3", "phase": "migration_execution", "title": "Migrate OneDrive → Google Drive", "owner": "Migration Lead", "scope": "All OneDrives", "priority": "High", "notes": ""},
    {"num": "5.4", "phase": "migration_execution", "title": "Migrate SharePoint → Google Shared Drives", "owner": "Migration Lead", "scope": "SharePoint sites", "priority": "Medium", "notes": "Permission models differ; manual review"},
    {"num": "5.5", "phase": "migration_execution", "title": "Migrate shared and resource mailboxes", "owner": "Migration Lead", "scope": "Exchange Online", "priority": "Medium", "notes": ""},
    {"num": "5.6", "phase": "migration_execution", "title": "Migrate Teams Chat → Workspace Chat", "owner": "Migration Lead", "scope": "Teams / Chat", "priority": "Low", "notes": ""},
    {"num": "5.7", "phase": "migration_execution", "title": "Run delta passes (data modified after initial pass)", "owner": "Migration Lead", "scope": "All workloads", "priority": "Medium", "notes": "Run close to cutover"},
    {"num": "5.8", "phase": "migration_execution", "title": "Monitor AvePoint Fly dashboard — review job errors", "owner": "Migration Lead", "scope": "AvePoint Fly", "priority": "Medium", "notes": ""},
    # ── Phase 6: Cutover ───────────────────────────────────────────────
    {"num": "6",   "phase": "cutover", "title": "Update DNS — SPF, DKIM, DMARC for Google", "owner": "IT Admin", "scope": "DNS", "priority": "High", "notes": ""},
    {"num": "6.1", "phase": "cutover", "title": "Confirm end-to-end mail flow in Workspace", "owner": "IT Admin", "scope": "Gmail", "priority": "High", "notes": ""},
    {"num": "6.2", "phase": "cutover", "title": "Manually verify permissions on sensitive Shared Drives", "owner": "Security Admin", "scope": "Shared Drives", "priority": "Medium", "notes": "Manual review"},
    {"num": "6.3", "phase": "cutover", "title": "Update embedded SharePoint/OneDrive links → Drive URLs", "owner": "Migration Lead", "scope": "All migrated content", "priority": "Medium", "notes": ""},
    {"num": "6.4", "phase": "cutover", "title": "Reconfigure Outlook → Gmail or deploy desktop clients", "owner": "IT Admin", "scope": "All endpoints", "priority": "Medium", "notes": ""},
    {"num": "6.5", "phase": "cutover", "title": "Notify users of new Workspace login & support channels", "owner": "Change Manager", "scope": "All staff", "priority": "High", "notes": ""},
    # ── Phase 7: Post-Migration ────────────────────────────────────────
    {"num": "7",   "phase": "post_migration", "title": "Validate migrated data volumes and review reports", "owner": "Migration Lead", "scope": "AvePoint Fly", "priority": "Medium", "notes": ""},
    {"num": "7.1", "phase": "post_migration", "title": "Revoke M365 service account perms; remove app registration", "owner": "IT Admin", "scope": "Azure AD", "priority": "High", "notes": "Security cleanup"},
    {"num": "7.2", "phase": "post_migration", "title": "Decommission M365 licenses (with retention period)", "owner": "IT Admin", "scope": "M365 tenant", "priority": "Medium", "notes": ""},
    {"num": "7.3", "phase": "post_migration", "title": "Archive/remove GCP migration project credentials", "owner": "Cloud Admin", "scope": "GCP Console", "priority": "Medium", "notes": ""},
    {"num": "7.4", "phase": "post_migration", "title": "Monitor Workspace audit logs for 30 days", "owner": "Security Admin", "scope": "Google Admin Console", "priority": "Medium", "notes": ""},
    {"num": "7.5", "phase": "post_migration", "title": "Confirm all devices enrolled and compliant in Google MDM", "owner": "IT Admin", "scope": "Google Endpoint Mgmt", "priority": "Medium", "notes": ""},
    {"num": "7.6", "phase": "post_migration", "title": "End-user training on Workspace", "owner": "Change Manager", "scope": "All staff", "priority": "Medium", "notes": ""},
    {"num": "7.7", "phase": "post_migration", "title": "Document lessons learned; close project", "owner": "Project Manager", "scope": "Project team", "priority": "Low", "notes": ""},
]


@bp.post("/seed")
def seed_workplan():
    created = 0
    for item in WORKPLAN:
        existing = MigrationTask.query.filter_by(task_number=item["num"]).first()
        if existing:
            continue
        db.session.add(MigrationTask(
            task_number=item["num"],
            phase=MigrationPhase(item["phase"]),
            title=item["title"],
            owner=item["owner"],
            scope=item["scope"],
            priority=item["priority"],
            notes=item["notes"],
        ))
        created += 1
    db.session.commit()
    return jsonify({"seeded": created, "total": len(WORKPLAN)}), 201


@bp.get("/tasks")
def list_tasks():
    phase = request.args.get("phase")
    q = MigrationTask.query
    if phase:
        try:
            q = q.filter(MigrationTask.phase == MigrationPhase(phase))
        except ValueError:
            return jsonify({"error": f"invalid phase: {phase}"}), 400
    return jsonify([t.to_dict() for t in q.order_by(MigrationTask.task_number).all()])


@bp.patch("/tasks/<task_id>")
def update_task(task_id: str):
    task = MigrationTask.query.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    data = request.get_json(silent=True) or {}
    if "status" in data:
        try:
            task.status = TaskStatus(data["status"])
        except ValueError:
            return jsonify({"error": f"invalid status: {data['status']}"}), 400
    if "progress" in data:
        try:
            task.progress = max(0, min(100, int(data["progress"])))
        except (TypeError, ValueError):
            return jsonify({"error": "progress must be int"}), 400
    if "notes" in data:
        task.notes = data["notes"]
    db.session.commit()
    return jsonify(task.to_dict())


@bp.get("/progress")
def overall_progress():
    all_tasks = MigrationTask.query.all()
    total = len(all_tasks)
    if not total:
        return jsonify({"overall": 0, "by_phase": {}, "total_tasks": 0,
                        "completed": 0, "in_progress": 0, "failed": 0})
    overall = sum(t.progress for t in all_tasks) / total
    by_phase: dict[str, int] = {}
    for phase in MigrationPhase:
        pt = [t for t in all_tasks if t.phase == phase]
        if pt:
            by_phase[phase.value] = round(sum(t.progress for t in pt) / len(pt))
    return jsonify({
        "overall": round(overall),
        "total_tasks": total,
        "completed": sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED),
        "in_progress": sum(1 for t in all_tasks if t.status == TaskStatus.IN_PROGRESS),
        "failed": sum(1 for t in all_tasks if t.status == TaskStatus.FAILED),
        "by_phase": by_phase,
    })
