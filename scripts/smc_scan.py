#!/usr/bin/env python3
"""Diagnostic: fingerprint the SMC data8 command bytes on this machine.

Why this exists: the published command bytes (VirtualSMC: read=5,
write=6, by-index=7, get-key-info=8) do not behave as documented on
the 2020 Intel Air under macOS 15 — the get-key-info byte returns
success with an all-zero keyInfo, and the read byte is refused with
result 0x89, even as root. Rather than guess, this script tries every
command byte 1..12 against known keys and prints the RAW response
struct for each attempt, so the real commands identify themselves:

- GetKeyInfo is the byte that answers for TC0P with size=2 and
  type 'sp78' (and for BCLM with size=1, type 'ui8 ').
- ReadKey is the byte that then returns TC0P's two payload bytes
  with result 0 — an sp78 temperature, first byte roughly 25-70.

Some command bytes are rejected at the IO level (e.g. data8=1 came
back kIOReturnNotPrivileged, 0xe00002c2, unprivileged). Those are
recorded as table rows and the scan continues.

Safety: the read scan runs against TC0P, a read-only sensor key,
with a zeroed payload — if some byte turns out to be WriteKey, the
firmware refuses writes to sensor keys. BCLM is only ever queried
for its info, never written, by this script.

Run from the repo root:
    PYTHONPATH=src python3 scripts/smc_scan.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from batterysail.smc import SMC, SMCKeyData, _fourcc, _fourcc_to_str


def attempt(smc: SMC, key: str, cmd: int, data_size: int = 0) -> SMCKeyData:
    data = SMCKeyData()
    data.key = _fourcc(key)
    data.data8 = cmd
    data.key_info.data_size = data_size
    return smc.call_raw(data)


def describe(out: SMCKeyData) -> str:
    info = out.key_info
    return (
        f"result={out.result:#04x} status={out.status:#04x} "
        f"size={info.data_size} type={_fourcc_to_str(info.data_type)!r} "
        f"attrs={info.data_attributes:#04x} "
        f"bytes={bytes(out.bytes)[:8].hex()}"
    )


def row(smc: SMC, key: str, cmd: int, data_size: int = 0) -> str:
    try:
        return describe(attempt(smc, key, cmd, data_size))
    except Exception as exc:  # IO-level rejection is data too
        return f"IO error: {exc}"


def main() -> int:
    with SMC() as smc:
        for key, want_size, want_type in (("TC0P", 2, "sp78"), ("BCLM", 1, "ui8 ")):
            print(f"--- info scan, key {key} "
                  f"(expect size={want_size}, type={want_type!r}) ---")
            for cmd in range(1, 13):
                print(f"  data8={cmd:2d}: {row(smc, key, cmd)}")
        print("--- read scan, key TC0P (size=2, zeroed payload) ---")
        for cmd in range(1, 13):
            print(f"  data8={cmd:2d}: {row(smc, 'TC0P', cmd, data_size=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
