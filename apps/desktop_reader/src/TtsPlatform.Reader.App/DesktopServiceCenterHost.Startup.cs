using System.IO;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

internal sealed partial class DesktopServiceCenterHost
{
    private UserStartupRegistration? _startupRegistration;
    private bool _startupBusy;
    private bool _autostartAttempted;

    private void EnsureStartupRegistration()
    {
        if (_startupRegistration is not null || _isolatedSmoke) return;
        var executable = Path.Combine(AppContext.BaseDirectory, "TtsPlatform.Reader.App.exe");
        _startupRegistration = new UserStartupRegistration(new WindowsUserStartupTasks(), executable,
            UserStartupRegistration.CurrentUserSid(), path => File.Exists(path) &&
                File.Exists(Path.Combine(Path.GetDirectoryName(path)!, "coreclr.dll")) &&
                ScheduledServiceController.FindLocalServiceLauncher(AppContext.BaseDirectory) is not null,
            findLegacyStartup: new LegacyServiceTasks(AppContext.BaseDirectory,
                UserStartupRegistration.CurrentUserSid(), 7777).ReadStartupConflicts);
    }

    private async Task RefreshStartupAsync()
    {
        if (_disposed || _startupBusy) return;
        _startupBusy = true;
        try
        {
            EnsureStartupRegistration();
            ShowStartupState();
            if (_startupRegistration is not null) await _startupRegistration.ReadAsync(_monitorLifetime.Token);
        }
        catch (OperationCanceledException) when (_monitorLifetime.IsCancellationRequested) { }
        finally { _startupBusy = false; ShowStartupState(); }
    }

    private void ShowStartupState()
    {
        if (_disposed) return;
        var state = _startupRegistration?.State ?? new UserStartupState(false, false, false,
            "Off · Isolated preview. No Windows startup registration is read or changed.");
        DashboardWindow?.ShowStartup(state, _startupRegistration?.TaskName ?? "Not connected", _startupBusy);
    }

    private async Task ChangeStartupAsync(bool enabled)
    {
        if (_disposed || _startupBusy || _isolatedSmoke) { ShowStartupState(); return; }
        _startupBusy = true;
        try
        {
            EnsureStartupRegistration();
            ShowStartupState();
            await _startupRegistration!.SetEnabledAsync(enabled, _monitorLifetime.Token);
        }
        catch (OperationCanceledException) when (_monitorLifetime.IsCancellationRequested) { }
        finally { _startupBusy = false; ShowStartupState(); }
    }

    private async void OpenStartupSettingsRequested(object? sender, EventArgs e)
    {
        await OpenServiceCenterAsync();
        DashboardWindow?.OpenStartupPage();
    }

    internal async Task RunAutostartAsync()
    {
        if (_disposed || _exiting || _autostartAttempted || (_isolatedSmoke && _startupRegistration is null)) return;
        _autostartAttempted = true;
        await RefreshStartupAsync();
        // The command-line flag never enables the option. A matching registration
        // for this user/installation must actually be enabled in Windows first.
        if (_startupRegistration?.State is not { Enabled: true, CanEnable: true })
        {
            if (_startupRegistration?.State.Enabled != false) StartupNotice();
            return;
        }
        if (_operationPending) return;
        _operationPending = true;
        _monitorTimer?.Stop();
        try
        {
            await _monitorGate.WaitAsync(_monitorLifetime.Token);
            try
            {
                await EnsureCoordinatorAsync();
                if (_coordinator is null) return;
                await _coordinator.RefreshAsync(_monitorLifetime.Token);
                if (_coordinator.Dashboard.State is LocalServiceState.Ready or LocalServiceState.Busy) return;
                if (_coordinator.Dashboard.State == LocalServiceState.Stopped)
                {
                    var result = await _coordinator.ExecuteAsync(LocalServiceCommand.Start,
                        () => Task.FromResult(false), _monitorLifetime.Token);
                    if (result.Succeeded)
                    {
                        if (Reader is { } reader) await reader.RefreshAfterLocalServiceCommandAsync(_coordinator.Dashboard);
                        return;
                    }
                }
                StartupNotice();
            }
            finally { _monitorGate.Release(); }
        }
        catch (OperationCanceledException) when (_monitorLifetime.IsCancellationRequested) { }
        catch (Exception exception) when (LocalServiceCoordinator.IsExpected(exception)) { StartupNotice(); }
        finally { _operationPending = false; RenderDashboard(); ScheduleNextCheck(); }
    }

    private void StartupNotice()
    {
        if (!_isolatedSmoke && !_disposed)
            _tray?.ShowServiceNotice("TTS startup needs attention", "Open Service Center from the tray to check local service access and Windows startup. No second or unverified service was started.");
    }

    internal void ConfigureIsolatedAutostart(UserStartupRegistration registration, LocalServiceCoordinator coordinator)
    {
        if (!_isolatedSmoke) throw new InvalidOperationException("Synthetic startup requires isolated smoke mode.");
        _startupRegistration = registration;
        _coordinator = coordinator;
        _coordinator.Changed += CoordinatorChanged;
        _localEndpoint = "Isolated startup fixture";
    }
}
