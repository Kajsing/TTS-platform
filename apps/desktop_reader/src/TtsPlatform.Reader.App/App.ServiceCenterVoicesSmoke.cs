using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class App
{
    private async Task VerifyIsolatedVoiceLibraryAsync(DesktopServiceCenterHost host, string root)
    {
        static void Require(bool condition, string message)
        { if (!condition) throw new InvalidOperationException(message); }
        async Task Idle() => await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        static void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        static void Available(ServiceCenterWindow panel) => ((TabControl)panel.AvailableVoicesPage.Parent).SelectedItem = panel.AvailableVoicesPage;
        static void Capture(ServiceCenterWindow panel, string path)
        {
            panel.UpdateLayout();
            var image = new RenderTargetBitmap((int)panel.ActualWidth, (int)panel.ActualHeight, 96, 96, PixelFormats.Pbgra32);
            image.Render(panel);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(image));
            using var file = File.Create(path);
            encoder.Save(file);
        }
        var fixture = new VoiceLibrarySmokeFixture();
        host.ConfigureIsolatedVoices(fixture);
        await host.OpenServiceCenterAsync();
        var panel = host.DashboardWindow!;
        var opened = 0;
        panel.VoicesOpened += (_, _) => opened++;
        panel.OpenVoicesPage();
        Require(opened == 1, "Selecting the voice tab did not request its initial inventory.");
        Click(panel.RefreshVoicesButton);
        await Idle();
        Require(panel.InstalledVoiceList.Items.Count == 2 && panel.VoicePackageList.Items.Count == 2,
            "Installed voices and available packages were not separated.");
        panel.InstalledVoiceList.SelectedIndex = 0;
        Require(!panel.SetServiceDefaultButton.IsEnabled, "Already configured voice offered a redundant save.");
        panel.InstalledVoiceList.SelectedIndex = 1;
        Require(panel.SetServiceDefaultButton.IsEnabled, "Installed alternative cannot be saved as default.");
        panel.ConfirmDefaultForSmoke = _ => false;
        Click(panel.SetServiceDefaultButton);
        Require(fixture.Defaults == 0, "Cancelling default confirmation changed a setting.");
        panel.ConfirmDefaultForSmoke = _ => true;
        Click(panel.SetServiceDefaultButton);
        await Idle();
        Require(fixture.Defaults == 1 && !panel.SetServiceDefaultButton.IsEnabled && !panel.RefreshVoicesButton.IsEnabled,
            "Default save did not retain serialized ownership.");
        Require(!await host.ExitAsync(confirm: false), "Tray exited during a default commit.");
        fixture.DefaultCompletion.SetResult();
        await Idle();
        Require(panel.RefreshVoicesButton.IsEnabled && panel.CommandMessage.Visibility == Visibility.Collapsed &&
            panel.VoiceLibraryMessage.Text.Contains("next explicit restart"),
            "Saved default was not labeled as deferred activation.");
        Capture(panel, Path.Combine(root, "service-center-voices-installed.png"));
        Available(panel);
        panel.VoicePackageList.SelectedIndex = 0;
        Require(!panel.AcceptVoiceLicenseCheckBox.IsEnabled && !panel.InstallVoiceButton.IsEnabled,
            "Existing package was offered for overwrite.");
        panel.VoicePackageList.SelectedIndex = 1;
        Require(panel.AcceptVoiceLicenseCheckBox.IsEnabled && !panel.InstallVoiceButton.IsEnabled,
            "New package did not require license review.");
        panel.AcceptVoiceLicenseCheckBox.IsChecked = true;
        panel.VoicePackageList.SelectedIndex = 0;
        panel.VoicePackageList.SelectedIndex = 1;
        Require(panel.AcceptVoiceLicenseCheckBox.IsChecked == false, "License acceptance leaked across selections.");
        await Idle();
        Capture(panel, Path.Combine(root, "service-center-voices-packages.png"));
        var normalHeight = panel.Height;
        panel.Height = panel.MinHeight;
        await Idle();
        Capture(panel, Path.Combine(root, "service-center-voices-small.png"));
        panel.VoicePageScrollViewer.ScrollToBottom();
        await Idle();
        Require(panel.InstallVoiceButton.TranslatePoint(new Point(0, panel.InstallVoiceButton.ActualHeight), panel).Y <
            panel.StartButton.TranslatePoint(new Point(), panel).Y,
            "The install action cannot be reached above the footer in a small window.");
        Capture(panel, Path.Combine(root, "service-center-voices-small-scrolled.png"));
        panel.VoicePageScrollViewer.ScrollToTop();
        panel.Height = normalHeight;
        await Idle();
        panel.AcceptVoiceLicenseCheckBox.IsChecked = true;
        Click(panel.InstallVoiceButton);
        await Idle();
        Require(fixture.Installs == 1 && panel.VoiceInstallProgressPanel.IsVisible && panel.VoiceInstallProgressBar.Value == 50 &&
            !panel.InstallVoiceButton.IsEnabled && !panel.RefreshVoicesButton.IsEnabled, "Installation progress or duplicate guards failed.");
        Require(panel.VoiceLibraryMessage.Foreground is SolidColorBrush foreground &&
            foreground.Color == ((SolidColorBrush)panel.FindResource("TextBrush")).Color,
            "Voice tab header leaked its white foreground into content.");
        Capture(panel, Path.Combine(root, "service-center-voices-progress.png"));
        panel.Close();
        Require(!fixture.Token.IsCancellationRequested && ReaderTrayIcon.LiveInstances == 1, "Closing the panel lost or cancelled its installer.");
        await host.OpenServiceCenterAsync();
        panel = host.DashboardWindow!;
        panel.OpenVoicesPage();
        await Idle();
        Require(panel.VoiceInstallProgressPanel.IsVisible && panel.VoiceInstallProgressBar.Value == 50,
            "Reopened voice panel lost current progress.");
        Require(!await host.ExitAsync(confirm: false), "Tray host exited while the installer was alive.");
        Click(panel.CancelVoiceInstallButton);
        Require(fixture.Token.IsCancellationRequested && !panel.CancelVoiceInstallButton.IsEnabled &&
            !panel.RefreshVoicesButton.IsEnabled, "Cancel released ownership before helper exit.");
        fixture.Completion.SetResult(new(false, true, "Synthetic installation cancelled safely."));
        await Idle();
        Require(panel.RefreshVoicesButton.IsEnabled && panel.VoiceInstallProgressPanel.Visibility == Visibility.Collapsed &&
            fixture.Lists == 3, "Terminal helper result did not refresh actual inventory and release controls.");
        panel.Close();
    }
}

internal sealed class VoiceLibrarySmokeFixture : ILocalVoiceLibrary
{
    internal int Lists;
    internal int Installs;
    internal int Defaults;
    internal readonly TaskCompletionSource DefaultCompletion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    internal CancellationToken Token;
    internal readonly TaskCompletionSource<VoiceInstallationOutcome> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public Task<VoiceLibraryInventory> ListAsync(CancellationToken cancellationToken)
    {
        Lists++;
        return Task.FromResult(new VoiceLibraryInventory(new string('a', 64), new string('b', 64), "kokoro", true,
            [new("kokoro", "Kokoro English · af_heart", "en-US", "kokoro", "Apache-2.0", "fixture", true, true),
             new("piper", "Piper English · Lessac", "en-US", "vits", "Voice-specific license", "fixture", true, false)],
            [new("old", "Existing package · synthetic preview", "en-US", "kokoro", 85000000, "Fixture only",
                "https://example.test/license", "https://example.test/source", [new("old", "Existing voice", "en-US")], true, false, "Already installed. Existing files will not be replaced."),
             new("new", "Danish voice package · synthetic preview", "da-DK", "vits", 63000000, "Synthetic fixture only — not a real download",
                "https://example.test/license", "https://example.test/source", [new("new", "Danish voice", "da-DK")], false, true, null)], new string('c', 64)));
    }
    public Task SetDefaultAsync(string voice, string manifest, string config, CancellationToken token)
    {
        if (voice != "piper" || manifest != new string('b', 64) || config != new string('c', 64))
            throw new InvalidOperationException("Default save lost its reviewed configuration/voice.");
        Defaults++;
        return DefaultCompletion.Task;
    }
    public Task<VoiceInstallationOutcome> InstallAsync(string packageId, string fingerprint, bool accepted,
        IProgress<VoiceInstallationProgress> progress, CancellationToken cancellationToken)
    {
        if (packageId != "new" || fingerprint != new string('a', 64) || !accepted)
            throw new InvalidOperationException("Smoke installation lost its reviewed package/license.");
        Token = cancellationToken;
        Installs++;
        progress.Report(new("downloading", 31500000, 63000000, true));
        return Completion.Task;
    }
}
