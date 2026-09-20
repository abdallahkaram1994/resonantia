from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from catalog.embed import EmbedStats, embed_pending, pending_items
from catalog.embedding.base import EmbeddingError
from catalog.embedding.factory import get_embedder


class Command(BaseCommand):
    help = "Embed items that have no vector yet (or one from another model). Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="Embed at most this many items")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        try:
            embedder = get_embedder()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from error

        total = pending_items(embedder).count()
        self.stdout.write(f"{total} items need embedding with {embedder.model}.")

        def progress(stats: EmbedStats) -> None:
            if stats.embedded % 25 == 0:
                self.stdout.write(f"  {stats.embedded} embedded...")

        try:
            stats = embed_pending(embedder, limit=limit, progress=progress)
        except EmbeddingError as error:
            raise CommandError(
                f"{error} Vectors already saved are kept; run the command again to continue."
            ) from error

        remaining = pending_items(embedder).count()
        self.stdout.write(self.style.SUCCESS(f"Embedded {stats.embedded}; {remaining} remaining."))
        if stats.stopped is not None:
            reason = (
                "the daily quota is used up, so try again tomorrow"
                if stats.stopped.quota_exhausted
                else "the provider is rate limiting, so wait a while and run it again"
            )
            self.stdout.write(self.style.WARNING(f"Stopped early: {reason}."))
