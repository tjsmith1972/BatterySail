using System.Management;

namespace BatterySailWin;

public sealed record BatterySnapshot(
    int Percent, bool PowerOnline, bool Charging, bool Discharging,
    int RemainingMwh, int FullChargeMwh, int CycleCount, double VoltageV);

/// <summary>
/// Battery telemetry from the standard root\WMI battery classes —
/// verified live on the Dell by probe2.ps1 (FullChargedCapacity
/// 93752 mWh, CycleCount 8, Voltage 12811 mV, PowerOnline True).
/// Win32_Battery left capacities blank on this machine; these
/// classes did not. Note: no temperature is exposed here, which is
/// why the Mac version's heat-pause has no Windows equivalent in v1.
/// </summary>
public static class BatteryInfo
{
    public static BatterySnapshot Read()
    {
        int full = ReadInt("BatteryFullChargedCapacity", "FullChargedCapacity");
        int cycles = ReadInt("BatteryCycleCount", "CycleCount");
        using var searcher = new ManagementObjectSearcher(@"root\WMI", "SELECT * FROM BatteryStatus");
        foreach (ManagementObject o in searcher.Get())
        {
            int remaining = Convert.ToInt32(o["RemainingCapacity"]);
            bool online = o["PowerOnline"] is bool on && on;
            bool charging = o["Charging"] is bool ch && ch;
            bool discharging = o["Discharging"] is bool di && di;
            double volts = Convert.ToInt32(o["Voltage"]) / 1000.0;
            int pct = full > 0 ? (int)Math.Round(100.0 * remaining / full) : 0;
            return new BatterySnapshot(pct, online, charging, discharging, remaining, full, cycles, volts);
        }
        throw new InvalidOperationException("BatteryStatus not available");
    }

    private static int ReadInt(string cls, string prop)
    {
        using var s = new ManagementObjectSearcher(@"root\WMI", $"SELECT {prop} FROM {cls}");
        foreach (ManagementObject o in s.Get())
            return Convert.ToInt32(o[prop]);
        return 0;
    }
}
