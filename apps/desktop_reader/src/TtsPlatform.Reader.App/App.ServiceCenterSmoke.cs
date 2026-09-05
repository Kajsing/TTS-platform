using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class App
{
    private async Task RunServiceCenterLifecycleSmokeAsync()
    {
        var marker = Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_SMOKE_MARKER");
        if (string.IsNullOrWhiteSpace(marker)) { Shutdown(1); return; }
        var root = Path.GetDirectoryName(Path.GetFullPath(marker))!;
        Directory.CreateDirectory(root);
        try
        {
            static void Require(bool condition, string message)
            {
                if (!condition) throw new InvalidOperationException(message);
            }
            async Task Idle() => await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            var store = new JsonDesktopSettingsStore(Path.Combine(root, "lifecycle-settings.json"));
            await store.SaveAsync(new DesktopSettings());
            var scope = "smoke-" + Guid.NewGuid().ToString("N");
            Require(ReaderInstanceChannel.TryAcquire(scope, out _instance), "Smoke ownership failed.");
            _serviceCenter = new DesktopServiceCenterHost(store, isolatedSmoke: true);
            _instance!.Listen(_serviceCenter.QueueActivation);
            Require(ReaderTrayIcon.LiveInstances == 1, "Host did not create exactly one real tray icon.");
            Require(await ReaderInstanceChannel.SendAsync(scope, ReaderActivation.Background), "Background activation was not acknowledged.");
            await Idle();
            Require(_serviceCenter.Reader is null, "Background activation opened a Reader window.");
            await _serviceCenter.OpenReaderAsync();
            await Idle();
            var first = _serviceCenter.Reader!;
            Require(first.IsVisible && ReaderTrayIcon.LiveInstances == 1, "Reader created another icon.");
            first.Close();
            await Idle();
            Require(_serviceCenter.Reader is null && ReaderTrayIcon.LiveInstances == 1,
                "Closing Reader destroyed the host or retained the editor.");

            // A second real executable invocation must activate this host, then exit.
            var start = new ProcessStartInfo(Environment.ProcessPath!)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
            if (string.Equals(Path.GetFileNameWithoutExtension(Environment.ProcessPath), "dotnet", StringComparison.OrdinalIgnoreCase))
                start.ArgumentList.Add(Assembly.GetExecutingAssembly().Location);
            start.ArgumentList.Add("--smoke-test");
            start.ArgumentList.Add("--activation-probe");
            start.Environment["TTS_PLATFORM_READER_ACTIVATION_SCOPE"] = scope;
            using (var secondary = Process.Start(start) ?? throw new InvalidOperationException("Could not launch secondary probe."))
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
                try { await secondary.WaitForExitAsync(timeout.Token); }
                catch (OperationCanceledException)
                {
                    if (!secondary.HasExited) secondary.Kill(entireProcessTree: true);
                    throw;
                }
                Require(secondary.ExitCode == 0, "Second executable failed to activate owner.");
            }
            await Idle();
            Require(_serviceCenter.Reader is { IsVisible: true } && _serviceCenter.Reader != first && ReaderTrayIcon.LiveInstances == 1,
                "Activation did not create a fresh Reader in the existing host.");
            var second = _serviceCenter.Reader!;
            second.PrepareLifecycleSmokeEdit();
            Require(!await second.CloseReaderAsync() && second.HasLifecycleSmokeEdit,
                "Reader close discarded an unsaved edit.");
            Require(!await _serviceCenter.ExitAsync(confirm: false) && second.HasLifecycleSmokeEdit,
                "Host exit discarded an unsaved edit.");
            second.ClearLifecycleSmokeEdit();
            var dialog = new Window { Owner = second, Width = 300, Height = 160, Title = "Isolated close guard" };
            dialog.Show();
            Require(!await second.CloseReaderAsync(), "Reader closed over an active dialog.");
            dialog.Close();
            Require(await second.CloseReaderAsync(), "Clean Reader did not close.");

            await store.SaveAsync(new DesktopSettings(MinimizeToTrayOnClose: true));
            await _serviceCenter.OpenReaderAsync();
            await Idle();
            var third = _serviceCenter.Reader!;
            third.Close();
            await Idle();
            Require(_serviceCenter.Reader == third && !third.IsVisible, "Minimize-on-close lost the live Reader.");
            await _serviceCenter.OpenReaderAsync();
            Require(third.IsVisible && ReaderTrayIcon.LiveInstances == 1, "Minimized Reader failed to restore.");
            await third.HandleTrayCommandAsync(ReaderTrayCommand.OpenCompactController);
            var compact = third.OwnedWindows.OfType<CompactControllerWindow>().Single();
            Require(compact.IsVisible, "Compact controller failed to open.");
            Require(await third.CloseReaderAsync() && _serviceCenter.Reader is null, "Explicit close could not bypass minimizing.");
            Require(!compact.IsVisible, "Closed Reader left the compact controller behind.");
            _serviceCenter.Dispose();
            Require(ReaderTrayIcon.LiveInstances == 0, "Host disposal left a tray icon behind.");
            _instance.Dispose();
            Require(ReaderInstanceChannel.TryAcquire(scope, out var nextOwner), "Exited owner retained its lock.");
            nextOwner!.Dispose();
            File.WriteAllText(marker, JsonSerializer.Serialize(new
            {
                rendered = true,
                one_tray = true,
                reader_closed = true,
                secondary_activation = true,
                fresh_reader = true,
                unsaved_preserved = true,
                dialog_guard = true,
                minimize_restored = true,
                settings_reloaded = true,
                tray_disposed = true,
                ownership_released = true,
                isolated_settings = true,
                live_service_untouched = true,
                background_hidden = true,
                compact_closed = true,
            }));
            Shutdown();
        }
        catch (Exception exception)
        {
            File.WriteAllText(marker, JsonSerializer.Serialize(new { failed = exception.GetType().Name, message = exception.Message, detail = exception.StackTrace }));
            Shutdown(1);
        }
    }
}

public partial class MainWindow
{
    internal bool HasLifecycleSmokeEdit => _editor?.HasUnsavedChanges == true;

    internal void PrepareLifecycleSmokeEdit()
    {
        if (!_smokeTest) throw new InvalidOperationException("Synthetic edits require smoke mode.");
        var client = DispatchProxy.Create<IReaderServiceClient, FolderVisibilitySmokeClient>();
        _editor = new DocumentEditor(client);
        var now = DateTimeOffset.UtcNow;
        var metadata = JsonSerializer.SerializeToElement(new { });
        var document = new ReaderDocument("lifecycle-test", "Synthetic article", "plain_text", null, null, null,
            null, "inbox", now, now, now, null, 1, 1, 1, 1, 10, metadata);
        _editor.LoadBlock(document, new ReaderBlock("test-block", document.Id, null, 0, "paragraph", "Test story", 10, "hash", 1, metadata));
        _editor.SetWorkingText("Unsaved synthetic edit");
    }

    internal void ClearLifecycleSmokeEdit() => _editor?.RevertLocalChanges();
}
