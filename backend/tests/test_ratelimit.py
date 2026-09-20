from catalog.ratelimit import Throttle
from tests.helpers import FakeClock


def test_first_call_does_not_wait() -> None:
    clock = FakeClock()
    throttle = Throttle(2.0, clock=clock.time, sleep=clock.sleep)

    throttle.wait()

    assert clock.sleeps == []


def test_back_to_back_calls_are_spaced_by_the_interval() -> None:
    clock = FakeClock()
    throttle = Throttle(2.0, clock=clock.time, sleep=clock.sleep)

    for _ in range(3):
        throttle.wait()

    assert clock.sleeps == [2.0, 2.0]
    assert clock.now == 4.0


def test_a_call_after_the_interval_does_not_wait() -> None:
    clock = FakeClock()
    throttle = Throttle(2.0, clock=clock.time, sleep=clock.sleep)
    throttle.wait()
    clock.now += 5.0

    throttle.wait()

    assert clock.sleeps == []


def test_partial_elapsed_time_only_waits_for_the_remainder() -> None:
    clock = FakeClock()
    throttle = Throttle(2.0, clock=clock.time, sleep=clock.sleep)
    throttle.wait()
    clock.now += 0.5

    throttle.wait()

    assert clock.sleeps == [1.5]
