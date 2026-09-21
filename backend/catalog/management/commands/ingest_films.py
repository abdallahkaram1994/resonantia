from datetime import UTC, datetime

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from catalog.ingest import IngestStats, ingest_films, oldest_tmdb_fetch, stale_cache_warning
from catalog.sources.base import SourceError
from catalog.sources.factory import get_film_source


class Command(BaseCommand):
    help = "Ingest popular films from TMDB. Idempotent and safe to re-run or interrupt."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            help="Films to ingest (default: INGEST_LIMIT, else CATALOG_TARGET_PER_TYPE)",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is None:
            limit = settings.INGEST_LIMIT or settings.CATALOG_TARGET_PER_TYPE
        if limit < 1:
            raise CommandError("--limit must be at least 1")
        try:
            source = get_film_source()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from error

        def progress(stats: IngestStats) -> None:
            if stats.ingested % 50 == 0:
                self.stdout.write(f"  {stats.ingested} films ingested...")

        self.stdout.write(f"Ingesting up to {limit} films from TMDB (this can take a while).")
        try:
            stats = ingest_films(
                source,
                limit=limit,
                mid_tail_percent=settings.MID_TAIL_PERCENT,
                progress=progress,
            )
        except SourceError as error:
            raise CommandError(
                f"{error} Films already ingested are kept; run the command again to continue."
            ) from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {stats.created} created, {stats.updated} updated, "
                f"{stats.unchanged} unchanged, {stats.skipped_not_embeddable} skipped "
                f"(missing overview, genres and keywords)."
            )
        )
        self.stdout.write(f"Films with keywords: {stats.with_keywords} of {stats.ingested}.")
        oldest = oldest_tmdb_fetch()
        if oldest is not None:
            self.stdout.write(f"Oldest TMDB fetch in the catalog: {oldest:%Y-%m-%d}.")
        warning = stale_cache_warning(oldest, settings.TMDB_MAX_CACHE_DAYS, datetime.now(UTC))
        if warning:
            self.stderr.write(self.style.WARNING(warning))
        self.stdout.write("Next: python manage.py embed_items")
