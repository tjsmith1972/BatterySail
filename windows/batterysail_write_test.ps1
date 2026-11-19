# BatterySail for Windows - WRITE TEST v2 (changes BIOS settings, then restores them)
# Rewritten against probe 4's fingerprint: on this BIOS the write
# method is SetAttribute (singular) on BIOSAttributeInterface, with
# a security block (SecType / SecHndCount / SecHandle). SecType 0 =
# no password. The documented 'SetBIOSAttributes' name belongs to a
# different Dell provider generation and does not exist here.
#
# Sequence:
#   1. Read PrimaryBattChargeCfg, CustomChargeStart, CustomChargeStop.
#   2. Best-effort: fetch the firmware's own help strings for those
#      attributes (may confirm exact value spellings). Read-only.
#   3. No-op write (mode -> its current value) to negotiate the exact
#      calling style: several SecHandle shapes are tried ONLY while
#      the invoke itself fails; if the firmware answers with a
#      nonzero Status, the script stops - that is a real answer
#      (e.g. a setup password gates writes). Nothing has changed
#      either way at this point.
#   4. Real flip: start = 70, stop = 80, mode = Custom. Read back
#      and verify all three.
#   5. Restore the original values. Read back and verify.
# The battery is at 100% on AC, so the brief Custom window has no
# practical effect. Run in PowerShell as administrator.

$ErrorActionPreference = 'Continue'
$ns = 'root\dcim\sysman\biosattributes'

function Get-Attr([string]$class, [string]$name) {
    $a = Get-CimInstance -Namespace $ns -ClassName $class | Where-Object { $_.AttributeName -eq $name }
    if ($a) { return [string]$a.CurrentValue }
    return $null
}

function Show-Help([string]$name) {
    try {
        $iface = Get-CimInstance -Namespace $ns -ClassName BIOSAttributeInterface
        $r = Invoke-CimMethod -InputObject $iface -MethodName GetHelpString -Arguments @{ AttributeName = $name } -ErrorAction Stop
        if ($r.HelpString) {
            $text = [Text.Encoding]::ASCII.GetString([byte[]]$r.HelpString)
            Write-Host ("--- help for {0} ---" -f $name)
            Write-Host $text
        }
    } catch { Write-Host "(no help string for $name)" }
}

# Returns @{ Invoked = bool; Status = int } - Invoked $false means the
# call itself failed (parameter shape), Status is the firmware's answer.
function Try-SetAttr([string]$name, [string]$value, [string]$style) {
    $iface = Get-CimInstance -Namespace $ns -ClassName BIOSAttributeInterface
    $argSet = @{ AttributeName = $name; AttributeValue = $value }
    switch ($style) {
        'full-empty' { $argSet.SecType = [uint32]0; $argSet.SecHndCount = [uint32]0; $argSet.SecHandle = [byte[]]@() }
        'no-handle'  { $argSet.SecType = [uint32]0 }
        'zero-byte'  { $argSet.SecType = [uint32]0; $argSet.SecHndCount = [uint32]1; $argSet.SecHandle = [byte[]]@(0) }
    }
    try {
        $r = Invoke-CimMethod -InputObject $iface -MethodName SetAttribute -Arguments $argSet -ErrorAction Stop
        return @{ Invoked = $true; Status = [int]$r.Status; Return = $r.ReturnValue }
    } catch {
        Write-Host "    style $style invoke failed: $($_.Exception.Message)"
        return @{ Invoked = $false; Status = $null; Return = $null }
    }
}

$mode  = Get-Attr 'EnumerationAttribute' 'PrimaryBattChargeCfg'
$start = Get-Attr 'IntegerAttribute' 'CustomChargeStart'
$stop  = Get-Attr 'IntegerAttribute' 'CustomChargeStop'
Write-Host "Current: mode=$mode start=$start stop=$stop"
if (-not $mode -or -not $start -or -not $stop) {
    Write-Host 'ABORT: an attribute is missing.'
    exit 1
}

Show-Help 'PrimaryBattChargeCfg'
Show-Help 'CustomChargeStart'
Show-Help 'CustomChargeStop'

Write-Host "`nNo-op write: PrimaryBattChargeCfg -> $mode (unchanged)"
$script:style = $null
foreach ($s in 'full-empty', 'no-handle', 'zero-byte') {
    $res = Try-SetAttr 'PrimaryBattChargeCfg' $mode $s
    if ($res.Invoked) {
        Write-Host "  style $s -> Return=$($res.Return) Status=$($res.Status)"
        if ($res.Status -eq 0) { $script:style = $s }
        break
    }
}
if (-not $script:style) {
    Write-Host 'No working no-op write. If a Status was printed, the firmware answered (setup password is the usual cause); if every style failed to invoke, report the errors above. Nothing was changed.'
    exit 1
}
Write-Host "Working style: $script:style"

function Set-Attr-OrDie([string]$name, [string]$value) {
    $res = Try-SetAttr $name $value $script:style
    Write-Host "  set $name -> $value : Return=$($res.Return) Status=$($res.Status)"
    if (-not $res.Invoked -or $res.Status -ne 0) { throw "Set of $name failed" }
}

try {
    Write-Host "`nReal flip: start -> 70, stop -> 80, mode -> Custom"
    Set-Attr-OrDie 'CustomChargeStart' '70'
    Set-Attr-OrDie 'CustomChargeStop' '80'
    Set-Attr-OrDie 'PrimaryBattChargeCfg' 'Custom'
} catch {
    Write-Host "Flip failed partway: $($_.Exception.Message) - restoring originals now."
}
$m2 = Get-Attr 'EnumerationAttribute' 'PrimaryBattChargeCfg'
$s2 = Get-Attr 'IntegerAttribute' 'CustomChargeStart'
$p2 = Get-Attr 'IntegerAttribute' 'CustomChargeStop'
Write-Host "Read back: mode=$m2 start=$s2 stop=$p2"
Write-Host ("Flip verified: " + ($m2 -eq 'Custom' -and $s2 -eq '70' -and $p2 -eq '80'))

Write-Host "`nRestore: mode -> $mode, start -> $start, stop -> $stop"
try {
    Set-Attr-OrDie 'PrimaryBattChargeCfg' $mode
    Set-Attr-OrDie 'CustomChargeStart' $start
    Set-Attr-OrDie 'CustomChargeStop' $stop
} catch { Write-Host "Restore hit an error: $($_.Exception.Message)" }
$m3 = Get-Attr 'EnumerationAttribute' 'PrimaryBattChargeCfg'
$s3 = Get-Attr 'IntegerAttribute' 'CustomChargeStart'
$p3 = Get-Attr 'IntegerAttribute' 'CustomChargeStop'
Write-Host "Read back: mode=$m3 start=$s3 stop=$p3"
if ($m3 -eq $mode -and $s3 -eq $start -and $p3 -eq $stop) {
    Write-Host "`nRESTORED OK. The WMI write path works end to end."
} else {
    Write-Host "`n!! RESTORE MISMATCH - set the values back in BIOS setup (F2 at boot): Battery Settings."
    exit 1
}
