from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "catalog"

    def ready(self) -> None:
        from catalog import checks  # noqa: F401
