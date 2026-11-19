# BatterySail for Windows - probe #4 (READ-ONLY)
# The write test failed with 'Method SetBIOSAttributes not found'
# (HRESULT 0x80041002) - the interface instance exists and reads
# work, but that method name is not in this provider's schema.
# Same discipline as the Mac SMC scan: enumerate what IS there.
# This probe dumps every class in the biosattributes namespace and
# every method (with parameter names/types) on the interface and
# attribute classes, plus a look at the parent sysman namespace.
# Changes nothing. Run in PowerShell as administrator.

$ErrorActionPreference = 'Continue'
$ns = 'root\dcim\sysman\biosattributes'

function Show-Methods([string]$namespace, [string]$class) {
    Write-Host "`n--- Methods on $namespace : $class ---"
    try {
        $cls = Get-CimClass -Namespace $namespace -ClassName $class -ErrorAction Stop
        if (-not $cls.CimClassMethods -or $cls.CimClassMethods.Count -eq 0) {
            Write-Host '(no methods defined)'
            return
        }
        foreach ($m in $cls.CimClassMethods) {
            Write-Host ("Method: " + $m.Name + "  -> returns " + $m.ReturnType)
            foreach ($p in $m.Parameters) {
                $quals = ($p.Qualifiers | ForEach-Object { $_.Name }) -join ','
                Write-Host ("    param: {0} : {1} [{2}]" -f $p.Name, $p.CimType, $quals)
            }
        }
    } catch { Write-Host "Not available: $($_.Exception.Message)" }
}

Write-Host "`n===== All classes in $ns ====="
try {
    Get-CimClass -Namespace $ns -ErrorAction Stop |
        ForEach-Object { Write-Host $_.CimClassName }
} catch { Write-Host "Not available: $($_.Exception.Message)" }

Show-Methods $ns 'BIOSAttributeInterface'
Show-Methods $ns 'EnumerationAttribute'
Show-Methods $ns 'IntegerAttribute'
Show-Methods $ns 'StringAttribute'

Write-Host "`n===== Classes in root\dcim\sysman (parent) ====="
try {
    Get-CimClass -Namespace 'root\dcim\sysman' -ErrorAction Stop |
        ForEach-Object { Write-Host $_.CimClassName }
} catch { Write-Host "Not available: $($_.Exception.Message)" }

Write-Host "`nProbe 4 done. Nothing was changed."
