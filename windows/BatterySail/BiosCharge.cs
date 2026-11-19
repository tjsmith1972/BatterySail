using System.Management;
using Microsoft.Management.Infrastructure;
// Both WMI libraries define a CimType enum; ours is the MMI one.
using CimType = Microsoft.Management.Infrastructure.CimType;

namespace BatterySailWin;

/// <summary>
/// Dell BIOS charge control via the WMI BIOS attribute interface
/// (root\dcim\sysman\biosattributes) — fingerprinted on the Dell Pro
/// Precision 5 16 (PW516261), BIOS 1.7.0, on 2026-11-19:
///  - Reads: EnumerationAttribute / IntegerAttribute instances.
///  - Writes: BIOSAttributeInterface.SetAttribute (singular — the
///    documented "SetBIOSAttributes" name does not exist on this
///    provider) with the security block SecType=0 (no password),
///    SecHndCount=0, SecHandle=empty byte array. That "full-empty"
///    style was proven by batterysail_write_test.ps1: mode, start
///    and stop writes all returned Return=True, Status=0, verified
///    by read-back, and the restore to Adaptive/50/90 verified too.
///  - Stack: writes must go through the CIM/MI stack — the one
///    PowerShell's *-Cim* cmdlets (and the write test) use. The
///    legacy System.Management WMI stack READS this provider fine
///    but cannot invoke its methods: the first app build's writes
///    died with ManagementException "Not found" (2026-11-19).
/// If a BIOS setup password is ever set, Status comes back nonzero
/// and we surface it instead of guessing at the password scheme.
/// </summary>
public static class BiosCharge
{
    private const string Ns = @"root\dcim\sysman\biosattributes";

    public sealed record ChargeConfig(string Mode, int Start, int Stop);

    public static ChargeConfig Read()
    {
        string mode = ReadAttribute("EnumerationAttribute", "PrimaryBattChargeCfg")
                      ?? throw new InvalidOperationException("PrimaryBattChargeCfg not found");
        int start = ReadIntAttribute("CustomChargeStart");
        int stop = ReadIntAttribute("CustomChargeStop");
        return new ChargeConfig(mode, start, stop);
    }

    private static string? ReadAttribute(string cls, string name)
    {
        using var searcher = new ManagementObjectSearcher(Ns,
            $"SELECT CurrentValue FROM {cls} WHERE AttributeName='{name}'");
        foreach (ManagementObject o in searcher.Get())
            return o["CurrentValue"]?.ToString();
        return null;
    }

    private static int ReadIntAttribute(string name)
    {
        string? raw = ReadAttribute("IntegerAttribute", name)
                      ?? throw new InvalidOperationException($"{name} not found");
        return int.Parse(raw);
    }

    /// <summary>
    /// Set one attribute; throws with the firmware Status on failure.
    /// Uses the CIM/MI stack (see the class remarks): the legacy
    /// System.Management stack cannot invoke this provider's methods.
    /// </summary>
    public static void SetAttribute(string name, string value)
    {
        using var session = CimSession.Create(null);
        foreach (var iface in session.QueryInstances(Ns, "WQL", "SELECT * FROM BIOSAttributeInterface"))
        {
            using (iface)
            {
                var parms = new CimMethodParametersCollection
                {
                    CimMethodParameter.Create("AttributeName", name, CimType.String, CimFlags.In),
                    CimMethodParameter.Create("AttributeValue", value, CimType.String, CimFlags.In),
                    CimMethodParameter.Create("SecHandle", Array.Empty<byte>(), CimType.UInt8Array, CimFlags.In),
                    CimMethodParameter.Create("SecHndCount", (uint)0, CimType.UInt32, CimFlags.In),
                    CimMethodParameter.Create("SecType", (uint)0, CimType.UInt32, CimFlags.In),
                };
                using var result = session.InvokeMethod(iface, "SetAttribute", parms);
                int status = Convert.ToInt32(result.OutParameters["Status"].Value);
                // ReturnValue's static type varies across MMI builds
                // (in 3.0.0 it is not object, so a direct `is bool`
                // pattern is CS8121). Go through object; only an
                // explicit False fails — the firmware Status is the
                // authoritative answer anyway.
                object? rv = result.ReturnValue;
                bool returnedFalse = rv is bool b && !b;
                if (returnedFalse || status != 0)
                    throw new InvalidOperationException(
                        $"SetAttribute {name}={value} failed: Return={result.ReturnValue} Status={status}");
                return;
            }
        }
        throw new InvalidOperationException("BIOSAttributeInterface instance not found");
    }

    /// <summary>
    /// Apply a custom sailing band: start/stop first, mode last —
    /// the same order the proven write test used. The firmware then
    /// enforces the band on its own (start charging at Start, stop
    /// at Stop) with no polling, exactly like the Mac's BCLM ceiling.
    /// </summary>
    public static void ApplyCustomBand(int start, int stop)
    {
        SetAttribute("CustomChargeStart", start.ToString());
        SetAttribute("CustomChargeStop", stop.ToString());
        SetAttribute("PrimaryBattChargeCfg", "Custom");
        // Verify by read-back: a band that did not take must be loud,
        // not silent (the first app launch applied start=75 but the
        // stop write was rejected, leaving the machine on Adaptive
        // with no visible sign anything had failed).
        var now = Read();
        if (now.Mode != "Custom" || now.Start != start || now.Stop != stop)
            throw new InvalidOperationException(
                $"Band did not take: firmware reports mode={now.Mode} start={now.Start} stop={now.Stop}, wanted Custom {start}/{stop}");
    }

    public static void SetMode(string mode) => SetAttribute("PrimaryBattChargeCfg", mode);
}
