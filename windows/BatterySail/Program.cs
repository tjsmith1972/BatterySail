namespace BatterySailWin;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // One tray instance only.
        using var mutex = new Mutex(true, "BatterySailWin", out bool isNew);
        if (!isNew) return;

        ApplicationConfiguration.Initialize();
        Application.Run(new TrayApp());
    }
}
