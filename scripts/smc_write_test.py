#!/usr/bin/env python3
"""Diagnostic: identify the SMC WriteKey command byte, safely.

Reads now work (ReadKey=5, GetKeyInfo=9 — see smc.py), but the write
byte is unconfirmed: the scan's candidate 6 answered kIOReturnNoDevice
to malformed size-0 requests, and 7/8/11 are silent no-ops. A no-op
and a successful same-value write look identical, so this test uses
BCLM itself and a CHANGED value as the fingerprint:

For each candidate byte, in order:
  1. read BCLM's current value,
  2. write current-1 (or current+1 if current is already 50) with a
     fully populated keyInfo (size 1, type 'ui8 ', attrs as reported),
  3. read BCLM back.
If the value flipped, that byte is WriteKey — the script immediately
writes the original value back with the same byte, verifies the
restore, and stops. BCLM spends at most a moment one point off its
original value (e.g. 99 instead of 100), which has no practical
effect on charging.

If no candidate flips the value unprivileged, re-run with sudo —
the daemon runs as root, so a root-only write path is acceptable:
    sudo env PYTHONPATH=$PWD/src python3 scripts/smc_write_test.py

Run from the repo root:
    PYTHONPATH=src python3 scripts/smc_write_test.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from batterysail.smc import SMC, SMCKeyData, _fourcc

CANDIDATES = (6, 7, 8, 11, 10, 12)


def write_attempt(smc: SMC, cmd: int, value: int) -> str:
    size, type_, attrs = smc.key_info("BCLM")
    data = SMCKeyData()
    data.key = _fourcc("BCLM")
    data.data8 = cmd
    data.key_info.data_size = size
    from batterysail.smc import _fourcc as fc
    data.key_info.data_type = fc(type_)
    data.key_info.data_attributes = attrs
    data.bytes[0] = value
    out = smc.call_raw(data)
    return f"result={out.result:#04x}"


def read_bclm(smc: SMC) -> int:
    return smc.read_key("BCLM")[0]


def main() -> int:
    with SMC() as smc:
        original = read_bclm(smc)
        print(f"BCLM current value: {original}%")
        test_value = original - 1 if original > 50 else original + 1
        for cmd in CANDIDATES:
            try:
                outcome = write_attempt(smc, cmd, test_value)
            except Exception as exc:
                print(f"  data8={cmd:2d}: IO error: {exc}")
                continue
            now = read_bclm(smc)
            print(f"  data8={cmd:2d}: write -> {outcome}; BCLM now {now}%")
            if now == test_value:
                print(f"  ** data8={cmd} is WriteKey **")
                outcome = write_attempt(smc, cmd, original)
                restored = read_bclm(smc)
                print(f"  restored: write -> {outcome}; BCLM now {restored}%")
                if restored != original:
                    print("  !! RESTORE FAILED — run: "
                          "sudo env PYTHONPATH=$PWD/src python3 "
                          "-m batterysail.cli restore")
                    return 1
                return 0
        print("No candidate flipped BCLM. If you ran unprivileged, "
              "retry with sudo (see docstring).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
