"""Firestore Writer — batch writes, transactions, and retry on contention."""
from __future__ import annotations

import logging
from typing import Any, Optional

from google.api_core.exceptions import Aborted, DeadlineExceeded
from google.cloud import firestore

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_MAX_BATCH_SIZE = 500  # Firestore limit per batch commit


class FirestoreWriter:
    """Wraps Firestore for the migration engine's state persistence needs."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Optional[firestore.AsyncClient] = None

    def _get_client(self) -> firestore.AsyncClient:
        if self._client is None:
            self._client = firestore.AsyncClient(
                project=self._settings.gcp.project_id,
                database=self._settings.gcp.firestore_database,
            )
        return self._client

    # ── Single document operations ─────────────────────────────────────────

    async def set(
        self,
        collection: str,
        doc_id: str,
        data: dict[str, Any],
        merge: bool = False,
    ) -> None:
        db = self._get_client()
        ref = db.collection(collection).document(doc_id)
        if merge:
            await ref.set(data, merge=True)
        else:
            await ref.set(data)

    async def get(
        self, collection: str, doc_id: str
    ) -> Optional[dict[str, Any]]:
        db = self._get_client()
        doc = await db.collection(collection).document(doc_id).get()
        return doc.to_dict() if doc.exists else None

    async def update(
        self, collection: str, doc_id: str, fields: dict[str, Any]
    ) -> None:
        db = self._get_client()
        await db.collection(collection).document(doc_id).update(fields)

    async def delete(self, collection: str, doc_id: str) -> None:
        db = self._get_client()
        await db.collection(collection).document(doc_id).delete()

    # ── Batch writes ───────────────────────────────────────────────────────

    async def batch_set(
        self,
        collection: str,
        documents: list[tuple[str, dict[str, Any]]],
        merge: bool = False,
    ) -> None:
        """Write many documents in Firestore batch commits (≤500 per batch)."""
        db = self._get_client()
        for i in range(0, len(documents), _MAX_BATCH_SIZE):
            chunk = documents[i : i + _MAX_BATCH_SIZE]
            batch = db.batch()
            for doc_id, data in chunk:
                ref = db.collection(collection).document(doc_id)
                if merge:
                    batch.set(ref, data, merge=True)
                else:
                    batch.set(ref, data)
            await batch.commit()
            logger.debug(
                "firestore_batch_committed",
                extra={"collection": collection, "count": len(chunk)},
            )

    # ── Queries ────────────────────────────────────────────────────────────

    async def query(
        self,
        collection: str,
        filters: Optional[list[tuple[str, str, Any]]] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query a collection with optional field filters."""
        db = self._get_client()
        ref: Any = db.collection(collection)
        if filters:
            for field_name, op, value in filters:
                ref = ref.where(field_name, op, value)
        ref = ref.limit(limit)
        docs = await ref.get()
        return [doc.to_dict() for doc in docs if doc.to_dict()]

    # ── Transactional upsert ───────────────────────────────────────────────

    async def transact_update(
        self,
        collection: str,
        doc_id: str,
        update_fn: Any,
        max_retries: int = 5,
    ) -> None:
        """Apply update_fn(snapshot) → dict in a Firestore transaction.

        Retries on contention (Aborted) up to max_retries times.
        """
        db = self._get_client()
        ref = db.collection(collection).document(doc_id)

        for attempt in range(max_retries):
            try:
                transaction = db.transaction()

                @firestore.async_transactional
                async def _txn(transaction: Any, ref: Any) -> None:
                    snapshot = await ref.get(transaction=transaction)
                    new_data = update_fn(
                        snapshot.to_dict() if snapshot.exists else {}
                    )
                    transaction.set(ref, new_data, merge=True)

                await _txn(transaction, ref)
                return
            except (Aborted, DeadlineExceeded) as exc:
                if attempt == max_retries - 1:
                    raise
                import asyncio

                await asyncio.sleep(0.5 * (2**attempt))
                logger.warning(
                    "firestore_transaction_retry",
                    extra={"attempt": attempt, "error": str(exc)},
                )
