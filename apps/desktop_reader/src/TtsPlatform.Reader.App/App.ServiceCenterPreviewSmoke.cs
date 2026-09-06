using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class App
{
    private async Task VerifyIsolatedVoicePreviewAsync(DesktopServiceCenterHost host, string root)
    {
        static void Require(bool condition, string message)
        { if (!condition) throw new InvalidOperationException(message); }
        async Task Until(Func<bool> ready)
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            while (!ready())
            {
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                await Task.Delay(10, timeout.Token);
            }
        }
        static void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        var fixture = new VoicePreviewSmokeFixture();
        host.ConfigureIsolatedVoicePreview(new(fixture, () => fixture));
        var reader = host.Reader!;
        await host.OpenServiceCenterAsync();
        var panel = host.DashboardWindow!;
        panel.OpenVoicesPage();
        panel.InstalledVoiceList.SelectedIndex = 1;
        Require(panel.PreviewVoiceButton.IsEnabled, "Installed voice preview was not available.");
        Click(panel.PreviewVoiceButton);
        await Until(() => fixture.Plays == 1);
        Require(panel.StopVoicePreviewButton.IsEnabled && !panel.PreviewVoiceButton.IsEnabled &&
            !panel.RefreshVoicesButton.IsEnabled && !panel.SetServiceDefaultButton.IsEnabled &&
            !reader.IsEnabled && reader.HasLifecycleSmokeEdit, "Preview lost its exclusive UI guard or unsaved edit.");
        Require(!await host.ExitAsync(confirm: false) && !await reader.CloseReaderAsync(),
            "Reader/host closed before preview audio was stopped.");
        await host.OpenReaderAsync();
        Require(host.Reader == reader, "Preview opened another Reader.");
        panel.UpdateLayout();
        var image = new RenderTargetBitmap((int)panel.ActualWidth, (int)panel.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        image.Render(panel);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(image));
        using (var file = File.Create(Path.Combine(root, "service-center-voice-preview.png"))) encoder.Save(file);
        Click(panel.StopVoicePreviewButton);
        await Until(() => reader.IsEnabled);
        Require(fixture.Stops == 1 && fixture.Disposals == 1 && fixture.Releases == 1 &&
            panel.PreviewVoiceButton.IsEnabled && !panel.StopVoicePreviewButton.IsEnabled && reader.HasLifecycleSmokeEdit,
            "Stop preview did not release audio/reservation and restore the draft.");
        Click(panel.PreviewVoiceButton);
        await Until(() => fixture.Plays == 2);
        panel.Close();
        await Until(() => reader.IsEnabled);
        Require(fixture.Stops == 2 && fixture.Disposals == 2 && fixture.Releases == 2 && reader.HasLifecycleSmokeEdit,
            "Closing the preview panel left audio running or changed the Reader draft.");
        await host.OpenServiceCenterAsync();
        panel = host.DashboardWindow!;
        panel.OpenVoicesPage();
        Require(panel.RefreshVoicesButton.IsEnabled && !panel.StopVoicePreviewButton.IsEnabled,
            "Reopened preview retained busy controls after cancellation.");
        panel.Close();
    }
}

internal sealed class VoicePreviewSmokeFixture : ILocalVoicePreviewClient, IVoicePreviewAudio
{
    internal int Plays, Stops, Disposals, Releases;
    public Task<LocalServiceStatus> GetLocalStatusAsync(CancellationToken token) => Task.FromResult(new LocalServiceStatus(
        1, "preview-fixture", true, true, "unchanged", "Unchanged", 2, 10, true,
        new(0, 0, 0, 0, 0), false, new("service_process", 42, 0, 1, 4, 1024)));
    public Task<ServiceMaintenanceReservation> ReserveMaintenanceAsync(string instance, CancellationToken token) =>
        Task.FromResult(new ServiceMaintenanceReservation("preview-smoke-lease", 15));
    public Task<ServiceMaintenanceRelease> ReleaseMaintenanceAsync(string reservation, CancellationToken token)
    {
        if (Stops != Plays || Disposals != Plays) throw new InvalidOperationException("Audio must stop before reservation release.");
        Releases++;
        return Task.FromResult(new ServiceMaintenanceRelease(true));
    }
    public Task<byte[]> RenderVoicePreviewAsync(string reservation, string voice, CancellationToken token)
    {
        if (voice != "piper") throw new InvalidOperationException("Preview did not use the explicitly selected voice.");
        return Task.FromResult<byte[]>([1, 2, 3]);
    }
    public TimeSpan Load(ReadOnlyMemory<byte> wave) => TimeSpan.FromSeconds(1);
    public async Task PlayAsync(CancellationToken token) { Plays++; await Task.Delay(Timeout.Infinite, token); }
    public Task StopAsync() { Stops++; return Task.CompletedTask; }
    public ValueTask DisposeAsync() { Disposals++; return ValueTask.CompletedTask; }
}

public partial class MainWindow
{
    internal void VerifyPreviewReaderGuards()
    {
        if (!_smokeTest) throw new InvalidOperationException("Preview guards require isolated smoke mode.");
        void Refused()
        {
            if (TryBeginVoicePreview() is null || !IsEnabled || !HasLifecycleSmokeEdit)
                throw new InvalidOperationException("Preview must not interrupt Reader work or discard a draft.");
        }
        _ephemeralPlaying = true;
        try { Refused(); } finally { _ephemeralPlaying = false; }
        _ephemeralReplayText = "Synthetic paused clipboard speech";
        try { Refused(); } finally { _ephemeralReplayText = null; }
        _audioInterruptionActive = true;
        try { Refused(); } finally { _audioInterruptionActive = false; }
        var dialog = new Window { Owner = this, Width = 200, Height = 120, Title = "Preview guard fixture" };
        dialog.Show();
        try { Refused(); } finally { dialog.Close(); }
    }
}
