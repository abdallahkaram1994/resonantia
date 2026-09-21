from django.core.management.base import BaseCommand, CommandError
from procrastinate.exceptions import AlreadyEnqueued

from catalog import tasks

# Jobs go through management commands, never through public endpoints (SPEC section 9b).
JOBS = {
    "ingest_films": tasks.ingest_films,
    "ingest_games": tasks.ingest_games,
    "ingest_albums": tasks.ingest_albums,
    "embed_pending": tasks.embed_pending,
}


class Command(BaseCommand):
    help = (
        "Queue a background job for the worker. Watch it run with: docker compose logs -f worker. "
        "Ingest jobs queue an embedding job when they finish."
    )

    def add_arguments(self, parser):
        parser.add_argument("job", choices=sorted(JOBS))
        parser.add_argument(
            "--limit",
            type=int,
            help=(
                "New items to ingest (default: INGEST_LIMIT, else CATALOG_TARGET_PER_TYPE) or "
                "items to embed (default: all that are waiting)"
            ),
        )

    def handle(self, *args, **options):
        name, limit = options["job"], options["limit"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        try:
            job_id = JOBS[name].defer(**({} if limit is None else {"limit": limit}))
        except AlreadyEnqueued:
            self.stdout.write(
                f"A {name} job is already waiting in the queue, so nothing was added."
            )
            return
        self.stdout.write(self.style.SUCCESS(f"Queued {name} as job {job_id}."))
        self.stdout.write("Follow it with: docker compose logs -f worker")
