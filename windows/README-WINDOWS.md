# BatterySail for Windows

The Windows counterpart of the Mac BatterySail. On the Dell Pro
Precision 5 16 there is no SMC; instead the BIOS itself offers a
custom charge band (CustomChargeStart / CustomChargeStop) through
Dell's WMI BIOS attribute interface. This app sets that band and
shows the state in the system tray. Once set, the firmware enforces
the band on its own — start charging at the bottom, stop at the
top — so there is no daemon to keep alive; the tray app is both
the controller and the display.

Proven on this machine (BIOS 1.7.0, 2026-11-19, see the probe
scripts in this folder):

- Reads: EnumerationAttribute `PrimaryBattChargeCfg`,
  IntegerAttributes `CustomChargeStart` (50–95) and
  `CustomChargeStop` (55–100), in `root\dcim\sysman\biosattributes`.
- Writes: `BIOSAttributeInterface.SetAttribute` with SecType 0,
  SecHndCount 0, empty SecHandle (no BIOS setup password is set).
  The documented `SetBIOSAttributes` name does not exist on this
  provider — probe4.ps1 enumerated the real methods.
- Telemetry: `root\WMI` BatteryStatus / BatteryFullChargedCapacity
  / BatteryCycleCount.

## Build (on the Dell)

Requires the free .NET 10 SDK (dotnet.microsoft.com/download).
Copy the whole `windows` folder over, then in PowerShell:

```powershell
cd windows\BatterySail
dotnet build -c Release
```

Run `bin\Release\net10.0-windows\BatterySail.exe` — it asks for
administrator rights (BIOS writes need them; the app manifest
requires elevation).

Optional single-file build:

```powershell
dotnet publish -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true
```

## First run and daily use

On first launch the app records the current BIOS charge mode
(it was `Adaptive`) and applies the default band: start 70,
stop 80. The tray icon shows the charge percent; the menu shows
the mode (Sailing / Charging / At limit / On battery / Off), the
band, and the cycle count.

- **Disable BatterySail** restores the recorded original mode.
- **Charge to 100% once** widens the band to 95/100 until the
  battery is full, then re-applies the sailing band.
- **Charge limit** switches the band between 70–80 and 80–90.
- Settings live in `%LocalAppData%\BatterySail\config.json`.
- Quitting the tray app changes nothing in the BIOS — the band
  persists until you Disable or change it in BIOS setup.

Autostart at logon without a UAC prompt (adjust the path):

```powershell
schtasks /Create /TN BatterySail /TR "\"C:\path\to\BatterySail.exe\"" /SC ONLOGON /RL HIGHEST /F
```

## Known differences from the Mac version (v1)

- No heat pause: the standard Windows battery classes do not
  expose battery temperature on this machine.
- No forced discharge: the Dell band only gates charging, so
  sailing down from a full charge happens by natural drain —
  same as Mac v1.
- If a BIOS setup password is ever set, writes will fail with a
  nonzero firmware Status and the app will say so; password
  support is not implemented.
