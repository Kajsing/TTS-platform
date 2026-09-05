using System.IO;
using System.Net.Http;
using System.Windows;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

internal sealed partial class DesktopServiceCenterHost
{
    private readonly CancellationTokenSource _monitorLifetime = new();
    private readonly SemaphoreSlim _monitorGate = new(1, 1);
    private DispatcherTimer? _monitorTimer;
    private HttpClient? _serviceHttp;
    private LocalServiceCoordinator? _coordinator;
    private string _localEndpoint = "Not checked";
    private string? _tokenPath;
    private bool _operationPending;
    private ServiceDashboard? _monitorFailure;
    internal ServiceCenterWindow? DashboardWindow { get; private set; }

    private void InitializeMonitor()
    {
        // Lifecycle smoke may create a real icon, but never contacts live HTTP,
        // reads real settings or launches the production service.
        if (_isolatedSmoke) return;
        _monitorTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        _monitorTimer.Tick += MonitorTick;
        _monitorTimer.Start();
    }

    private async void MonitorTick(object? sender, EventArgs e) => await RefreshMonitorAsync();

    private async Task EnsureCoordinatorAsync()
    {
        if (_isolatedSmoke) return;
        var settings = await _settingsStore.LoadAsync(_monitorLifetime.Token);
        _monitorLifetime.Token.ThrowIfCancellationRequested();
        var endpoint = ServiceBaseUrl.Parse(settings.ServiceBaseUrl);
        var tokenPath = settings.EffectiveTokenSource.Path;
        _monitorFailure = null;
        if (_coordinator is not null && _localEndpoint == endpoint.AbsoluteUri && _tokenPath == tokenPath) return;
        if (_coordinator is not null) _coordinator.Changed -= CoordinatorChanged;
        _serviceHttp?.Dispose();
        _serviceHttp = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false })
        { Timeout = TimeSpan.FromSeconds(4) };
        var client = new ReaderServiceClient(_serviceHttp, endpoint.AbsoluteUri, new FileTokenProvider(tokenPath));
        _coordinator = new LocalServiceCoordinator(client, new LocalServiceProcessControl(endpoint));
        _coordinator.Changed += CoordinatorChanged;
        _localEndpoint = endpoint.AbsoluteUri;
        _tokenPath = tokenPath;
    }

    private async Task RefreshMonitorAsync()
    {
        if (_disposed || _operationPending || !await _monitorGate.WaitAsync(0)) return;
        _monitorTimer?.Stop();
        try
        {
            await EnsureCoordinatorAsync();
            if (_coordinator is not null) await _coordinator.RefreshAsync(_monitorLifetime.Token);
            RenderDashboard();
        }
        catch (OperationCanceledException) when (_monitorLifetime.IsCancellationRequested) { }
        catch (Exception exception) when (LocalServiceCoordinator.IsExpected(exception))
        {
            ShowMonitorFailure();
        }
        finally { _monitorGate.Release(); ScheduleNextCheck(); }
    }

    private void ScheduleNextCheck()
    {
        if (_disposed || _monitorTimer is null) return;
        var failed = _monitorFailure is not null || _coordinator is null || _coordinator.Dashboard.State is LocalServiceState.Unreachable or LocalServiceState.AuthenticationRequired;
        _monitorTimer.Interval = ServiceDashboard.PollInterval(DashboardWindow?.IsVisible == true, failed, _coordinator?.IsRateLimited == true);
        _monitorTimer.Start();
    }

    private void ShowMonitorFailure()
    {
        _monitorFailure = new ServiceDashboard(LocalServiceState.Unreachable,
            "Local settings or status could not be read. Check Reader's local connection settings; existing settings were not replaced.");
        RenderDashboard();
    }

    private void CoordinatorChanged(object? sender, EventArgs e) => RenderDashboard();

    private void RenderDashboard()
    {
        if (_disposed) return;
        var value = _monitorFailure ?? _coordinator?.Dashboard ?? new ServiceDashboard(LocalServiceState.Unknown, "No local status sample yet.");
        var operating = _operationPending || _coordinator?.IsOperating == true;
        var limited = _coordinator?.IsRateLimited == true;
        DashboardWindow?.ShowDashboard(value, _monitorFailure is null ? _localEndpoint : "Unavailable", operating, limited,
            _monitorFailure is null ? _coordinator?.LastCheckedAt : null);
        _tray?.SetServiceStatus(value.State.ToString(), !operating && !limited && value.State == LocalServiceState.Stopped,
            !operating && !limited && value.CanRequestMaintenance);
    }

    internal async Task OpenServiceCenterAsync()
    {
        if (_disposed || _exiting) return;
        if (DashboardWindow is null)
        {
            var panel = new ServiceCenterWindow();
            panel.OpenReaderRequested += async (_, _) => await OpenReaderAsync();
            panel.RefreshRequested += async (_, _) => await RefreshMonitorAsync();
            panel.CommandRequested += async (_, command) => await RunServiceCommandAsync(command);
            panel.Closed += (_, _) => { DashboardWindow = null; ScheduleNextCheck(); };
            DashboardWindow = panel;
            RenderDashboard();
            panel.Show();
        }
        else
        {
            DashboardWindow.Show();
            DashboardWindow.WindowState = WindowState.Normal;
        }
        DashboardWindow.Activate();
        await RefreshMonitorAsync();
    }

    private async void OpenServiceCenterRequested(object? sender, EventArgs e) => await OpenServiceCenterAsync();

    internal async Task RunServiceCommandAsync(LocalServiceCommand command)
    {
        if (_disposed || _operationPending) return;
        await OpenServiceCenterAsync();
        if (_isolatedSmoke || _disposed || _operationPending) return;
        _operationPending = true;
        _monitorTimer?.Stop();
        MainWindow? preparedReader = null;
        try
        {
            await _monitorGate.WaitAsync(_monitorLifetime.Token);
            try
            {
                await EnsureCoordinatorAsync();
                RenderDashboard();
                var result = await _coordinator!.ExecuteAsync(command, async () =>
                {
                    if (DashboardWindow is not { } panel) return false;
                    var verb = command == LocalServiceCommand.Restart ? "Restart" : "Stop";
                    if (MessageBox.Show(panel,
                        $"{verb} this computer's local TTS service?\n\nLocal Reader playback, including paused audio, will be stopped. Unsaved text is kept. Active imports and exports must finish first. Remote workspaces are not controlled here.",
                        $"{verb} local service", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return false;
                    preparedReader = Reader;
                    return preparedReader is null || await preparedReader.PrepareLocalServiceOperationAsync();
                }, _monitorLifetime.Token);
                DashboardWindow?.ShowCommandMessage(result.Message);
                if (result.Succeeded && Reader is { } reader)
                    await reader.RefreshAfterLocalServiceCommandAsync(_coordinator.Dashboard);
            }
            finally { _monitorGate.Release(); }
        }
        catch (OperationCanceledException) when (_monitorLifetime.IsCancellationRequested) { }
        catch (Exception exception) when (LocalServiceCoordinator.IsExpected(exception)) { ShowMonitorFailure(); }
        finally
        {
            preparedReader?.EndLocalServiceOperation();
            _operationPending = false;
            RenderDashboard();
            ScheduleNextCheck();
        }
    }

    private void DisposeMonitor()
    {
        _monitorLifetime.Cancel();
        _monitorTimer?.Stop();
        if (_monitorTimer is not null) _monitorTimer.Tick -= MonitorTick;
        if (_coordinator is not null) _coordinator.Changed -= CoordinatorChanged;
        DashboardWindow?.Close();
        _serviceHttp?.Dispose();
        // In-flight awaited requests still observe the cancellation token.
    }
}
