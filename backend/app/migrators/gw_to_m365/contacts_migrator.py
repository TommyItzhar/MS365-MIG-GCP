"""Google Contacts → Outlook Contacts migrator.

Reads contacts via the Google People API and creates them in the user's
Outlook contacts folder via the Microsoft Graph API.

Phone numbers, email addresses, postal addresses, and job info are preserved.
"""
from __future__ import annotations

import logging
from typing import Optional

from googleapiclient.discovery import build

from app.constants import GW_CONTACTS_MAX_RESULTS
from app.migrators.gw_to_m365.base_migrator import BaseGWMigrator
from app.models import (
    GWMigrationItem,
    GWMigrationScope,
    GWWorkloadType,
    MigrationResult,
)

logger = logging.getLogger(__name__)


class ContactsMigrator(BaseGWMigrator):
    """Migrates Google Contacts → Outlook Contacts."""

    workload = GWWorkloadType.CONTACTS

    async def discover_items(
        self, scope: GWMigrationScope, source_user: str
    ) -> list[GWMigrationItem]:
        dest_user = scope.user_mappings.get(source_user, source_user)
        creds = await self._gw_auth.get_credentials(source_user, "contacts")
        service = build("people", "v1", credentials=creds, cache_discovery=False)

        items: list[GWMigrationItem] = []
        page_token: Optional[str] = None

        while True:
            kwargs: dict = {
                "resourceName": "people/me",
                "personFields": (
                    "names,emailAddresses,phoneNumbers,addresses,"
                    "organizations,biographies,birthdays"
                ),
                "pageSize": GW_CONTACTS_MAX_RESULTS,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            result = service.people().connections().list(**kwargs).execute()
            connections = result.get("connections", [])

            for person in connections:
                resource = person.get("resourceName", "")
                items.append(
                    GWMigrationItem(
                        id=f"{self._job_id}-contact-{resource.replace('/', '_')}",
                        job_id=self._job_id,
                        workload=GWWorkloadType.CONTACTS,
                        source_user=source_user,
                        destination_user=dest_user,
                        source_id=resource,
                        tenant_id=scope.gw_domain,
                        metadata={
                            "display_name": (
                                person.get("names", [{}])[0].get("displayName", "")
                                if person.get("names") else ""
                            )
                        },
                    )
                )

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info(
            "contacts_discovery_done",
            extra={"count": len(items), "job_id": self._job_id},
        )
        return items

    async def migrate_item(self, item: GWMigrationItem) -> MigrationResult:
        creds = await self._gw_auth.get_credentials(item.source_user, "contacts")
        service = build("people", "v1", credentials=creds, cache_discovery=False)

        person = (
            service.people()
            .get(
                resourceName=item.source_id,
                personFields=(
                    "names,emailAddresses,phoneNumbers,addresses,"
                    "organizations,biographies,birthdays"
                ),
            )
            .execute()
        )

        payload = _gw_person_to_graph(person)
        contact_id = await self._writer.create_contact(
            item.destination_user, payload
        )

        return MigrationResult(
            item_id=item.id,
            success=True,
            bytes_transferred=0,
            gcs_uri=f"m365://{item.destination_user}/contacts/{contact_id}",
        )


def _gw_person_to_graph(person: dict) -> dict:
    """Convert a Google People API person to a Graph contacts payload."""
    names = person.get("names", [])
    primary_name = names[0] if names else {}

    emails = [
        {"address": e["value"], "name": e.get("displayName", "")}
        for e in person.get("emailAddresses", [])
    ]
    phones = [
        {"number": p["value"], "type": _map_phone_type(p.get("type", ""))}
        for p in person.get("phoneNumbers", [])
    ]

    orgs = person.get("organizations", [])
    org = orgs[0] if orgs else {}

    payload: dict = {
        "displayName": primary_name.get("displayName", "(unnamed)"),
        "givenName": primary_name.get("givenName", ""),
        "surname": primary_name.get("familyName", ""),
        "emailAddresses": emails[:3],  # Graph allows max 3
        "businessPhones": [p["number"] for p in phones if p["type"] == "business"][:3],
        "mobilePhone": next(
            (p["number"] for p in phones if p["type"] == "mobile"), None
        ),
        "jobTitle": org.get("title", ""),
        "companyName": org.get("name", ""),
        "department": org.get("department", ""),
    }

    addresses = person.get("addresses", [])
    if addresses:
        addr = addresses[0]
        payload["homeAddress"] = {
            "street": addr.get("streetAddress", ""),
            "city": addr.get("city", ""),
            "state": addr.get("region", ""),
            "postalCode": addr.get("postalCode", ""),
            "countryOrRegion": addr.get("country", ""),
        }

    bios = person.get("biographies", [])
    if bios:
        payload["personalNotes"] = bios[0].get("value", "")[:1000]

    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


def _map_phone_type(gw_type: str) -> str:
    mapping = {
        "mobile": "mobile",
        "work": "business",
        "home": "home",
        "main": "business",
        "workFax": "businessFax",
        "homeFax": "homeFax",
    }
    return mapping.get(gw_type, "other")
