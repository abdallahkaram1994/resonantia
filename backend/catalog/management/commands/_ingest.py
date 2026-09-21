from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from catalog.ingest import IngestStats, ingest_items
from catalog.sources.base import ItemSource, SourceError


class IngestCommand(BaseCommand):
    """Shared behavior of the ingest_* commands: limit handling, progress and a summary."""

    plural = "items"
    source_name = ""
    keywords_label = "keywords"
    skip_reason = "missing summary, genres and keywords"

    def get_source(self) -> ItemSource:
        raise NotImplementedError

    def extra_summary(self, stats: IngestStats) -> None:
        """Hook for lines that only make sense for one source."""

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            help=f"{self.plural} to ingest (default: INGEST_LIMIT, else CATALOG_TARGET_PER_TYPE)",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is None:
            limit = settings.INGEST_LIMIT or settings.CATALOG_TARGET_PER_TYPE
        if limit < 1:
            raise CommandError("--limit must be at least 1")
        try:
            source = self.get_source()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from error

        def progress(stats: IngestStats) -> None:
            if stats.ingested % 50 == 0:
                self.stdout.write(f"  {stats.ingested} {self.plural.lower()} ingested...")

        self.stdout.write(
            f"Ingesting up to {limit} {self.plural.lower()} from {self.source_name} "
            "(this can take a while)."
        )
        try:
            stats = ingest_items(
                source,
                limit=limit,
                mid_tail_percent=settings.MID_TAIL_PERCENT,
                progress=progress,
            )
        except SourceError as error:
            kept = f"{self.plural} already ingested are kept; run the command again to continue."
            raise CommandError(f"{error} {kept}") from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {stats.created} created, {stats.updated} updated, "
                f"{stats.unchanged} unchanged, {stats.skipped_not_embeddable} skipped "
                f"({self.skip_reason})."
            )
        )
        self.stdout.write(
            f"{self.plural} with {self.keywords_label}: {stats.with_keywords} of {stats.ingested}."
        )
        self.extra_summary(stats)
        self.stdout.write("Next: python manage.py embed_items")
