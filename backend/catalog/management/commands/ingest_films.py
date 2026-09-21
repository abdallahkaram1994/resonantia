from datetime import UTC, datetime

from django.conf import settings

from catalog.ingest import FilmItems, IngestStats, oldest_tmdb_fetch, stale_cache_warning
from catalog.management.commands._ingest import IngestCommand
from catalog.sources.base import ItemSource
from catalog.sources.factory import get_film_source


class Command(IngestCommand):
    help = "Ingest popular films from TMDB. Idempotent and safe to re-run or interrupt."
    plural = "Films"
    source_name = "TMDB"
    skip_reason = "missing overview, genres and keywords"

    def get_source(self) -> ItemSource:
        return FilmItems(get_film_source())

    def extra_summary(self, stats: IngestStats) -> None:
        oldest = oldest_tmdb_fetch()
        if oldest is not None:
            self.stdout.write(f"Oldest TMDB fetch in the catalog: {oldest:%Y-%m-%d}.")
        warning = stale_cache_warning(oldest, settings.TMDB_MAX_CACHE_DAYS, datetime.now(UTC))
        if warning:
            self.stderr.write(self.style.WARNING(warning))
