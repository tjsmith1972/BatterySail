# BatterySail

Charge limiting with sailing mode for **Intel MacBooks** — a from-scratch,
open reimplementation of the ideas behind AlDente Pro, in pure Python
(standard library only).

Lithium batteries age fastest when they sit at 100% charge, which is
exactly where a mostly-plugged-in laptop lives. BatterySail parks the
battery in a healthy band (default 75–80%) and lets it *sail* inside
that band instead of micro-charging at the ceiling.

## How it works

There is no public macOS API for charge control. Like AlDente, BatterySail
talks to the **SMC** (System Management Controller):

- On Intel MacBooks the charge ceiling is the SMC key **BCLM**
  ("Battery Charge Level Max", one byte, percent). The SMC itself stops
  charging at that level — no polling needed for the basic limit, and it
  persists across reboots until changed.
- Battery state (percent, temperature, charging, cycle count) is read
  from IOKit's `AppleSmartBattery` entry by parsing `ioreg -a` output.
- A root **daemon** (LaunchDaemon) polls every 30 s and runs a small
  state machine (`controller.py`): charge limit, sailing hysteresis,
  heat protection, discharge target, and periodic calibration. It only
  writes to the SMC when the ceiling actually changes.
- A **CLI** edits the JSON config; the daemon picks changes up on its
  next poll.

Fail-safe by design: stopping the daemon restores the ceiling to 100,
and `batterysail restore` (or `scripts/uninstall.sh`) does the same
manually at any time. A crashed or removed BatterySail can never leave
the machine in a weird state — worst case, BCLM sits at some value
between 50 and 100 until you reset it.

## Safety first: probe before you write

SMC key availability varies by model. **Do not install the daemon until
the probe passes:**

```bash
cd ~/repos/BatterySail
PYTHONPATH=src python3 -m batterysail.cli status   # battery read via ioreg
PYTHONPATH=src python3 -m batterysail.cli probe    # read-only SMC checks
```

`probe` verifies the SMC transport (reads the key count via `#KEY`) and
whether this machine exposes `BCLM`. If BCLM is absent, charge limiting
via this mechanism is not possible on that model — stop there.

Also verify the temperature calibration once: compare `status` output
against coconutBattery or Stats. `battery.py` assumes the
`AppleSmartBattery` Temperature value is in 0.01 °C units; if your
machine disagrees, the heat rules need the corrected scale before they
can be trusted.

A good first live test is a **dry run** — the full state machine, with
intended SMC writes only logged:

```bash
cp config.example.json config.json
PYTHONPATH=src python3 -m batterysail.daemon --config ./config.json --dry-run
```

## Install (as a LaunchDaemon)

```bash
sudo bash scripts/install.sh     # copies to /usr/local/lib, seeds /etc/batterysail.json
tail -f /var/log/batterysail.log
```

## Usage

```bash
batterysail status            # charge, temp, cycles, current BCLM ceiling
batterysail limit 80          # charge limit (%)
batterysail sail 5            # sailing range: drift 80 -> 75 before recharging
batterysail discharge 60      # stop charging until the battery falls to 60
batterysail discharge off
batterysail off               # disable (daemon restores ceiling to 100)
batterysail on
sudo batterysail restore      # one-shot: BCLM back to 100, immediately
```

(For dev runs without installing: prefix with
`PYTHONPATH=src python3 -m batterysail.cli --config ./config.json`.)

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The controller is pure logic and fully tested with a fake charge
control — no hardware involved.

## Known limits / roadmap

- **Intel only, for now.** Apple Silicon uses a different SMC key set
  (and macOS 26.4+ ships its own native charge limit worth integrating
  with rather than fighting). The controller and battery reader are
  platform-neutral; only `smc.py`'s charge control is Intel-specific.
- **Sailing uses natural drift.** BCLM can stop charging, but it cannot
  force the Mac to run off its battery while plugged in, so the sail
  down happens at the speed of the battery's natural micro-drain
  (hours to days). Actively forcing discharge needs the SMC
  charge-inhibit keys — that's the next investigation.
- **Not every Intel model has BCLM.** Probe first (see above).
- No GUI. A menu-bar front end over the same config/state files would
  be straightforward.

## Layout

```
src/batterysail/
    battery.py      AppleSmartBattery reader (ioreg -> plistlib)
    smc.py          ctypes/IOKit SMC transport + Intel BCLM control
    controller.py   the state machine (limit, sailing, heat, calibration)
    daemon.py       root polling daemon (LaunchDaemon entry point)
    cli.py          batterysail command
launchd/            LaunchDaemon plist
scripts/            install.sh / uninstall.sh
tests/              controller unit tests
```
