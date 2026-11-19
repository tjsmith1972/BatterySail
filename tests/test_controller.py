"""Unit tests for the controller state machine (no hardware needed).

Run from the repo root:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from batterysail.battery import BatteryState
from batterysail.controller import Config, Controller

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


class FakeControl:
    def __init__(self):
        self.ceiling = None
        self.writes = []

    def get_ceiling(self):
        return self.ceiling

    def set_ceiling(self, percent):
        self.ceiling = percent
        self.writes.append(percent)


def battery(percent, temp=30.0, charging=True, external=True, full=False):
    return BatteryState(
        percent=percent,
        is_charging=charging,
        external_connected=external,
        fully_charged=full,
        temperature_c=temp,
        cycle_count=100,
        voltage_mv=12000,
        amperage_ma=0,
    )


def make(config=None):
    control = FakeControl()
    return Controller(config or Config(), control), control


class SailingTests(unittest.TestCase):
    def test_initial_ceiling_is_limit(self):
        ctl, control = make()
        ctl.tick(battery(60), NOW)
        self.assertEqual(control.ceiling, 80)

    def test_at_limit_ceiling_drops_to_band_bottom(self):
        ctl, control = make()
        ctl.tick(battery(60), NOW)          # ceiling 80
        ctl.tick(battery(80), NOW)          # reached the top
        self.assertEqual(control.ceiling, 75)

    def test_inside_band_no_writes(self):
        ctl, control = make()
        ctl.tick(battery(80), NOW)          # ceiling -> 75
        writes = len(control.writes)
        ctl.tick(battery(78), NOW)          # drifting inside the band
        ctl.tick(battery(76), NOW)
        self.assertEqual(len(control.writes), writes)
        self.assertEqual(control.ceiling, 75)

    def test_bottom_of_band_restores_limit(self):
        ctl, control = make()
        ctl.tick(battery(80), NOW)          # ceiling -> 75
        ctl.tick(battery(75), NOW)          # hit the bottom
        self.assertEqual(control.ceiling, 80)


class HeatTests(unittest.TestCase):
    def test_heat_pauses_at_current_percent(self):
        ctl, control = make()
        ctl.tick(battery(70, temp=39.0), NOW)
        self.assertEqual(control.ceiling, 70)

    def test_heat_resume_restores_band_logic(self):
        ctl, control = make()
        ctl.tick(battery(70, temp=39.0), NOW)   # paused, ceiling 70
        ctl.tick(battery(70, temp=33.0), NOW)   # cooled down
        self.assertEqual(control.ceiling, 80)


class ModeTests(unittest.TestCase):
    def test_disabled_restores_100(self):
        ctl, control = make(Config(enabled=False))
        ctl.tick(battery(55), NOW)
        self.assertEqual(control.ceiling, 100)

    def test_discharge_pins_ceiling_to_target(self):
        ctl, control = make(Config(discharge_below=60))
        ctl.tick(battery(85), NOW)
        self.assertEqual(control.ceiling, 60)
        ctl.tick(battery(60), NOW)  # target reached: normal band logic
        self.assertEqual(control.ceiling, 80)


if __name__ == "__main__":
    unittest.main()
