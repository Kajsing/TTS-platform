using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;
using Forms = System.Windows.Forms;

if (!OperatingSystem.IsWindows())
{
    Console.Error.WriteLine("Windows integration smoke requires Windows.");
    return 2;
}

string? output = null;
Exception? failure = null;
var smokeThread = new Thread(() =>
{
    try
    {
        using var window = new SmokeWindow();
        using var listener = new ClipboardListener(new FixedForegroundApplication());
        if (!listener.Register(window.Handle))
        {
            throw new InvalidOperationException(
                listener.RegistrationError ?? "Clipboard listener registration failed.");
        }
        listener.Unregister();
        var monitoringOffUnregistered = !listener.IsRegistered;
        var monitoringCanRestart = listener.Register(window.Handle);
        if (!monitoringOffUnregistered || !monitoringCanRestart)
        {
            throw new InvalidOperationException(
                "Clipboard prompt monitoring did not stop and restart cleanly.");
        }

        using var hotkeys = new GlobalHotkeyManager();
        var hotkeyResults = hotkeys.Register(
            window.Handle,
            [
                new GlobalHotkeyBinding(GlobalHotkeyCommand.ReadClipboard, "not-a-hotkey"),
                new GlobalHotkeyBinding(GlobalHotkeyCommand.PlayPause, "Ctrl+Alt+Shift+F24"),
            ]);
        var invalidHotkeyWasNonfatal = hotkeyResults.Count == 2 &&
            hotkeyResults[0].Registered is false &&
            hotkeyResults[0].Message is not null;
        if (!invalidHotkeyWasNonfatal)
        {
            throw new InvalidOperationException("Invalid global hotkey handling was not nonfatal.");
        }

        using (var tray = new ReaderTrayIcon())
        {
            tray.SetClipboardMonitoring(enabled: false);
            tray.SetStatus("Windows integration smoke");
        }

        var defaults = new DesktopSettings();
        if (defaults.ClipboardMonitoringEnabled || defaults.CopySelectionAndReadEnabled ||
            !defaults.PrivacyMode)
        {
            throw new InvalidOperationException("Clipboard privacy defaults are unsafe.");
        }

        output = JsonSerializer.Serialize(new
        {
            windows_integration = true,
            clipboard_listener_registered = listener.IsRegistered,
            monitoring_off_unregistered = monitoringOffUnregistered,
            monitoring_restart = monitoringCanRestart,
            clipboard_read_or_write_performed = false,
            monitoring_default = defaults.ClipboardMonitoringEnabled,
            copy_selection_default = defaults.CopySelectionAndReadEnabled,
            privacy_default = defaults.PrivacyMode,
            invalid_hotkey_nonfatal = invalidHotkeyWasNonfatal,
            configured_hotkey_registered = hotkeyResults[1].Registered,
            tray_lifecycle = "created_and_disposed",
        });
    }
    catch (Exception exception)
    {
        failure = exception;
    }
});
smokeThread.SetApartmentState(ApartmentState.STA);
smokeThread.Start();
if (!smokeThread.Join(TimeSpan.FromSeconds(10)))
{
    Console.Error.WriteLine("Windows integration smoke timed out.");
    return 3;
}
if (failure is not null)
{
    Console.Error.WriteLine(
        $"Windows integration smoke failed: {failure.GetType().Name}: {failure.Message}");
    return 1;
}

Console.WriteLine(output);
return 0;

file sealed class SmokeWindow : Forms.NativeWindow, IDisposable
{
    public SmokeWindow()
    {
        CreateHandle(new Forms.CreateParams
        {
            Caption = "TTS Platform Reader Windows integration smoke",
        });
    }

    public void Dispose() => DestroyHandle();
}

file sealed class FixedForegroundApplication : IForegroundApplicationReader
{
    public string? GetExecutableName() => "smoke.exe";
}
