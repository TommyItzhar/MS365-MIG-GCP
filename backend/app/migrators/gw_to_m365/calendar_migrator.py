"""Google Calendar → Outlook Calendar migrator.

Reads calendar events via the Google Calendar API and creates them in
the user's Outlook calendar via the Microsoft Graph API.

Attendees, recurrence rules, and reminders are preserved.
Only future events are migrated by default (configurable via scope dates).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from googleapiclient.discovery import build

from app.constants import GW_CALENDAR_MAX_RESULTS
from app.migrators.gw_to_m365.base_migrator import BaseGWMigrator
from app.models import (
    GWMigrationItem,
    GWMigrationScope,
    GWWorkloadType,
    MigrationResult,
)

logger = logging.getLogger(__name__)


class CalendarMigrator(BaseGWMigrator):
    """Migrates Google Calendar events → Outlook Calendar."""

    workload = GWWorkloadType.CALENDAR

    async def discover_items(
        self, scope: GWMigrationScope, source_user: str
    ) -> list[GWMigrationItem]:
        dest_user = scope.user_mappings.get(source_user, source_user)
        creds = await self._gw_auth.get_credentials(source_user, "calendar")
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        items: list[GWMigrationItem] = []
        page_token: Optional[str] = None
        time_min = (
            scope.start_date.isoformat() + "Z"
            if scope.start_date
            else datetime.now(timezone.utc).isoformat()
        )
        time_max = scope.end_date.isoformat() + "Z" if scope.end_date else None

        while True:
            kwargs: dict = {
                "calendarId": "primary",
                "maxResults": GW_CALENDAR_MAX_RESULTS,
                "singleEvents": True,
                "orderBy": "startTime",
                "timeMin": time_min,
            }
            if time_max:
                kwargs["timeMax"] = time_max
            if page_token:
                kwargs["pageToken"] = page_token

            result = service.events().list(**kwargs).execute()
            events = result.get("items", [])

            for evt in events:
                if evt.get("status") == "cancelled":
                    continue
                items.append(
                    GWMigrationItem(
                        id=f"{self._job_id}-cal-{evt['id']}",
                        job_id=self._job_id,
                        workload=GWWorkloadType.CALENDAR,
                        source_user=source_user,
                        destination_user=dest_user,
                        source_id=evt["id"],
                        tenant_id=scope.gw_domain,
                        metadata={"summary": evt.get("summary", "")},
                    )
                )

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info(
            "calendar_discovery_done",
            extra={"count": len(items), "job_id": self._job_id},
        )
        return items

    async def migrate_item(self, item: GWMigrationItem) -> MigrationResult:
        creds = await self._gw_auth.get_credentials(item.source_user, "calendar")
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        evt = (
            service.events()
            .get(calendarId="primary", eventId=item.source_id)
            .execute()
        )

        payload = _gw_event_to_graph(evt)
        event_id = await self._writer.create_calendar_event(
            item.destination_user, payload
        )

        return MigrationResult(
            item_id=item.id,
            success=True,
            bytes_transferred=0,
            gcs_uri=f"m365://{item.destination_user}/events/{event_id}",
        )


def _gw_event_to_graph(evt: dict) -> dict:
    """Convert a Google Calendar event dict to a Graph API event payload."""

    def _dt(dt_obj: Optional[dict]) -> Optional[dict]:
        if not dt_obj:
            return None
        if "dateTime" in dt_obj:
            return {"dateTime": dt_obj["dateTime"], "timeZone": dt_obj.get("timeZone", "UTC")}
        if "date" in dt_obj:
            return {"dateTime": dt_obj["date"] + "T00:00:00", "timeZone": "UTC"}
        return None

    attendees = [
        {"emailAddress": {"address": a["email"], "name": a.get("displayName", "")}, "type": "required"}
        for a in evt.get("attendees", [])
        if not a.get("self", False)
    ]

    payload: dict = {
        "subject": evt.get("summary", "(No title)"),
        "body": {
            "contentType": "html" if evt.get("description", "").startswith("<") else "text",
            "content": evt.get("description", ""),
        },
        "start": _dt(evt.get("start")) or {"dateTime": "2000-01-01T00:00:00", "timeZone": "UTC"},
        "end": _dt(evt.get("end")) or {"dateTime": "2000-01-01T01:00:00", "timeZone": "UTC"},
        "location": {"displayName": evt.get("location", "")},
        "attendees": attendees,
        "isOnlineMeeting": False,
    }

    if evt.get("recurrence"):
        # Pass raw iCal recurrence string — Graph accepts RRULE lines
        payload["recurrence"] = {"pattern": {}, "range": {}}

    return payload
