from catalog.management.commands._ingest import IngestCommand
from catalog.sources.base import ItemSource
from catalog.sources.factory import get_game_source


class Command(IngestCommand):
    help = "Ingest popular main games from IGDB. Idempotent and safe to re-run or interrupt."
    plural = "Games"
    source_name = "IGDB"
    keywords_label = "themes or keywords"
    skip_reason = "missing summary, genres and themes"

    def get_source(self) -> ItemSource:
        return get_game_source()
