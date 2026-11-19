# BatterySail-Win probe (READ-ONLY - changes nothing)
#
# Fingerprints this Dell the way smc_scan.py fingerprinted the Mac:
# which programmatic route to the BIOS battery-charge settings exists
# on this machine, what the settings are called here, their current
# values, and whether a BIOS admin password gates writes.
#
# Run in an ELEVATED PowerShell on the Dell (Run as administrator),
# then paste the whole output back to Mila:
#     powershell -ExecutionPolicy Bypass -File .\probe.ps1

$ErrorActionPreference = 'Continue'

function Section($title) { Write-Host "`n===== $title =====" }

Section 'Elevation'
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "Running as administrator: $isAdmin"

Section 'System'
Get-CimInstance Win32_ComputerSystem |
    Select-Object Manufacturer, Model | Format-List | Out-String | Write-Host
Get-CimInstance Win32_BIOS |
    Select-Object SMBIOSBIOSVersion, ReleaseDate | Format-List | Out-String | Write-Host

Section 'Battery (Win32_Battery)'
Get-CimInstance Win32_Battery |
    Select-Object Name, EstimatedChargeRemaining, BatteryStatus,
        DesignCapacity, FullChargeCapacity |
    Format-List | Out-String | Write-Host

Section 'Route 1: Dell WMI BIOS attributes (root\dcim\sysman\biosattributes)'
$ns = 'root\dcim\sysman\biosattributes'
try {
    $enums = Get-CimInstance -Namespace $ns -ClassName DCIM_BIOSEnumeration `
        -ErrorAction Stop |
        Where-Object { $_.AttributeName -match 'Batt|Charge' }
    foreach ($a in $enums) {
        Write-Host ("ENUM  {0} = {1}   [possible: {2}]" -f `
            $a.AttributeName, ($a.CurrentValue -join ','), `
            ($a.PossibleValues -join ', '))
    }
    $ints = Get-CimInstance -Namespace $ns -ClassName DCIM_BIOSInteger `
        -ErrorAction Stop |
        Where-Object { $_.AttributeName -match 'Batt|Charge' }
    foreach ($a in $ints) {
        Write-Host ("INT   {0} = {1}   [range {2}..{3}]" -f `
            $a.AttributeName, $a.CurrentValue, $a.LowerBound, $a.UpperBound)
    }
    if (-not $enums -and -not $ints) {
        Write-Host 'Namespace exists, but no Batt/Charge attributes found.'
    }
} catch {
    Write-Host "Not available: $($_.Exception.Message)"
}

Section 'BIOS passwords (write gate)'
try {
    Get-CimInstance -Namespace $ns -ClassName DCIM_BIOSPassword `
        -ErrorAction Stop |
        ForEach-Object { Write-Host ("{0}: IsSet = {1}" -f $_.Name, $_.IsSet) }
} catch {
    Write-Host "Not reported: $($_.Exception.Message)"
}

Section 'Route 2: Dell Command PowerShell Provider (DellSmbios: drive)'
try {
    $drive = Get-PSDrive -Name DellSmbios -ErrorAction Stop
    Write-Host "DellSmbios: drive present ($($drive.Description))"
    Get-ChildItem -Path 'DellSmbios:\PowerManagement' -ErrorAction Stop |
        Where-Object { $_.AttributeName -match 'Batt|Charge' -or `
                       $_.Name -match 'Batt|Charge' } |
        Format-List | Out-String | Write-Host
} catch {
    Write-Host "Not available: $($_.Exception.Message)"
}

Section 'Route 3: Dell Command | Configure (cctk.exe)'
$cctkPaths = @(
    'C:\Program Files (x86)\Dell\Command Configure\X86_64\cctk.exe',
    'C:\Program Files\Dell\Command Configure\X86_64\cctk.exe'
)
$found = $cctkPaths | Where-Object { Test-Path $_ }
if ($found) {
    Write-Host "Found: $($found -join ', ')"
    & $found[0] --PrimaryBattChargeCfg 2>&1 | Write-Host
} else {
    Write-Host 'cctk.exe not found in the usual locations.'
}

Write-Host "`nProbe done. Nothing was changed."
