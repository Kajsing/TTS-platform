using System.ComponentModel;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.App;

public partial class ServiceCenterWindow
{
    internal event EventHandler? VoicesOpened;
    internal event EventHandler? VoicesRefreshRequested;
    internal event EventHandler<VoiceLibraryPackage>? VoiceInstallRequested;
    internal event EventHandler? VoiceCancelRequested;
    internal event EventHandler<InstalledLibraryVoice>? VoiceDefaultRequested;
    internal event EventHandler<InstalledLibraryVoice>? VoicePreviewRequested;
    internal event EventHandler? VoicePreviewStopRequested;
    private bool _previewBusy;
    internal Func<InstalledLibraryVoice, bool>? ConfirmDefaultForSmoke { get; set; }
    private VoiceLibraryController? _voices;
    private VoiceLibraryInventory? _displayedInventory;
    private bool _voicesOpened;

    private void ServicePages_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (e.Source != ServicePages || VoicesPage is null || ServicePages.SelectedItem != VoicesPage || _voicesOpened) return;
        _voicesOpened = true;
        VoicesOpened?.Invoke(this, EventArgs.Empty);
    }

    internal void ShowVoiceLibrary(VoiceLibraryController controller)
    {
        _voices = controller;
        if (!controller.IsBusy && _voiceCommandMessage)
        {
            _voiceCommandMessage = false;
            CommandMessage.Visibility = Visibility.Collapsed;
        }
        if (!ReferenceEquals(_displayedInventory, controller.Inventory))
        {
            _displayedInventory = controller.Inventory;
            AcceptVoiceLicenseCheckBox.IsChecked = false;
            InstalledVoiceList.ItemsSource = controller.Inventory?.InstalledVoices;
            VoicePackageList.ItemsSource = controller.Inventory?.Packages;
        }
        var inventory = controller.Inventory;
        InstalledVoiceSummary.Text = inventory is null ? "No current inventory. Use Refresh library to retry." :
            $"{inventory.InstalledVoices.Count} installed voices · Configured service default: {inventory.ConfiguredDefault ?? "unknown"}. Reader's own voice preference is separate.";
        VoiceLibraryMessage.Text = controller.Message;
        RefreshVoicesButton.IsEnabled = !controller.IsBusy && !_previewBusy;
        VoicePackageList.IsEnabled = !controller.IsBusy && !_previewBusy;
        InstalledVoiceList.IsEnabled = !controller.IsBusy && !_previewBusy;
        VoiceInstallProgressPanel.Visibility = controller.IsInstalling ? Visibility.Visible : Visibility.Collapsed;
        VoiceInstallProgressText.Text = controller.CancelRequested ? "Waiting for safe cancellation or commit…" : controller.Progress?.Display ?? "Starting installer…";
        VoiceInstallProgressBar.IsIndeterminate = controller.Progress?.Percent is null;
        VoiceInstallProgressBar.Value = controller.Progress?.Percent ?? 0;
        CancelVoiceInstallButton.IsEnabled = controller.CanCancel;
        RenderPackageReview();
        RenderInstalledSelection();
    }

    private void InstalledVoice_SelectionChanged(object sender, SelectionChangedEventArgs e) => RenderInstalledSelection();
    private void RenderInstalledSelection()
    {
        if (SetServiceDefaultButton is null) return;
        SetServiceDefaultButton.IsEnabled = !_previewBusy && _voices?.CanSetDefault((InstalledVoiceList.SelectedItem as InstalledLibraryVoice)?.Id) == true;
        PreviewVoiceButton.IsEnabled = !_previewBusy && _voices is { IsBusy: false } &&
            InstalledVoiceList.SelectedItem is InstalledLibraryVoice { AssetsPresent: true };
    }
    internal void ShowVoicePreview(string message, bool busy, bool cancellationRequested = false)
    {
        _previewBusy = busy;
        VoicePreviewMessage.Text = message;
        StopVoicePreviewButton.IsEnabled = busy && !cancellationRequested;
        if (_voices is not null) ShowVoiceLibrary(_voices);
    }
    private void PreviewVoice_Click(object sender, RoutedEventArgs e)
    {
        if (PreviewVoiceButton.IsEnabled && InstalledVoiceList.SelectedItem is InstalledLibraryVoice voice)
            VoicePreviewRequested?.Invoke(this, voice);
    }
    private void StopVoicePreview_Click(object sender, RoutedEventArgs e) => VoicePreviewStopRequested?.Invoke(this, EventArgs.Empty);
    private void SetServiceDefault_Click(object sender, RoutedEventArgs e)
    {
        if (!SetServiceDefaultButton.IsEnabled || InstalledVoiceList.SelectedItem is not InstalledLibraryVoice voice) return;
        var confirmed = ConfirmDefaultForSmoke?.Invoke(voice) ?? MessageBox.Show(this,
            $"Save {voice.Name} as this computer's service default?\n\nThis does not change running speech or Reader's own voice preference. Use Restart service explicitly when idle to apply the saved default.",
            "Service default for next restart", MessageBoxButton.OKCancel, MessageBoxImage.Information, MessageBoxResult.Cancel) == MessageBoxResult.OK;
        if (confirmed) VoiceDefaultRequested?.Invoke(this, voice);
    }

    internal void OpenVoicesPage() => ServicePages.SelectedItem = VoicesPage;
    private void RefreshVoices_Click(object sender, RoutedEventArgs e)
    {
        AcceptVoiceLicenseCheckBox.IsChecked = false;
        VoicesRefreshRequested?.Invoke(this, EventArgs.Empty);
    }
    private void CancelVoiceInstall_Click(object sender, RoutedEventArgs e) => VoiceCancelRequested?.Invoke(this, EventArgs.Empty);
    private void Package_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        AcceptVoiceLicenseCheckBox.IsChecked = false;
        RenderPackageReview();
        if (VoicePackageList.SelectedItem is { } selected) VoicePackageList.ScrollIntoView(selected);
    }
    private void License_Checked(object sender, RoutedEventArgs e) => RenderPackageReview();

    private void RenderPackageReview()
    {
        if (SelectedPackageTitle is null) return; // XAML initialization raises selection events.
        var package = VoicePackageList.SelectedItem as VoiceLibraryPackage;
        SelectedPackageTitle.Text = package?.Name ?? "Select a package to review its license and source.";
        SelectedPackageLicense.Text = package is null ? "" : $"License: {package.License} · {package.SizeLabel}";
        PackageLicenseButton.IsEnabled = SafeWebUri(package?.LicenseUrl) is not null;
        PackageSourceButton.IsEnabled = SafeWebUri(package?.SourceUrl) is not null;
        AcceptVoiceLicenseCheckBox.IsEnabled = package?.CanInstall == true && _voices?.IsBusy != true && !_previewBusy;
        InstallVoiceButton.IsEnabled = AcceptVoiceLicenseCheckBox.IsEnabled && AcceptVoiceLicenseCheckBox.IsChecked == true;
    }

    private void InstallVoice_Click(object sender, RoutedEventArgs e)
    {
        if (InstallVoiceButton.IsEnabled && VoicePackageList.SelectedItem is VoiceLibraryPackage package)
            VoiceInstallRequested?.Invoke(this, package);
    }
    private void PackageLicense_Click(object sender, RoutedEventArgs e) => OpenPackageLink((VoicePackageList.SelectedItem as VoiceLibraryPackage)?.LicenseUrl);
    private void PackageSource_Click(object sender, RoutedEventArgs e) => OpenPackageLink((VoicePackageList.SelectedItem as VoiceLibraryPackage)?.SourceUrl);
    private static Uri? SafeWebUri(string? value) => Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
        uri.Scheme is "https" or "http" && string.IsNullOrEmpty(uri.UserInfo) && !string.IsNullOrEmpty(uri.Host) ? uri : null;
    private void OpenPackageLink(string? value)
    {
        if (SafeWebUri(value) is not { } uri) return;
        try { Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true }); }
        catch (Exception exception) when (exception is Win32Exception or InvalidOperationException)
        { VoiceLibraryMessage.Text = "The browser could not open this source. Check your default browser settings."; }
    }
}
