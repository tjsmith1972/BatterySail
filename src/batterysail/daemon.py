"""BatterySail daemon: polls the battery and drives the controller.

Runs as root (LaunchDaemon) because SMC writes are privileged. Reads
its JSON config on every poll, so CLI edits take effect without a
restart, and publishes a state.json next to the config for `status`.

Fail-safe: on SIGTERM/SIGINT the ceiling is restored to 100 before
exit, and BCLM itself is just a number in the SMC — a reboot or a
`batterysail restore` always returns the machine to stock behavior.

Usage:
    python3 -m batterysail.daemon --config /etc/batterysail.json
    python3 -m batterysail.daemon --config ./config.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .battery import read_battery
from .controller import Config, Controller
from .smc import SMC, IntelChargeControl

log = logging.getLogger("batterysail")


class DryRunControl:
    """Charge control that logs intended writes instead of doing them."""

    def __init__(self) -> None:
        self._ceiling: int | None = None

    def get_ceiling(self) -> int | None:
        return self._ceiling

    def set_ceiling(self, percent: int) -> None:
        log.info("DRY RUN: would set ceiling to %d%%", percent)
        self._ceiling = percent


def load_config(path: Path) -> Config:
    try:
        return Config.from_dict(json.loads(path.read_text()))
    except FileNotFoundError:
        log.warning("no config at %s, using defaults", path)
        return Config()
    except (ValueError, OSError) as exc:
        log.error("bad config (%s), using defaults", exc)
        return Config()


def current_mode(controller: Controller, battery) -> str:
    """One-word mode for the state file; the menu bar app renders it."""
    cfg = controller.config
    if not cfg.enabled:
        return "off"
    if controller._calibrating:
        return "calibrating"
    if controller._heat_paused:
        return "heat_pause"
    if cfg.discharge_below is not None and battery.percent > cfg.discharge_below:
        return "discharging"
    if not battery.external_connected:
        return "on_battery"
    if controller._ceiling is not None and controller._ceiling < cfg.charge_limit:
        return "sailing"
    if battery.is_charging:
        return "charging"
    if battery.percent >= cfg.charge_limit:
        return "at_limit"
    return "holding"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="batterysail-daemon")
    parser.add_argument("--config", default="/etc/batterysail.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config_path = Path(args.config)
    state_path = config_path.with_name("batterysail-state.json")

    if os.geteuid() != 0 and not args.dry_run:
        log.warning("not running as root: SMC writes will fail")

    smc = None if args.dry_run else SMC()
    control = DryRunControl() if args.dry_run else IntelChargeControl(smc)
    if not args.dry_run and not control.available():
        log.error("BCLM key not present on this machine; nothing to control")
        return 1

    controller = Controller(load_config(config_path), control)
    stopping = False

    def _stop(signum, frame):  # noqa: ARG001
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info("batterysail daemon started (dry_run=%s)", args.dry_run)
    try:
        while not stopping:
            controller.config = load_config(config_path)
            try:
                battery = read_battery()
                actions = controller.tick(battery, datetime.now(timezone.utc))
                for action in actions:
                    log.info(action)
                state_path.write_text(json.dumps({
                    "percent": battery.percent,
                    "is_charging": battery.is_charging,
                    "external_connected": battery.external_connected,
                    "temperature_c": battery.temperature_c,
                    "cycle_count": battery.cycle_count,
                    "ceiling": controller._ceiling,
                    "mode": current_mode(controller, battery),
                    "enabled": controller.config.enabled,
                    "charge_limit": controller.config.charge_limit,
                    "sailing_range": controller.config.sailing_range,
                    "discharge_below": controller.config.discharge_below,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, indent=2))
            except Exception:  # keep the daemon alive through bad reads
                log.exception("poll failed")
            time.sleep(controller.config.poll_seconds)
    finally:
        try:
            control.set_ceiling(100)
            log.info("ceiling restored to 100 on shutdown")
        except Exception:
            log.exception("failed to restore ceiling on shutdown")
        if smc is not None:
            smc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
