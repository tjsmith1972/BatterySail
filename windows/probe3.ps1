# BatterySail for Windows - probe #3 (READ-ONLY)
# Probe 2 found the Dell WMI BIOS interface alive with
# PrimaryBattChargeCfg (an EnumerationAttribute). The custom
# start/stop values are IntegerAttributes, which probe 2 did not
# query. This probe reads those, expands PossibleValues properly,
# and confirms the BIOSAttributeInterface class (the write channel)
# exists. Changes nothing.
# Run in PowerShell as administrator, same as before.

$ErrorActionPreference = 'Continue'
$ns = 'root\dcim\sysman\biosattributes'

Write-Host "`n===== EnumerationAttribute (charge-related) ====="
try {
    Get-CimInstance -Namespace $ns -ClassName EnumerationAttribute -ErrorAction Stop |
        Where-Object { $_.AttributeName -match 'Batt|Charge' } |
        ForEach-Object {
            Write-Host ("{0} = {1}" -f $_.AttributeName, $_.CurrentValue)
            Write-Host ("    Possible: " + ($_.PossibleValues -join ', '))
        }
} catch { Write-Host "Not available: $($_.Exception.Message)" }

Write-Host "`n===== IntegerAttribute (charge-related) ====="
try {
    Get-CimInstance -Namespace $ns -ClassName IntegerAttribute -ErrorAction Stop |
        Where-Object { $_.AttributeName -match 'Batt|Charge' } |
        ForEach-Object {
            Write-Host ("{0} = {1}  (min {2}, max {3})" -f $_.AttributeName, $_.CurrentValue, $_.LowerBound, $_.UpperBound)
        }
} catch { Write-Host "Not available: $($_.Exception.Message)" }

Write-Host "`n===== BIOSAttributeInterface (write channel) ====="
try {
    $iface = Get-CimInstance -Namespace $ns -ClassName BIOSAttributeInterface -ErrorAction Stop
    Write-Host 'Interface class present.'
    $iface | Format-List *
} catch { Write-Host "Not available: $($_.Exception.Message)" }

Write-Host "`nProbe 3 done. Nothing was changed."
