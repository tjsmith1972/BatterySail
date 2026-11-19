"""The charge-control state machine.

Pure logic, no I/O: the daemon feeds it BatteryState snapshots and it
decides what the SMC charge ceiling should be, calling the injected
charge-control object only when the ceiling actually changes (SMC
writes are cheap, but pointless writes are still pointless).

How the AlDente Pro feature set maps onto a BCLM ceiling:

- Charge limit:   ceiling = charge_limit.
- Sailing mode:   hysteresis. At/above the limit the ceiling drops to
                  (limit - sailing_range); it is only restored to the
                  limit once the battery drifts down to the bottom of
                  the band. While plugged in the battery micro-drains
                  slowly (it buffers power spikes), so the level sails
                  down over hours/days instead of micro-charging.
                  NOTE: actively *forcing* a discharge needs the SMC
                  charge-inhibit keys (roadmap); v1 sailing works with
                  the natural drift only.
- Heat protection: at/above heat_pause_celsius the ceiling drops to the
                  current percentage (charging stops, Mac runs on AC);
                  it resumes when the battery cools to heat_resume.
- Discharge:      with discharge_below set, the ceiling is pinned there
                  so charging stops until the level falls to it.
- Calibration:    every N days the ceiling goes to 100 until the
                  battery reports fully charged, keeping the
                  percentage gauge honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from .battery import BatteryState


class ChargeControl(Protocol):
    def get_ceiling(self) -> int | None: ...
    def set_ceiling(self, percent: int) -> None: ...


@dataclass
class Config:
    enabled: bool = True
    charge_limit: int = 80
    sailing_range: int = 5
    heat_pause_celsius: float = 38.0
    heat_resume_celsius: float = 34.0
    poll_seconds: int = 30
    discharge_below: int | None = None
    calibration_enabled: bool = False
    calibration_every_days: int = 30

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        cal = data.get("calibration") or {}
        return cls(
            enabled=data.get("enabled", True),
            charge_limit=data.get("charge_limit", 80),
            sailing_range=data.get("sailing_range", 5),
            heat_pause_celsius=data.get("heat_pause_celsius", 38.0),
            heat_resume_celsius=data.get("heat_resume_celsius", 34.0),
            poll_seconds=data.get("poll_seconds", 30),
            discharge_below=data.get("discharge_below"),
            calibration_enabled=cal.get("enabled", False),
            calibration_every_days=cal.get("every_days", 30),
        )


@dataclass
class Controller:
    config: Config
    control: ChargeControl
    _ceiling: int | None = field(default=None, init=False)
    _heat_paused: bool = field(default=False, init=False)
    _calibrating: bool = field(default=False, init=False)
    _last_calibration: datetime | None = field(default=None, init=False)

    def _apply(self, ceiling: int, actions: list[str], why: str) -> None:
        ceiling = max(50, min(100, ceiling))
        if ceiling != self._ceiling:
            self.control.set_ceiling(ceiling)
            self._ceiling = ceiling
            actions.append(f"ceiling -> {ceiling}% ({why})")

    def tick(self, battery: BatteryState, now: datetime) -> list[str]:
        """Advance the state machine once. Returns log-worthy actions."""
        actions: list[str] = []
        cfg = self.config

        if not cfg.enabled:
            self._apply(100, actions, "disabled, restoring full charge")
            return actions

        # --- calibration ------------------------------------------------
        if cfg.calibration_enabled and not self._calibrating:
            due = (
                self._last_calibration is None
                or now - self._last_calibration
                >= timedelta(days=cfg.calibration_every_days)
            )
            if due and battery.external_connected:
                self._calibrating = True
                actions.append("calibration started")
        if self._calibrating:
            if battery.fully_charged or battery.percent >= 100:
                self._calibrating = False
                self._last_calibration = now
                actions.append("calibration complete")
            else:
                self._apply(100, actions, "calibrating")
                return actions

        # --- heat protection ---------------------------------------------
        temp = battery.temperature_c
        if temp is not None:
            if not self._heat_paused and temp >= cfg.heat_pause_celsius:
                self._heat_paused = True
                actions.append(f"heat pause at {temp:.1f} C")
            elif self._heat_paused and temp <= cfg.heat_resume_celsius:
                self._heat_paused = False
                actions.append(f"heat resume at {temp:.1f} C")
        if self._heat_paused:
            hold = min(battery.percent, cfg.charge_limit)
            self._apply(hold, actions, "heat protection hold")
            return actions

        # --- manual discharge --------------------------------------------
        if cfg.discharge_below is not None and battery.percent > cfg.discharge_below:
            self._apply(cfg.discharge_below, actions, "discharge target")
            return actions

        # --- sailing band --------------------------------------------------
        top = cfg.charge_limit
        bottom = max(50, top - cfg.sailing_range)
        if battery.percent >= top:
            self._apply(bottom, actions, "top of band, sailing down")
        elif battery.percent <= bottom:
            self._apply(top, actions, "bottom of band, charging to limit")
        elif self._ceiling is None:
            self._apply(top, actions, "initial ceiling")
        return actions
