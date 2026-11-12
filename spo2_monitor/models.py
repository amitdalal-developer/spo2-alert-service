"""Data models for SpO2 readings and alerts."""
from enum import Enum

from pydantic import BaseModel, Field
from typing_extensions import Literal


class Reading(BaseModel):
    """A single SpO2 sample, e.g.
    {"patient_id": "P-001", "ts": 1730480400000, "spo2": 88, "quality": "good"}
    """

    patient_id: str = Field(min_length=1)
    ts: int = Field(description="Device timestamp, epoch milliseconds")
    spo2: float = Field(ge=0, le=100)
    quality: Literal["good", "poor"]


class AlertType(str, Enum):
    LOW_SPO2 = "LOW_SPO2"
    SIGNAL_LOSS = "SIGNAL_LOSS"


class Alert(BaseModel):
    type: AlertType
    start_time: int = Field(description="Epoch milliseconds")
