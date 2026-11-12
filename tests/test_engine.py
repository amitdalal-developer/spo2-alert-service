from typing import List

import pytest

from spo2_monitor.clock import FakeClock
from spo2_monitor.engine import AlertEngine
from spo2_monitor.models import AlertType, Reading

T0 = 1730480400000


@pytest.fixture
def clock():
    return FakeClock(start_ms=T0)


@pytest.fixture
def engine(clock):
    return AlertEngine(clock=clock)


class Feeder:
    """Sends readings at 1 Hz, advancing both device ts and the server clock."""

    def __init__(self, engine, clock, patient_id="P-001"):
        self.engine, self.clock, self.pid = engine, clock, patient_id
        self.ts = T0

    def send(self, spo2, quality="good", n=1):
        for _ in range(n):
            self.engine.process(
                Reading(patient_id=self.pid, ts=self.ts, spo2=spo2, quality=quality)
            )
            self.ts += 1000
            self.clock.advance(1000)


@pytest.fixture
def feed(engine, clock):
    return Feeder(engine, clock)


def types(engine, pid="P-001") -> List[AlertType]:
    return [a.type for a in engine.active_alerts(pid)]


# REQ-1 ----------------------------------------------------------------------

def test_req1_patients_are_tracked_independently(engine, clock):
    a, b = Feeder(engine, clock, "P-001"), Feeder(engine, clock, "P-002")
    for _ in range(10):
        a.send(85)
        b.send(97)
    assert types(engine, "P-001") == [AlertType.LOW_SPO2]
    assert types(engine, "P-002") == []


def test_req1_unknown_patient_returns_none(engine):
    assert engine.active_alerts("nobody") is None


# REQ-2 ----------------------------------------------------------------------

def test_req2_nine_low_readings_do_not_alert(engine, feed):
    feed.send(85, n=9)
    assert types(engine) == []


def test_req2_ten_low_readings_raise_low_spo2(engine, feed):
    feed.send(85, n=10)
    alerts = engine.active_alerts("P-001")
    assert [a.type for a in alerts] == [AlertType.LOW_SPO2]
    assert alerts[0].start_time == T0  # ts of first low reading in the run


def test_req2_reading_of_90_is_not_low(engine, feed):
    feed.send(90, n=20)
    assert types(engine) == []


def test_req2_borderline_reading_breaks_low_run(engine, feed):
    feed.send(85, n=9)
    feed.send(91)
    feed.send(85, n=9)
    assert types(engine) == []
    feed.send(85)
    assert types(engine) == [AlertType.LOW_SPO2]


def test_req2_high_reading_breaks_low_run(engine, feed):
    feed.send(85, n=9)
    feed.send(95)
    feed.send(85, n=9)
    assert types(engine) == []


def test_req2_alert_not_duplicated_and_start_time_kept(engine, feed):
    feed.send(85, n=25)
    alerts = engine.active_alerts("P-001")
    assert len(alerts) == 1 and alerts[0].start_time == T0


# REQ-3 ----------------------------------------------------------------------

def test_req3_ten_readings_at_or_above_92_clear(engine, feed):
    feed.send(85, n=10)
    feed.send(92, n=9)
    assert types(engine) == [AlertType.LOW_SPO2]
    feed.send(92)
    assert types(engine) == []


def test_req3_readings_of_90_or_91_do_not_clear(engine, feed):
    feed.send(85, n=10)
    feed.send(91, n=20)
    assert types(engine) == [AlertType.LOW_SPO2]


def test_req3_low_reading_breaks_clear_run(engine, feed):
    feed.send(85, n=10)
    feed.send(95, n=9)
    feed.send(88)
    feed.send(95, n=9)
    assert types(engine) == [AlertType.LOW_SPO2]
    feed.send(95)
    assert types(engine) == []


def test_req3_alert_can_be_raised_again_after_clearing(engine, feed):
    feed.send(85, n=10)
    feed.send(95, n=10)
    start = feed.ts
    feed.send(85, n=10)
    alerts = engine.active_alerts("P-001")
    assert [a.type for a in alerts] == [AlertType.LOW_SPO2]
    assert alerts[0].start_time == start


# REQ-4 ----------------------------------------------------------------------

def test_req4_poor_readings_do_not_raise(engine, feed):
    feed.send(70, quality="poor", n=30)
    assert types(engine) == []


def test_req4_poor_readings_do_not_break_low_window(engine, feed):
    feed.send(85, n=5)
    feed.send(99, quality="poor", n=3)
    feed.send(85, n=4)
    assert types(engine) == []
    feed.send(85)  # 10th good low reading
    assert types(engine) == [AlertType.LOW_SPO2]


def test_req4_poor_readings_do_not_clear(engine, feed):
    feed.send(85, n=10)
    feed.send(99, quality="poor", n=30)
    assert types(engine) == [AlertType.LOW_SPO2]


def test_req4_poor_readings_do_not_break_clear_window(engine, feed):
    feed.send(85, n=10)
    feed.send(95, n=5)
    feed.send(70, quality="poor", n=3)
    feed.send(95, n=4)
    assert types(engine) == [AlertType.LOW_SPO2]
    feed.send(95)
    assert types(engine) == []


# REQ-5 ----------------------------------------------------------------------

def test_req5_exactly_30s_is_not_signal_loss(engine, feed, clock):
    feed.send(97)
    last_arrival = clock.now_ms() - 1000
    assert engine.check_signal_loss(last_arrival + 30_000) == []
    assert types(engine) == []


def test_req5_more_than_30s_raises_signal_loss(engine, feed, clock):
    feed.send(97)
    last_arrival = clock.now_ms() - 1000
    assert engine.check_signal_loss(last_arrival + 30_001) == ["P-001"]
    alerts = engine.active_alerts("P-001")
    assert [a.type for a in alerts] == [AlertType.SIGNAL_LOSS]
    assert alerts[0].start_time == last_arrival + 30_001


def test_req5_signal_loss_uses_server_clock(engine, feed, clock):
    feed.send(97)
    clock.advance(31_000)
    engine.check_signal_loss()
    assert types(engine) == [AlertType.SIGNAL_LOSS]


def test_req5_poor_readings_prevent_signal_loss(engine, feed, clock):
    feed.send(97)
    feed.send(97, quality="poor", n=60)
    engine.check_signal_loss()
    assert types(engine) == []


def test_req5_poor_reading_does_not_clear_signal_loss(engine, feed, clock):
    feed.send(97)
    clock.advance(31_000)
    engine.check_signal_loss()
    feed.send(97, quality="poor", n=5)
    assert types(engine) == [AlertType.SIGNAL_LOSS]


def test_req5_good_reading_clears_signal_loss(engine, feed, clock):
    feed.send(97)
    clock.advance(31_000)
    engine.check_signal_loss()
    feed.send(97)
    assert types(engine) == []


def test_req5_signal_loss_not_duplicated(engine, feed, clock):
    feed.send(97)
    clock.advance(31_000)
    assert engine.check_signal_loss() == ["P-001"]
    clock.advance(10_000)
    assert engine.check_signal_loss() == []
    assert types(engine) == [AlertType.SIGNAL_LOSS]


def test_req5_signal_loss_resets_window_but_keeps_low_alert(engine, feed, clock):
    feed.send(85, n=10)
    feed.send(95, n=9)
    clock.advance(31_000)
    engine.check_signal_loss()
    assert set(types(engine)) == {AlertType.LOW_SPO2, AlertType.SIGNAL_LOSS}
    feed.send(95)  # clears SIGNAL_LOSS; clear run restarts at 1
    assert types(engine) == [AlertType.LOW_SPO2]
    feed.send(95, n=9)
    assert types(engine) == []


def test_req5_signal_loss_only_for_silent_patient(engine, clock):
    a, b = Feeder(engine, clock, "P-001"), Feeder(engine, clock, "P-002")
    a.send(97)
    for _ in range(35):
        b.send(97)
    engine.check_signal_loss()
    assert types(engine, "P-001") == [AlertType.SIGNAL_LOSS]
    assert types(engine, "P-002") == []
