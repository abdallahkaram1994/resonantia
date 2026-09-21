"""What the album pipeline already knows, so a re-run only does new work."""

from typing import Protocol

from catalog.models import ExternalId, SkippedRecord

RELEASE_SOURCE = "musicbrainz-release"
GROUP_SOURCE = "musicbrainz"


class Ledger(Protocol):
    def is_known(self, release_mbid: str) -> bool:
        """Was an album with this release id already ingested?"""
        ...

    def group_item_exists(self, group_mbid: str) -> bool:
        """Is there already an item for this release-group (reached through another release)?"""
        ...

    def link_release(self, group_mbid: str, release_mbid: str) -> None:
        """Remember another release of an item that already exists."""
        ...

    def is_skipped(self, release_mbid: str) -> bool:
        """Was this release checked before and rejected?"""
        ...

    def mark_skipped(self, release_mbid: str, reason: str) -> None: ...


class DbLedger:
    """The ledger kept in the database. `retry_skipped` forgets earlier rejections."""

    def __init__(self, *, retry_skipped: bool = False) -> None:
        self._retry_skipped = retry_skipped

    def is_known(self, release_mbid: str) -> bool:
        return ExternalId.objects.filter(source=RELEASE_SOURCE, external_id=release_mbid).exists()

    def group_item_exists(self, group_mbid: str) -> bool:
        return ExternalId.objects.filter(source=GROUP_SOURCE, external_id=group_mbid).exists()

    def link_release(self, group_mbid: str, release_mbid: str) -> None:
        existing = ExternalId.objects.filter(source=GROUP_SOURCE, external_id=group_mbid).first()
        if existing is not None:
            ExternalId.objects.get_or_create(
                source=RELEASE_SOURCE,
                external_id=release_mbid,
                defaults={"item": existing.item},
            )

    def is_skipped(self, release_mbid: str) -> bool:
        if self._retry_skipped:
            return False
        return SkippedRecord.objects.filter(
            source=RELEASE_SOURCE, external_id=release_mbid
        ).exists()

    def mark_skipped(self, release_mbid: str, reason: str) -> None:
        SkippedRecord.objects.update_or_create(
            source=RELEASE_SOURCE, external_id=release_mbid, defaults={"reason": reason}
        )
