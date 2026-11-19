"""Minimal SMC (System Management Controller) client via ctypes/IOKit.

The SMC is how macOS-level tools control charging: there is no public
API for it. This module implements the well-known AppleSMC user-client
protocol (an 80-byte struct exchanged with IOConnectCallStructMethod)
using only the standard library.

Reading keys works unprivileged; WRITING keys requires root, which is
why BatterySail's daemon runs as a LaunchDaemon.

Run `batterysail probe` before enabling anything: it performs read-only
checks (key count via #KEY, BCLM presence) so you can confirm the
transport works on your machine before a single write happens.
"""

from __future__ import annotations

import ctypes

# --- IOKit plumbing -------------------------------------------------------
#
# Every function signature is declared explicitly. This is not optional
# decoration: without a restype, ctypes assumes C int and TRUNCATES
# 64-bit return values. IOServiceMatching returns a pointer (a CF
# dictionary ref); truncated to 32 bits it becomes a garbage pointer
# and the next call segfaults the process. (Learned the hard way:
# first live run, 2026-11-19 — battery reads via ioreg were fine, and
# the process died the moment it touched the SMC.)

_iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
_libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")

_iokit.IOServiceMatching.restype = ctypes.c_void_p
_iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]

_iokit.IOServiceGetMatchingService.restype = ctypes.c_uint32
_iokit.IOServiceGetMatchingService.argtypes = [ctypes.c_uint32, ctypes.c_void_p]

_iokit.IOServiceOpen.restype = ctypes.c_uint32
_iokit.IOServiceOpen.argtypes = [
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
]

_iokit.IOServiceClose.restype = ctypes.c_uint32
_iokit.IOServiceClose.argtypes = [ctypes.c_uint32]

_iokit.IOObjectRelease.restype = ctypes.c_uint32
_iokit.IOObjectRelease.argtypes = [ctypes.c_uint32]

_iokit.IOConnectCallStructMethod.restype = ctypes.c_uint32
_iokit.IOConnectCallStructMethod.argtypes = [
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_size_t),
]

# mach_task_self() is a libSystem call (and `mach_task_self_` the
# underlying port global); it is not an IOKit export.
try:
    _MACH_TASK_SELF = ctypes.c_uint32.in_dll(_libsystem, "mach_task_self_").value
except ValueError:
    _libsystem.mach_task_self.restype = ctypes.c_uint32
    _libsystem.mach_task_self.argtypes = []
    _MACH_TASK_SELF = _libsystem.mach_task_self()

K_IO_MAIN_PORT_DEFAULT = 0  # kIOMainPortDefault / kIOMasterPortDefault
K_SMC_HANDLE_YPC_EVENT = 2  # selector for IOConnectCallStructMethod

# data8 command selectors — FINGERPRINTED on the 2020 Intel Air
# (macOS 15) with scripts/smc_scan.py, 2026-11-19. They differ from
# the commonly published VirtualSMC values, which put GetKeyInfo at
# 8: with 8, this SMC returns success and an all-zero keyInfo, the
# size comes back 0, and every read is then refused with result
# 0x89 (a read needs the key's real size). The full observed map:
#   1-4, 10: rejected at the IO level, kIOReturnNotPrivileged
#   5:  ReadKey — confirmed (TC0P payload decodes as a temperature)
#   6:  WriteKey — confirmed by scripts/smc_write_test.py (flipped
#       BCLM 100 -> 99 -> restored). ROOT ONLY: unprivileged write
#       attempts are rejected at the IO level with the misleading
#       kIOReturnNoDevice (0xe00002c1). Reads are unprivileged.
#       This is why the daemon runs as root and the CLI only reads.
#   7, 8, 11: success, all-zero response (no-ops for our purposes)
#   9:  GetKeyInfo — confirmed (TC0P: 2 bytes 'sp78', attrs 0xc0;
#       BCLM: 1 byte 'ui8 ', attrs 0xd0 — the extra 0x10 bit on BCLM
#       is consistent with it being the writable one)
#   12: result 0x84 (key not found) — consistent with GetKeyByIndex
SMC_CMD_READ_KEY = 5
SMC_CMD_WRITE_KEY = 6  # confirmed; requires root (see map above)
SMC_CMD_GET_KEY_BY_INDEX = 12
SMC_CMD_GET_KEY_INFO = 9


class SMCError(RuntimeError):
    pass


def _fourcc(text: str) -> int:
    if len(text) != 4:
        raise ValueError(f"SMC keys are 4 characters, got {text!r}")
    return int.from_bytes(text.encode("ascii"), "big")


def _fourcc_to_str(value: int) -> str:
    return value.to_bytes(4, "big").decode("ascii", errors="replace")


# --- The 80-byte SMCKeyData struct (layout as in the classic smc tools) ---


class _SMCVersion(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_uint8),
        ("minor", ctypes.c_uint8),
        ("build", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8),
        ("release", ctypes.c_uint16),
    ]


class _SMCPLimitData(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint16),
        ("length", ctypes.c_uint16),
        ("cpu_plimit", ctypes.c_uint32),
        ("gpu_plimit", ctypes.c_uint32),
        ("mem_plimit", ctypes.c_uint32),
    ]


class _SMCKeyInfoData(ctypes.Structure):
    _fields_ = [
        ("data_size", ctypes.c_uint32),
        ("data_type", ctypes.c_uint32),
        ("data_attributes", ctypes.c_uint8),
    ]


class SMCKeyData(ctypes.Structure):
    _fields_ = [
        ("key", ctypes.c_uint32),
        ("version", _SMCVersion),
        ("plimit", _SMCPLimitData),
        ("key_info", _SMCKeyInfoData),
        ("result", ctypes.c_uint8),
        ("status", ctypes.c_uint8),
        ("data8", ctypes.c_uint8),
        ("data32", ctypes.c_uint32),
        ("bytes", ctypes.c_uint8 * 32),
    ]


assert ctypes.sizeof(SMCKeyData) == 80, ctypes.sizeof(SMCKeyData)


class SMC:
    """A connection to the AppleSMC service. Use as a context manager."""

    def __init__(self) -> None:
        self._conn = ctypes.c_uint32(0)
        matching = _iokit.IOServiceMatching(b"AppleSMC")
        if not matching:
            raise SMCError("IOServiceMatching(AppleSMC) returned nothing")
        service = _iokit.IOServiceGetMatchingService(
            K_IO_MAIN_PORT_DEFAULT, matching
        )
        if not service:
            raise SMCError("AppleSMC service not found")
        result = _iokit.IOServiceOpen(
            service, _MACH_TASK_SELF, 0, ctypes.byref(self._conn)
        )
        _iokit.IOObjectRelease(service)
        if result != 0:
            raise SMCError(f"IOServiceOpen(AppleSMC) failed: {result:#x}")

    def close(self) -> None:
        if self._conn:
            _iokit.IOServiceClose(self._conn)
            self._conn = ctypes.c_uint32(0)

    def __enter__(self) -> "SMC":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low level ---------------------------------------------------------

    def call_raw(self, data: SMCKeyData) -> SMCKeyData:
        """Exchange one struct with the SMC and return the raw response.

        Never raises on the SMC result byte (still raises SMCError if
        the IO call itself fails). Diagnostic code — scripts/smc_scan.py
        — uses this to inspect responses that _call would turn into an
        exception, including the response payload of a failed call.
        """
        output = SMCKeyData()
        out_size = ctypes.c_size_t(ctypes.sizeof(SMCKeyData))
        result = _iokit.IOConnectCallStructMethod(
            self._conn,
            K_SMC_HANDLE_YPC_EVENT,
            ctypes.byref(data),
            ctypes.sizeof(SMCKeyData),
            ctypes.byref(output),
            ctypes.byref(out_size),
        )
        if result != 0:
            raise SMCError(f"IOConnectCallStructMethod failed: {result:#x}")
        return output

    def _call(self, data: SMCKeyData) -> SMCKeyData:
        output = self.call_raw(data)
        if output.result != 0:
            raise SMCError(f"SMC returned result {output.result:#x}")
        return output

    # -- public API --------------------------------------------------------

    def key_info(self, key: str) -> tuple[int, str, int]:
        """Return (size_in_bytes, type_fourcc, attributes) for a key.

        Raises SMCError if the key is absent.
        """
        data = SMCKeyData()
        data.key = _fourcc(key)
        data.data8 = SMC_CMD_GET_KEY_INFO
        out = self._call(data)
        info = out.key_info
        return info.data_size, _fourcc_to_str(info.data_type), info.data_attributes

    def _fill_key_info(self, data: SMCKeyData, key: str) -> int:
        """Populate data.key_info from a GetKeyInfo call; return the size.

        Read/write calls carry the FULL key info (size, type and
        attributes), exactly as GetKeyInfo reported it — not just the
        size. Some SMC firmware validates the type on read/write too,
        and passing back what the key itself declared is the
        conservative choice either way.
        """
        size, type_, attrs = self.key_info(key)
        data.key_info.data_size = size
        data.key_info.data_type = _fourcc(type_)
        data.key_info.data_attributes = attrs
        return size

    def has_key(self, key: str) -> bool:
        try:
            self.key_info(key)
            return True
        except SMCError:
            return False

    def read_key(self, key: str) -> bytes:
        data = SMCKeyData()
        data.key = _fourcc(key)
        size = self._fill_key_info(data, key)
        data.data8 = SMC_CMD_READ_KEY
        out = self._call(data)
        return bytes(out.bytes)[:size]

    def write_key(self, key: str, value: bytes) -> None:
        size, _, _ = self.key_info(key)
        if len(value) != size:
            raise SMCError(
                f"key {key} expects {size} bytes, got {len(value)}"
            )
        data = SMCKeyData()
        data.key = _fourcc(key)
        self._fill_key_info(data, key)
        data.data8 = SMC_CMD_WRITE_KEY
        for i, byte in enumerate(value):
            data.bytes[i] = byte
        self._call(data)

    def key_count(self) -> int:
        """Total number of SMC keys (#KEY) — a good transport smoke test."""
        raw = self.read_key("#KEY")
        return int.from_bytes(raw, "big")


# --- Intel charge control ---------------------------------------------------
#
# On Intel MacBooks the charge ceiling lives in the SMC key BCLM
# ("Battery Charge Level Max", one unsigned byte, percent). The SMC
# itself stops charging at that level, so the basic limit needs no
# polling and survives reboots until changed. AlDente uses the same key
# on Intel. Not every Intel model exposes BCLM — probe first.

KEY_BCLM = "BCLM"


class IntelChargeControl:
    """Charge-ceiling control for Intel Macs, via BCLM."""

    def __init__(self, smc: SMC) -> None:
        self._smc = smc

    def available(self) -> bool:
        return self._smc.has_key(KEY_BCLM)

    def get_ceiling(self) -> int | None:
        if not self.available():
            return None
        return self._smc.read_key(KEY_BCLM)[0]

    def set_ceiling(self, percent: int) -> None:
        if not 50 <= percent <= 100:
            raise ValueError("BCLM ceiling must be between 50 and 100")
        self._smc.write_key(KEY_BCLM, bytes([percent]))
        actual = self.get_ceiling()
        if actual != percent:
            raise SMCError(
                f"BCLM write did not stick: wanted {percent}, read {actual}"
            )
