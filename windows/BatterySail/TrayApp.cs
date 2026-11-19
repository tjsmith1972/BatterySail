using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace BatterySailWin;

/// <summary>
/// BatterySail for Windows — tray icon + controller.
///
/// The Dell firmware enforces the band itself (CustomChargeStart /
/// CustomChargeStop), so unlike the Mac daemon there is nothing to
/// poll for enforcement: this app sets the band, watches the
/// battery, and shows the mode. It re-applies the band at launch if
/// something else changed it, runs the "charge to 100% once"
/// override, and restores the pre-BatterySail mode on Disable.
///
/// Mode names mirror the Mac menu bar app: Sailing, Charging,
/// At limit, On battery, Off.
/// </summary>
public sealed class TrayApp : ApplicationContext
{
    private readonly NotifyIcon _tray = new();
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 15000 };
    private readonly ToolStripMenuItem _statusLine = new() { Enabled = false };
    private readonly ToolStripMenuItem _detailLine = new() { Enabled = false };
    private readonly ToolStripMenuItem _toggleItem = new();
    private readonly ToolStripMenuItem _chargeOnceItem = new("Charge to 100% once");
    private readonly ToolStripMenuItem _limit80 = new("Limit 80%");
    private readonly ToolStripMenuItem _limit90 = new("Limit 90%");
    private SailConfig _cfg = SailConfig.Load();
    private string? _applyError;
    private IntPtr _iconHandle = IntPtr.Zero;
    private string _lastIconText = "";
    private bool _busy;

    public TrayApp()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add(_statusLine);
        menu.Items.Add(_detailLine);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(_toggleItem);
        menu.Items.Add(_chargeOnceItem);
        var limitMenu = new ToolStripMenuItem("Charge limit");
        limitMenu.DropDownItems.Add(_limit80);
        limitMenu.DropDownItems.Add(_limit90);
        menu.Items.Add(limitMenu);
        menu.Items.Add(new ToolStripSeparator());
        var quit = new ToolStripMenuItem("Quit");
        quit.Click += (_, _) => ExitThread();
        menu.Items.Add(quit);

        _toggleItem.Click += async (_, _) => await ToggleAsync();
        _chargeOnceItem.Click += async (_, _) => await ChargeOnceAsync();
        _limit80.Click += async (_, _) => await SetLimitAsync(80);
        _limit90.Click += async (_, _) => await SetLimitAsync(90);

        _tray.ContextMenuStrip = menu;
        _tray.Visible = true;
        _tray.Text = "BatterySail - starting";

        _timer.Tick += async (_, _) => await RefreshAsync();
        _timer.Start();
        _ = RefreshAsync(initial: true);
    }

    private async Task RefreshAsync(bool initial = false)
    {
        if (_busy) return;
        _busy = true;
        try
        {
            var (bat, bios) = await Task.Run(() =>
            {
                var b = BatteryInfo.Read();
                BiosCharge.ChargeConfig? c = null;
                try { c = BiosCharge.Read(); } catch { /* battery info still shows */ }
                return (b, c);
            });

            // Launch-time drift repair: enabled but the band is not
            // in the firmware (first run, or it was changed in BIOS
            // setup) -> capture the current mode as the one to
            // restore later, then apply the band.
            if (initial && _cfg.Enabled && bios is not null && bios.Mode != "Custom")
            {
                _cfg.OriginalMode ??= bios.Mode;
                _cfg.Save();
                try
                {
                    await Task.Run(() => BiosCharge.ApplyCustomBand(
                        _cfg.ChargeLimit - _cfg.SailingRange, _cfg.ChargeLimit));
                    _applyError = null;
                }
                catch (Exception ex) { _applyError = ex.Message; }
                bios = await Task.Run(() => BiosCharge.Read());
            }

            // Charge-once finished -> back to the sailing band.
            if (_cfg.ChargeOnceActive && bat.PowerOnline && !bat.Charging && bat.Percent >= 99)
            {
                _cfg.ChargeOnceActive = false;
                _cfg.Save();
                await Task.Run(() => BiosCharge.ApplyCustomBand(
                    _cfg.ChargeLimit - _cfg.SailingRange, _cfg.ChargeLimit));
                bios = await Task.Run(() => BiosCharge.Read());
            }

            string mode = ComputeMode(bat, bios);
            _statusLine.Text = $"{bat.Percent}% - {mode}";
            _detailLine.Text = _applyError is not null
                ? $"Error: {_applyError}"
                : bios is null
                ? $"Cycles: {bat.CycleCount} - {bat.VoltageV:F1} V - BIOS state unreadable"
                : $"Band: start {bios.Start}% - stop {bios.Stop}% - mode {bios.Mode} - cycles {bat.CycleCount}";
            _toggleItem.Text = _cfg.Enabled ? "Disable BatterySail" : "Enable BatterySail";
            _chargeOnceItem.Enabled = _cfg.Enabled && !_cfg.ChargeOnceActive;
            _limit80.Checked = _cfg.ChargeLimit == 80;
            _limit90.Checked = _cfg.ChargeLimit == 90;
            _tray.Text = Limit63($"BatterySail - {bat.Percent}% - {mode}");
            SetIcon(bat.Percent);
        }
        catch (Exception ex)
        {
            _statusLine.Text = "BatterySail - error";
            _detailLine.Text = ex.Message;
        }
        finally { _busy = false; }
    }

    private string ComputeMode(BatterySnapshot bat, BiosCharge.ChargeConfig? bios)
    {
        if (!bat.PowerOnline) return "On battery";
        if (_cfg.ChargeOnceActive) return bat.Charging ? "Charging to 100" : "At 100";
        if (bios is null || bios.Mode != "Custom" || !_cfg.Enabled)
            return $"Off ({bios?.Mode ?? "unknown"})";
        if (bat.Charging) return "Charging";
        if (bat.Percent >= bios.Stop) return "At limit";
        return "Sailing";
    }

    private async Task ToggleAsync()
    {
        try
        {
            if (_cfg.Enabled)
            {
                string restore = _cfg.OriginalMode ?? "Adaptive";
                await Task.Run(() => BiosCharge.SetMode(restore));
                _cfg.Enabled = false;
                _cfg.ChargeOnceActive = false;
            }
            else
            {
                var bios = await Task.Run(() => BiosCharge.Read());
                if (bios.Mode != "Custom") _cfg.OriginalMode = bios.Mode;
                await Task.Run(() => BiosCharge.ApplyCustomBand(
                    _cfg.ChargeLimit - _cfg.SailingRange, _cfg.ChargeLimit));
                _cfg.Enabled = true;
            }
            _cfg.Save();
        }
        catch (Exception ex) { ShowError(ex); }
        await RefreshAsync();
    }

    private async Task ChargeOnceAsync()
    {
        try
        {
            // Widest band the firmware allows: start 95, stop 100.
            await Task.Run(() => BiosCharge.ApplyCustomBand(95, 100));
            _cfg.ChargeOnceActive = true;
            _cfg.Save();
        }
        catch (Exception ex) { ShowError(ex); }
        await RefreshAsync();
    }

    private async Task SetLimitAsync(int limit)
    {
        try
        {
            _cfg.ChargeLimit = limit;
            _cfg.Save();
            if (_cfg.Enabled && !_cfg.ChargeOnceActive)
                await Task.Run(() => BiosCharge.ApplyCustomBand(
                    limit - _cfg.SailingRange, limit));
        }
        catch (Exception ex) { ShowError(ex); }
        await RefreshAsync();
    }

    private static void ShowError(Exception ex) =>
        MessageBox.Show(ex.Message, "BatterySail", MessageBoxButtons.OK, MessageBoxIcon.Warning);

    // Tray icon: the charge percent as white digits on Sunfish navy,
    // redrawn only when the number changes.
    private void SetIcon(int pct)
    {
        string text = pct.ToString();
        if (text == _lastIconText) return;
        _lastIconText = text;
        using var bmp = new Bitmap(32, 32);
        using (var g = Graphics.FromImage(bmp))
        {
            g.Clear(Color.Transparent);
            using var bg = new SolidBrush(Color.FromArgb(30, 60, 114));
            g.FillRectangle(bg, 1, 1, 30, 30);
            using var font = new Font("Segoe UI", text.Length >= 3 ? 12f : 15f, FontStyle.Bold);
            using var fg = new SolidBrush(Color.White);
            var size = g.MeasureString(text, font);
            g.DrawString(text, font, fg, (32 - size.Width) / 2, (32 - size.Height) / 2);
        }
        IntPtr h = bmp.GetHicon();
        _tray.Icon = Icon.FromHandle(h);
        if (_iconHandle != IntPtr.Zero) DestroyIcon(_iconHandle);
        _iconHandle = h;
    }

    private static string Limit63(string s) => s.Length <= 63 ? s : s[..63];

    protected override void ExitThreadCore()
    {
        _timer.Stop();
        _tray.Visible = false;
        _tray.Dispose();
        if (_iconHandle != IntPtr.Zero) DestroyIcon(_iconHandle);
        base.ExitThreadCore();
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool DestroyIcon(IntPtr hIcon);
}
