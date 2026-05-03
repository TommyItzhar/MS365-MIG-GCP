"""Google Workspace Directory → Microsoft Entra ID migrator.

Reads users and groups from Google Admin SDK Directory API and syncs them
into Entra ID via the Microsoft Graph API.

Only creates/updates users — never deletes, to avoid accidental data loss.
Passwords are NOT migrated (users must reset via SSPR or admin-set password).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.migrators.gw_to_m365.base_migrator import BaseGWMigrator
from app.models import (
    GWMigrationItem,
    GWMigrationScope,
    GWWorkloadType,
    MigrationResult,
)

logger = logging.getLogger(__name__)


class IdentityMigrator(BaseGWMigrator):
    """Migrates Google Workspace users → Microsoft Entra ID."""

    workload = GWWorkloadType.IDENTITY

    async def discover_items(
        self, scope: GWMigrationScope, source_user: str
    ) -> list[GWMigrationItem]:
        """List all active GW users. source_user must be a Workspace admin."""
        dest_user = scope.user_mappings.get(source_user, source_user)

        users = await self._gw_auth.list_workspace_users(admin_email=source_user)
        items: list[GWMigrationItem] = []

        for user in users:
            gw_email = user.get("primaryEmail", "")
            if not gw_email:
                continue
            items.append(
                GWMigrationItem(
                    id=f"{self._job_id}-identity-{user['id']}",
                    job_id=self._job_id,
                    workload=GWWorkloadType.IDENTITY,
                    source_user=source_user,
                    destination_user=dest_user,
                    source_id=user["id"],
                    tenant_id=scope.gw_domain,
                    metadata={
                        "primary_email": gw_email,
                        "full_name": user.get("name", {}).get("fullName", ""),
                        "given_name": user.get("name", {}).get("givenName", ""),
                        "family_name": user.get("name", {}).get("familyName", ""),
                        "org_unit": user.get("orgUnitPath", "/"),
                        "job_title": user.get("organizations", [{}])[0].get("title", "")
                            if user.get("organizations") else "",
                        "department": user.get("organizations", [{}])[0].get("department", "")
                            if user.get("organizations") else "",
                    },
                )
            )

        logger.info(
            "identity_discovery_done",
            extra={"count": len(items), "job_id": self._job_id},
        )
        return items

    async def migrate_item(self, item: GWMigrationItem) -> MigrationResult:
        """Create or update the user in Entra ID."""
        meta = item.metadata
        gw_email = meta.get("primary_email", "")
        m365_upn = item.destination_user if "@" in item.destination_user else gw_email

        # Build a mail-nickname from the local part of the UPN
        mail_nickname = re.sub(r"[^a-zA-Z0-9._-]", "", m365_upn.split("@")[0])[:64]

        user_payload = {
            "accountEnabled": True,
            "displayName": meta.get("full_name") or m365_upn.split("@")[0],
            "givenName": meta.get("given_name", ""),
            "surname": meta.get("family_name", ""),
            "userPrincipalName": m365_upn,
            "mailNickname": mail_nickname,
            "jobTitle": meta.get("job_title", ""),
            "department": meta.get("department", ""),
            # Temporary password — admin must distribute and enforce reset
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": _temp_password(item.source_id),
            },
        }
        # Remove empty optional fields to avoid Graph validation errors
        user_payload = {k: v for k, v in user_payload.items() if v not in ("", None)}

        object_id, was_created = await self._writer.create_or_update_user(user_payload)

        action = "created" if was_created else "updated"
        logger.info(
            f"identity_user_{action}",
            extra={"object_id": object_id, "job_id": self._job_id},
        )

        return MigrationResult(
            item_id=item.id,
            success=True,
            bytes_transferred=0,
            gcs_uri=f"m365://users/{object_id}",
        )


def _temp_password(seed: str) -> str:
    """Generate a deterministic but strong temporary password.

    This is a stopgap — admins MUST distribute passwords out-of-band
    and users will be forced to reset on first login.
    """
    import hashlib
    digest = hashlib.sha256(f"gw-migration-{seed}".encode()).hexdigest()[:16]
    # Ensure complexity: uppercase, lowercase, digit, special char
    return f"Mig@{digest[:12]}1!"
