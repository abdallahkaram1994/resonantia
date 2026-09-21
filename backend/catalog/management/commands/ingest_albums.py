from catalog.ingest import IngestStats
from catalog.management.commands._ingest import IngestCommand
from catalog.sources.albums import AlbumSource
from catalog.sources.base import ItemSource
from catalog.sources.factory import get_album_source

# How to read the drop reasons printed after a run.
_REASONS = {
    "no_mbid": "no MusicBrainz id on Last.fm (never matched by title)",
    "lastfm_not_found": "unknown to Last.fm",
    "no_tags": "no usable tags",
    "no_listener_count": "no listener count",
    "below_threshold": "too few listeners",
    "already_ingested": "already in the catalog",
    "previously_skipped": "rejected in an earlier run (use --retry-skipped)",
    "duplicate": "another release of an album already handled",
    "no_release_group": "no MusicBrainz release group",
    "not_found": "not found at MusicBrainz",
    "not_studio_album": "not a studio album (live, compilation, EP, single...)",
}


class Command(IngestCommand):
    help = (
        "Ingest popular studio albums: Last.fm finds them, MusicBrainz identifies them, and the "
        "Cover Art Archive and Wikipedia add covers and summaries. Resumable and idempotent."
    )
    plural = "Albums"
    source_name = "Last.fm and MusicBrainz (roughly four seconds per album)"
    keywords_label = "tags"
    skip_reason = "missing tags"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--retry-skipped",
            action="store_true",
            help="Look again at albums rejected in an earlier run",
        )

    def handle(self, *args, **options):
        self._retry_skipped = options["retry_skipped"]
        return super().handle(*args, **options)

    def get_source(self) -> ItemSource:
        self._source = get_album_source(
            retry_skipped=self._retry_skipped, heartbeat=self.stdout.write
        )
        return self._source

    def extra_summary(self, stats: IngestStats) -> None:
        source = self._source
        if not isinstance(source, AlbumSource):
            return
        if source.drops:
            self.stdout.write("Albums left out, by reason:")
            for reason, count in source.drops.most_common():
                self.stdout.write(f"  {count:5}  {_REASONS.get(reason, reason)}")
        for label, checked in source.gave_up.items():
            self.stderr.write(
                self.style.WARNING(
                    f"The {label} search gave up after checking {checked} albums on Last.fm. "
                    "Lower ALBUM_MID_TAIL_MIN_LISTENERS or ALBUM_MID_TAIL_START_PAGE, raise "
                    "ALBUM_MID_TAIL_MAX_SCAN, or set MID_TAIL_PERCENT=0 to skip the mid-tail."
                )
            )
