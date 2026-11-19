using System.Text.Json;

namespace BatterySailWin;

/// <summary>
/// BatterySail settings, stored as JSON in
/// %LocalAppData%\BatterySail\config.json — the counterpart of the
/// Mac version's /etc/batterysail.json. OriginalMode remembers the
/// BIOS charge mode that was in effect before BatterySail first
/// applied its band ("Adaptive" on the Dell) so Disable can put
/// things back exactly as they were.
/// </summary>
public sealed class SailConfig
{
    public bool Enabled { get; set; } = true;
    public int ChargeLimit { get; set; } = 80;   // band stop
    public int SailingRange { get; set; } = 10;  // band start = limit - range (10, not 5: the firmware rejected a stop exactly 5 above the start; the proven write-test band was 70/80)
    public string? OriginalMode { get; set; }
    public bool ChargeOnceActive { get; set; }

    private static string Dir => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "BatterySail");
    private static string FilePath => Path.Combine(Dir, "config.json");

    public static SailConfig Load()
    {
        try
        {
            if (File.Exists(FilePath))
                return JsonSerializer.Deserialize<SailConfig>(File.ReadAllText(FilePath)) ?? new SailConfig();
        }
        catch { /* unreadable config -> defaults */ }
        return new SailConfig();
    }

    public void Save()
    {
        Directory.CreateDirectory(Dir);
        File.WriteAllText(FilePath,
            JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
    }
}
