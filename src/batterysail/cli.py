"""BatterySail command-line interface.

    batterysail status            battery + current ceiling (no root)
    batterysail probe             read-only SMC transport self-test
    batterysail limit 80          set the charge limit in the config
    batterysail sail 5            set the sailing range
    batterysail discharge 60      stop charging until the battery falls to 60
    batterysail discharge off     clear a discharge target
    batterysail on | off          enable / disable (off restores 100)
    sudo batterysail restore      one-shot: write BCLM back to 100, now

Config edits are picked up by the daemon on its next poll. The config
path defaults to /etc/batterysail.json; override with --config or the
BATTERYSAIL_CONFIG environment variable (handy for dev runs).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .battery import read_battery

DEFAULT_CONFIG = "/etc/batterysail.json"


def _config_path(args) -> Path:
    return Path(args.config or os.environ.get("BATTERYSAIL_CONFIG", DEFAULT_CONFIG))


def _load_config_dict(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_config_dict(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2) + "\n")
    except PermissionError:
        raise SystemExit(f"cannot write {path} — try: sudo batterysail ...")
    print(f"config updated: {path}")


def cmd_status(args) -> int:
    battery = read_battery()
    print(f"Charge:        {battery.percent}%")
    print(f"Charging:      {battery.is_charging}")
    print(f"AC connected:  {battery.external_connected}")
    print(f"Fully charged: {battery.fully_charged}")
    if battery.temperature_c is not None:
        print(f"Temperature:   {battery.temperature_c:.1f} C (verify calibration!)")
    if battery.cycle_count is not None:
        print(f"Cycle count:   {battery.cycle_count}")
    try:
        from .smc import SMC, IntelChargeControl

        with SMC() as smc:
            ceiling = IntelChargeControl(smc).get_ceiling()
        print(f"SMC ceiling (BCLM): {ceiling if ceiling is not None else 'not supported'}")
    except Exception as exc:
        print(f"SMC ceiling (BCLM): unreadable ({exc})")
    state = _config_path(args).with_name("batterysail-state.json")
    if state.exists():
        print(f"Daemon state:  {state.read_text().strip()}")
    return 0


def cmd_probe(args) -> int:  # noqa: ARG001
    """Step-by-step read-only diagnostic: every check reports on its
    own line, so one run shows exactly which SMC operations work."""
    from .smc import SMC

    print(f"BatterySail SMC probe (read-only), running as uid {os.geteuid()}")

    def check(label, fn):
        try:
            detail = fn()
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            return None
        print(f"  OK    {label}: {detail}")
        return detail

    def fmt_info(info) -> str:
        size, type_, attrs = info
        return f"{size} byte(s), type {type_!r}, attributes {attrs:#04x}"

    with SMC() as smc:
        check("key_info BCLM", lambda: fmt_info(smc.key_info("BCLM")))
        bclm = check("read BCLM", lambda: f"{smc.read_key('BCLM')[0]}%")
        check("read #KEY", lambda: f"{smc.key_count()} keys")
        check("read TC0P (CPU temp sensor, control test)",
              lambda: smc.read_key("TC0P").hex())

    if bclm is None and os.geteuid() != 0:
        print("\nReads failed unprivileged. The daemon runs as root, so also try:")
        print("  sudo env PYTHONPATH=$PWD/src python3 -m batterysail.cli probe")
    return 0 if bclm is not None else 1


def cmd_restore(args) -> int:  # noqa: ARG001
    if os.geteuid() != 0:
        raise SystemExit("restore writes to the SMC — run it with sudo")
    from .smc import SMC, IntelChargeControl

    with SMC() as smc:
        IntelChargeControl(smc).set_ceiling(100)
    print("BCLM restored to 100%")
    return 0


def _edit_config(args, mutate) -> int:
    path = _config_path(args)
    data = _load_config_dict(path)
    mutate(data)
    _save_config_dict(path, data)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="batterysail")
    parser.add_argument("--config", help="path to batterysail config JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("probe").set_defaults(func=cmd_probe)
    sub.add_parser("restore").set_defaults(func=cmd_restore)

    p_limit = sub.add_parser("limit")
    p_limit.add_argument("percent", type=int)
    p_limit.set_defaults(func=lambda a: _edit_config(
        a, lambda d: d.__setitem__("charge_limit", a.percent)))

    p_sail = sub.add_parser("sail")
    p_sail.add_argument("percent", type=int)
    p_sail.set_defaults(func=lambda a: _edit_config(
        a, lambda d: d.__setitem__("sailing_range", a.percent)))

    p_dis = sub.add_parser("discharge")
    p_dis.add_argument("target", help="a percentage, or 'off'")
    p_dis.set_defaults(func=lambda a: _edit_config(a, lambda d: d.__setitem__(
        "discharge_below", None if a.target == "off" else int(a.target))))

    sub.add_parser("on").set_defaults(func=lambda a: _edit_config(
        a, lambda d: d.__setitem__("enabled", True)))
    sub.add_parser("off").set_defaults(func=lambda a: _edit_config(
        a, lambda d: d.__setitem__("enabled", False)))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
