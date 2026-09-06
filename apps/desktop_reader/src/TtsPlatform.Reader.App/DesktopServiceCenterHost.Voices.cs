using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

internal sealed partial class DesktopServiceCenterHost
{
    private VoiceLibraryController? _voices;

    private void WireVoiceLibrary(ServiceCenterWindow panel)
    {
        panel.VoicesOpened += async (_, _) =>
        {
            if (!_isolatedSmoke && _voices?.Inventory is null) await RefreshVoicesAsync();
        };
        panel.VoicesRefreshRequested += async (_, _) => await RefreshVoicesAsync();
        panel.VoiceInstallRequested += async (_, package) =>
        {
            if (_disposed || _operationPending || _voices is null) return;
            await _voices.InstallAsync(package.Id, panel.AcceptVoiceLicenseCheckBox.IsChecked == true);
        };
        panel.VoiceCancelRequested += (_, _) => _voices?.Cancel();
        panel.VoiceDefaultRequested += async (_, voice) =>
        {
            if (_disposed || _operationPending || _voices is null) return;
            await _voices.SetDefaultAsync(voice.Id);
        };
        if (_voices is not null) panel.ShowVoiceLibrary(_voices);
    }

    private async Task RefreshVoicesAsync()
    {
        if (_disposed || _operationPending || _isolatedSmoke && _voices is null) return;
        if (_voices is null)
        {
            _voices = new VoiceLibraryController(new LocalVoiceLibrary());
            _voices.Changed += VoiceLibraryChanged;
        }
        await _voices.RefreshAsync();
    }

    private void VoiceLibraryChanged(object? sender, EventArgs e)
    {
        if (_disposed || _voices is null) return;
        DashboardWindow?.ShowVoiceLibrary(_voices);
        RenderDashboard();
    }

    internal void ConfigureIsolatedVoices(ILocalVoiceLibrary library)
    {
        if (!_isolatedSmoke) throw new InvalidOperationException("Voice fixture requires isolated smoke mode.");
        if (_voices is not null) _voices.Changed -= VoiceLibraryChanged;
        _voices = new VoiceLibraryController(library);
        _voices.Changed += VoiceLibraryChanged;
    }
}
