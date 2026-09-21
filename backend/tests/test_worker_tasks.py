"""The background jobs and how they are queued (SPEC section 9b). The queue is Procrastinate's
in-memory connector, so nothing here needs a running worker or any network."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from procrastinate import testing
from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from catalog import tasks
from catalog.embed import EmbedStats
from catalog.embedding.base import (
    EmbeddingRateLimited,
    EmbeddingRequestError,
    EmbeddingUnavailable,
)
from catalog.ingest import IngestStats
from catalog.sources.base import SourceRequestError, SourceUnavailable


@pytest.fixture
def queue() -> Iterator[testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    with app.replace_connector(connector):
        yield connector


def queued(queue: testing.InMemoryConnector) -> list[tuple[str, dict]]:
    return [(job["task_name"], job["args"]) for job in queue.jobs.values()]


def run_worker(queue: testing.InMemoryConnector) -> None:
    with app.replace_connector(queue) as worker_app:
        worker_app.run_worker(wait=False, listen_notify=False, install_signal_handlers=False)


def status_of(queue: testing.InMemoryConnector, task_name: str) -> str:
    (job,) = [j for j in queue.jobs.values() if j["task_name"] == task_name]
    return job["status"]


# --- registration -----------------------------------------------------------------------------

ALL_TASKS = {
    "ingest_films": tasks.ingest_films,
    "ingest_games": tasks.ingest_games,
    "ingest_albums": tasks.ingest_albums,
    "embed_pending": tasks.embed_pending,
}


@pytest.mark.parametrize("name", sorted(ALL_TASKS))
def test_every_job_is_registered_on_the_ingest_queue_with_a_queueing_lock_of_its_own(
    name: str,
) -> None:
    task = ALL_TASKS[name]

    assert task.name == f"catalog.tasks.{name}"
    assert app.tasks[task.name] is task
    assert task.queue == "ingest"
    assert task.queueing_lock == name


def test_only_the_album_job_holds_the_musicbrainz_lock() -> None:
    assert {name: t.lock for name, t in ALL_TASKS.items()} == {
        "ingest_films": None,
        "ingest_games": None,
        "ingest_albums": "musicbrainz",
        "embed_pending": None,
    }


def test_only_temporary_outages_are_retried() -> None:
    for task in ALL_TASKS.values():
        strategy = task.retry_strategy
        assert strategy.max_attempts == 3
        assert strategy.retry_exceptions == {SourceUnavailable, EmbeddingUnavailable}


# --- ingest jobs ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "media"),
    [("ingest_films", "films"), ("ingest_games", "games"), ("ingest_albums", "albums")],
)
def test_an_ingest_job_ingests_its_media_type_and_then_queues_embedding(
    queue: testing.InMemoryConnector, name: str, media: str
) -> None:
    with mock.patch.object(tasks.jobs, "ingest", return_value=IngestStats(created=2)) as ingest:
        ALL_TASKS[name](limit=25)

    ingest.assert_called_once_with(media, 25)
    assert queued(queue) == [("catalog.tasks.embed_pending", {})]


def test_an_ingest_job_without_a_limit_leaves_the_choice_to_the_default(
    queue: testing.InMemoryConnector,
) -> None:
    with mock.patch.object(tasks.jobs, "ingest", return_value=IngestStats()) as ingest:
        tasks.ingest_games()

    ingest.assert_called_once_with("games", None)


def test_a_failed_ingest_queues_no_embedding(queue: testing.InMemoryConnector) -> None:
    with (
        mock.patch.object(tasks.jobs, "ingest", side_effect=SourceUnavailable("IGDB is down")),
        pytest.raises(SourceUnavailable),
    ):
        tasks.ingest_games(limit=5)

    assert queued(queue) == []


def test_a_second_ingest_finishing_while_embedding_waits_does_not_queue_another(
    queue: testing.InMemoryConnector, caplog: pytest.LogCaptureFixture
) -> None:
    tasks.embed_pending.defer()

    with (
        mock.patch.object(tasks.jobs, "ingest", return_value=IngestStats()),
        caplog.at_level(logging.INFO, logger="catalog.tasks"),
    ):
        tasks.ingest_films(limit=1)

    assert queued(queue) == [("catalog.tasks.embed_pending", {})]
    assert "already queued" in caplog.text


def test_the_ingest_summary_is_logged(
    queue: testing.InMemoryConnector, caplog: pytest.LogCaptureFixture
) -> None:
    stats = IngestStats(created=3, updated=2, unchanged=1, skipped_not_embeddable=4)
    with (
        mock.patch.object(tasks.jobs, "ingest", return_value=stats),
        caplog.at_level(logging.INFO, logger="catalog.tasks"),
    ):
        tasks.ingest_albums(limit=9)

    assert "Ingested albums: 3 created, 2 updated, 1 unchanged, 4 skipped." in caplog.text


# --- embedding job ----------------------------------------------------------------------------


def test_the_embedding_job_passes_its_limit_on(caplog: pytest.LogCaptureFixture) -> None:
    with (
        mock.patch.object(tasks.jobs, "embed", return_value=EmbedStats(embedded=6)) as embed,
        caplog.at_level(logging.INFO, logger="catalog.tasks"),
    ):
        tasks.embed_pending(limit=10)
        tasks.embed_pending()

    assert [c.args for c in embed.call_args_list] == [(10,), (None,)]
    assert "Embedded 6 items." in caplog.text


@pytest.mark.parametrize(
    ("quota_exhausted", "expected"),
    [(True, "daily quota is used up"), (False, "provider is rate limiting")],
)
def test_stopping_at_a_limit_is_a_warning_with_progress_kept_not_a_failure(
    caplog: pytest.LogCaptureFixture, quota_exhausted: bool, expected: str
) -> None:
    stop = EmbeddingRateLimited("limit", retry_after=None, quota_exhausted=quota_exhausted)
    with (
        mock.patch.object(tasks.jobs, "embed", return_value=EmbedStats(embedded=41, stopped=stop)),
        caplog.at_level(logging.INFO, logger="catalog.tasks"),
    ):
        tasks.embed_pending()  # returns normally, so the worker does not retry it

    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert "after 41 items" in record.getMessage()
    assert expected in record.getMessage()


# --- queueing ---------------------------------------------------------------------------------


def test_the_same_job_cannot_wait_in_the_queue_twice(queue: testing.InMemoryConnector) -> None:
    tasks.ingest_films.defer(limit=5)

    with pytest.raises(AlreadyEnqueued):
        tasks.ingest_films.defer(limit=500)

    assert queued(queue) == [("catalog.tasks.ingest_films", {"limit": 5})]


def test_different_jobs_do_not_block_each_other(queue: testing.InMemoryConnector) -> None:
    for task in ALL_TASKS.values():
        task.defer()

    assert len(queue.jobs) == 4


def test_a_job_can_be_queued_again_once_the_earlier_one_has_run(
    queue: testing.InMemoryConnector,
) -> None:
    with mock.patch.object(tasks.jobs, "embed", return_value=EmbedStats()):
        tasks.embed_pending.defer()
        run_worker(queue)
        tasks.embed_pending.defer()

    assert [j["status"] for j in queue.jobs.values()] == ["succeeded", "todo"]


# --- what the worker does with failures --------------------------------------------------------


@pytest.mark.parametrize(
    "error", [SourceUnavailable("IGDB is down"), EmbeddingUnavailable("Gemini is down")]
)
def test_the_worker_retries_a_temporary_outage_later(
    queue: testing.InMemoryConnector, error: Exception
) -> None:
    with mock.patch.object(tasks.jobs, "embed", side_effect=error):
        tasks.embed_pending.defer()
        run_worker(queue)

    (job,) = queue.jobs.values()
    assert job["status"] == "todo"
    assert job["attempts"] == 1
    assert job["scheduled_at"] is not None


@pytest.mark.parametrize(
    "error",
    [
        SourceRequestError("TMDB_API_TOKEN was rejected"),
        EmbeddingRequestError("GEMINI_API_KEY was rejected"),
        ValueError("bug"),
    ],
)
def test_the_worker_does_not_retry_what_will_not_fix_itself(
    queue: testing.InMemoryConnector, error: Exception
) -> None:
    with mock.patch.object(tasks.jobs, "embed", side_effect=error):
        tasks.embed_pending.defer()
        run_worker(queue)

    (job,) = queue.jobs.values()
    assert job["status"] == "failed"
    assert job["attempts"] == 1


def test_a_persistent_outage_is_retried_three_times_with_growing_waits_and_then_fails(
    queue: testing.InMemoryConnector,
) -> None:
    waits: list[float] = []
    statuses: list[str] = []
    with mock.patch.object(tasks.jobs, "embed", side_effect=SourceUnavailable("down")):
        tasks.embed_pending.defer()
        for _ in range(6):
            started = datetime.now(UTC)
            run_worker(queue)
            (job,) = queue.jobs.values()
            statuses.append(job["status"])
            if job["scheduled_at"] is not None:
                waits.append((job["scheduled_at"] - started).total_seconds())
                job["scheduled_at"] = None  # do not wait out the backoff

    # Four runs (the first and three retries); later passes find nothing left to do.
    assert statuses == ["todo", "todo", "todo", "failed", "failed", "failed"]
    assert [round(w) for w in waits] == [8, 64, 512]
    assert job["attempts"] == 4


def test_the_worker_runs_a_job_with_its_arguments(queue: testing.InMemoryConnector) -> None:
    with mock.patch.object(tasks.jobs, "embed", return_value=EmbedStats(embedded=1)) as embed:
        tasks.embed_pending.defer(limit=12)
        run_worker(queue)

    embed.assert_called_once_with(12)
    assert status_of(queue, "catalog.tasks.embed_pending") == "succeeded"


# --- enqueue_job ------------------------------------------------------------------------------


def enqueue(*args: str) -> str:
    out = StringIO()
    call_command("enqueue_job", *args, stdout=out)
    return out.getvalue()


@pytest.mark.parametrize("name", sorted(ALL_TASKS))
def test_enqueue_job_queues_the_named_job(queue: testing.InMemoryConnector, name: str) -> None:
    out = enqueue(name)

    assert queued(queue) == [(f"catalog.tasks.{name}", {})]
    assert f"Queued {name} as job" in out
    assert "docker compose logs -f worker" in out


def test_enqueue_job_passes_the_limit_on(queue: testing.InMemoryConnector) -> None:
    enqueue("ingest_games", "--limit", "40")

    assert queued(queue) == [("catalog.tasks.ingest_games", {"limit": 40})]


def test_enqueue_job_says_so_when_the_job_is_already_waiting(
    queue: testing.InMemoryConnector,
) -> None:
    enqueue("ingest_albums", "--limit", "10")

    out = enqueue("ingest_albums", "--limit", "20")

    assert "already waiting in the queue" in out
    assert "Queued" not in out
    assert queued(queue) == [("catalog.tasks.ingest_albums", {"limit": 10})]


@pytest.mark.parametrize("bad", ["0", "-3"])
def test_enqueue_job_rejects_a_limit_below_one(queue: testing.InMemoryConnector, bad: str) -> None:
    with pytest.raises(CommandError, match="at least 1"):
        enqueue("embed_pending", "--limit", bad)

    assert queued(queue) == []


def test_enqueue_job_offers_only_the_known_jobs(queue: testing.InMemoryConnector) -> None:
    with pytest.raises(CommandError, match="invalid choice"):
        enqueue("drop_database")

    assert queued(queue) == []
