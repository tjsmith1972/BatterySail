# BatterySail for Windows - probe #2 (READ-ONLY)
# Run AFTER installing Dell Command | Configure. Changes nothing:
# every cctk / DellSmbios call below is a read. It answers:
#   1. Where did cctk.exe land, and what is the current battery
#      charge configuration (mode + custom start/stop values)?
#   2. Is a BIOS setup password set? (It would gate our writes.)
#   3. What does the detailed battery telemetry say (design vs full
#      charge capacity, cycle count, charge/discharge rate)?
# Run in PowerShell as administrator, same as probe.ps1.

$ErrorActionPreference = 'Continue'

Write-Host "`n===== Elevation ====="
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
Write-Host ("Running as administrator: " + $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

Write-Host "`n===== cctk.exe ====="
$cctk = $null
$cmd = Get-Command cctk.exe -ErrorAction SilentlyContinue
if ($cmd) { $cctk = $cmd.Source }
if (-not $cctk) {
    $hits = Get-ChildItem 'C:\Program Files (x86)\Dell', 'C:\Program Files\Dell' -Recurse -Filter cctk.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hits) { $cctk = $hits.FullName }
}
if ($cctk) {
    Write-Host "Found: $cctk"
    foreach ($token in '--PrimaryBattChargeCfg', '--CustomChargeStart', '--CustomChargeStop', '--SetupPwd') {
        Write-Host "`n--- cctk $token (read) ---"
        try { & $cctk $token 2>&1 | ForEach-Object { Write-Host $_ } }
        catch { Write-Host "Error: $($_.Exception.Message)" }
    }
} else {
    Write-Host 'cctk.exe still not found - is Dell Command | Configure installed?'
}

Write-Host "`n===== DellSmbios: drive (DellBIOSProvider) ====="
try {
    if (Get-Module -ListAvailable DellBIOSProvider) {
        Import-Module DellBIOSProvider -ErrorAction Stop
        Get-PSDrive DellSmbios | Format-List Name, Root
        foreach ($item in 'DellSmbios:\PowerManagement\PrimaryBattChargeCfg',
                          'DellSmbios:\PowerManagement\CustomChargeStart',
                          'DellSmbios:\PowerManagement\CustomChargeStop') {
            try {
                $v = Get-Item $item -ErrorAction Stop
                Write-Host "$item -> $($v.CurrentValue)"
            } catch { Write-Host "$item -> not readable: $($_.Exception.Message)" }
        }
    } else {
        Write-Host 'DellBIOSProvider module not installed.'
    }
} catch { Write-Host "Error: $($_.Exception.Message)" }

Write-Host "`n===== Route 1 re-check: Dell WMI BIOS attributes ====="
try {
    $attrs = Get-CimInstance -Namespace 'root\dcim\sysman\biosattributes' -ClassName EnumerationAttribute -ErrorAction Stop |
        Where-Object { $_.AttributeName -match 'Batt|Charge' } |
        Select-Object AttributeName, CurrentValue, PossibleValues
    if ($attrs) { $attrs | Format-List } else { Write-Host 'Class present, no battery attributes matched.' }
} catch { Write-Host "Not available: $($_.Exception.Message)" }

Write-Host "`n===== Battery telemetry (root\WMI) ====="
foreach ($cls in 'BatteryStaticData', 'BatteryFullChargedCapacity', 'BatteryCycleCount', 'BatteryStatus') {
    try {
        Write-Host "--- $cls ---"
        Get-CimInstance -Namespace 'root\WMI' -ClassName $cls -ErrorAction Stop | Format-List *
    } catch { Write-Host "Not available: $($_.Exception.Message)" }
}

Write-Host "`nProbe 2 done. Nothing was changed."
