"""Alert engine: pure per-patient state machine, no I/O.

Rules (see Requirements.rtf and README):
  REQ-2  LOW_SPO2 raised when the last 10 good readings are all < 90.
  REQ-3  LOW_SPO2 cleared when the last 10 good readings are all >= 92.
  REQ-4  "poor" readings are skipped: they never count toward, reset or
         break a window, and never raise or clear an alert.
  REQ-5  SIGNAL_LOSS raised when no reading (of any quality) has arrived
         for more than 30 s; cleared only by the next good reading.
"""
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .clock import Clock, SystemClock
from .models import Alert, AlertType, Reading

LOW_THRESHOLD = 90  # spo2 < 90 counts toward LOW_SPO2
CLEAR_THRESHOLD = 92  # spo2 >= 92 counts toward clearing LOW_SPO2
WINDOW_SIZE = 10  # readings arrive at 1 Hz, so 10 readings ~= 10 s
SIGNAL_LOSS_TIMEOUT_MS = 30_000


@dataclass
class PatientState:
    last_arrival_ms: int
    low_run: int = 0
    low_run_start_ts: Optional[int] = None
    clear_run: int = 0
    active: Dict[AlertType, Alert] = field(default_factory=dict)

    def reset_runs(self) -> None:
        self.low_run = 0
        self.low_run_start_ts = None
        self.clear_run = 0


class AlertEngine:
    def __init__(self, clock: Optional[Clock] = None) -> None:
        self._clock = clock or SystemClock()
        self._patients: Dict[str, PatientState] = {}
        self._lock = threading.Lock()

    def process(self, reading: Reading) -> None:
        with self._lock:
            now = self._clock.now_ms()
            state = self._patients.get(reading.patient_id)
            if state is None:
                state = PatientState(last_arrival_ms=now)
                self._patients[reading.patient_id] = state
            # Any reading, including poor, proves the device is sending (REQ-5).
            state.last_arrival_ms = now

            if reading.quality == "poor":  # REQ-4
                return

            state.active.pop(AlertType.SIGNAL_LOSS, None)

            if reading.spo2 < LOW_THRESHOLD:
                if state.low_run == 0:
                    state.low_run_start_ts = reading.ts
                state.low_run += 1
                state.clear_run = 0
            elif reading.spo2 >= CLEAR_THRESHOLD:
                state.clear_run += 1
                state.low_run = 0
                state.low_run_start_ts = None
            else:  # 90 <= spo2 < 92 breaks both runs
                state.reset_runs()

            if state.low_run >= WINDOW_SIZE and AlertType.LOW_SPO2 not in state.active:
                assert state.low_run_start_ts is not None
                state.active[AlertType.LOW_SPO2] = Alert(
                    type=AlertType.LOW_SPO2, start_time=state.low_run_start_ts
                )
            if state.clear_run >= WINDOW_SIZE:
                state.active.pop(AlertType.LOW_SPO2, None)

    def check_signal_loss(self, now_ms: Optional[int] = None) -> List[str]:
        """Raise SIGNAL_LOSS for silent patients. Returns newly affected ids."""
        with self._lock:
            now = self._clock.now_ms() if now_ms is None else now_ms
            raised = []
            for pid, state in self._patients.items():
                if AlertType.SIGNAL_LOSS in state.active:
                    continue
                if now - state.last_arrival_ms > SIGNAL_LOSS_TIMEOUT_MS:
                    state.active[AlertType.SIGNAL_LOSS] = Alert(
                        type=AlertType.SIGNAL_LOSS, start_time=now
                    )
                    # The gap breaks continuity of any in-progress window.
                    state.reset_runs()
                    raised.append(pid)
            return raised

    def active_alerts(self, patient_id: str) -> Optional[List[Alert]]:
        """Active alerts for a patient, or None if the patient is unknown."""
        with self._lock:
            state = self._patients.get(patient_id)
            if state is None:
                return None
            return sorted(state.active.values(), key=lambda a: a.start_time)
