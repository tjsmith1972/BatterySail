"""Read battery state from IOKit's AppleSmartBattery entry.

Zero-dependency approach: `ioreg -a` dumps the entry as an XML plist,
which we parse with plistlib. Works unprivileged on Intel and Apple
silicon Macs.
"""

from __future__ import annotations

import plistlib
import subprocess
from dataclasses import dataclass, field


@dataclass
class BatteryState:
    percent: int
    is_charging: bool
    external_connected: bool
    fully_charged: bool
    temperature_c: float | None
    cycle_count: int | None
    voltage_mv: int | None
    amperage_ma: int | None  # signed; negative while discharging
    raw: dict = field(repr=False, default_factory=dict)


def _signed64(value: int) -> int:
    """ioreg sometimes reports Amperage as an unsigned 64-bit value."""
    if value > 2**63:
        return value - 2**64
    return value


def read_battery() -> BatteryState:
    out = subprocess.run(
        ["ioreg", "-a", "-r", "-c", "AppleSmartBattery"],
        capture_output=True,
        check=True,
    ).stdout
    entries = plistlib.loads(out)
    if not entries:
        raise RuntimeError("AppleSmartBattery not found in the IORegistry")
    props = entries[0]

    current = props.get("CurrentCapacity")
    maximum = props.get("MaxCapacity")
    if current is None or maximum in (None, 0):
        raise RuntimeError("AppleSmartBattery entry has no capacity values")
    # On modern macOS CurrentCapacity is already a percentage (MaxCapacity
    # == 100); compute it properly for the general case anyway.
    percent = current if maximum == 100 else round(100 * current / maximum)

    temp_raw = props.get("Temperature")
    # AppleSmartBattery reports Temperature in 0.01 degC units on Intel
    # (e.g. 3045 -> 30.45 C). VERIFY against a known-good monitor
    # (coconutBattery, Stats) on first run before trusting heat rules.
    temperature_c = temp_raw / 100.0 if temp_raw is not None else None

    amperage = props.get("Amperage")
    if amperage is not None:
        amperage = _signed64(amperage)

    return BatteryState(
        percent=percent,
        is_charging=bool(props.get("IsCharging", False)),
        external_connected=bool(props.get("ExternalConnected", False)),
        fully_charged=bool(props.get("FullyCharged", False)),
        temperature_c=temperature_c,
        cycle_count=props.get("CycleCount"),
        voltage_mv=props.get("Voltage"),
        amperage_ma=amperage,
        raw=props,
    )
