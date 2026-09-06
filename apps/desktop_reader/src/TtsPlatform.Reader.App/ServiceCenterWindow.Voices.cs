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
        RefreshVoicesButton.IsEnabled = !controller.IsBusy;
        VoicePackageList.IsEnabled = !controller.IsBusy;
        VoiceInstallProgressPanel.Visibility = controller.IsInstalling ? Visibility.Visible : Visibility.Collapsed;
        VoiceInstallProgressText.Text = controller.CancelRequested ? "Waiting for safe cancellation or commit…" : controller.Progress?.Display ?? "Starting installer…";
        VoiceInstallProgressBar.IsIndeterminate = controller.Progress?.Percent is null;
        VoiceInstallProgressBar.Value = controller.Progress?.Percent ?? 0;
        CancelVoiceInstallButton.IsEnabled = controller.CanCancel;
        RenderPackageReview();
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
        AcceptVoiceLicenseCheckBox.IsEnabled = package?.CanInstall == true && _voices?.IsBusy != true;
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
