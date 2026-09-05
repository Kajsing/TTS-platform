using System.Windows;
using System.Windows.Media;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class ServiceCenterWindow : Window
{
    internal event EventHandler<LocalServiceCommand>? CommandRequested;
    internal event EventHandler? RefreshRequested;
    internal event EventHandler? OpenReaderRequested;
    internal event EventHandler<bool>? StartupChangeRequested;
    internal event EventHandler? StartupRefreshRequested;
    private bool? _startupEnabled;
    public ServiceCenterWindow()
    {
        InitializeComponent();
        Height = Math.Min(Height, Math.Max(MinHeight, SystemParameters.WorkArea.Height - 40));
        Width = Math.Min(Width, Math.Max(MinWidth, SystemParameters.WorkArea.Width - 40));
    }

    internal void OpenStartupPage() => ServicePages.SelectedItem = WindowsStartupPage;

    internal void ShowStartup(UserStartupState state, string taskName, bool busy)
    {
        _startupEnabled = state.Enabled;
        WindowsStartupCheckBox.IsChecked = state.Enabled;
        WindowsStartupCheckBox.IsEnabled = !busy && (state.Enabled == true ? state.CanDisable : state.CanEnable);
        WindowsStartupStatus.Text = busy ? "Reading or updating the Windows registration…" : state.Message;
        WindowsStartupTaskName.Text = "Windows task · " + taskName;
        RefreshStartupButton.IsEnabled = !busy;
    }

    private void Startup_Click(object sender, RoutedEventArgs e) => StartupChangeRequested?.Invoke(this, _startupEnabled != true);
    private void RefreshStartup_Click(object sender, RoutedEventArgs e) => StartupRefreshRequested?.Invoke(this, EventArgs.Empty);

    internal void ShowDashboard(ServiceDashboard value, string endpoint, bool operating, bool rateLimited, DateTimeOffset? checkedAt)
    {
        StateText.Text = value.State switch
        {
            LocalServiceState.Ready => "Ready to read",
            LocalServiceState.Busy => "Working",
            LocalServiceState.Degraded => "Needs attention",
            LocalServiceState.Stopped => "Service stopped",
            LocalServiceState.Starting => "Starting service",
            LocalServiceState.Maintenance => "Maintenance",
            LocalServiceState.AuthenticationRequired => "Check local access",
            LocalServiceState.Unreachable => "Status unavailable",
            _ => "Checking service",
        };
        StateDot.Fill = new SolidColorBrush(value.State switch
        {
            LocalServiceState.Ready => Color.FromRgb(26, 128, 94),
            LocalServiceState.Busy => Color.FromRgb(35, 119, 122),
            LocalServiceState.Stopped => Color.FromRgb(101, 113, 125),
            _ => Color.FromRgb(169, 109, 13),
        });
        StatusMessage.Text = value.Message;
        EndpointText.Text = "Local endpoint · " + endpoint;
        CpuText.Text = value.CpuPercent is { } cpu ? $"{cpu:N1}%" : "—";
        RamText.Text = value.WorkingSetMiB is { } ram ? $"{ram:N0} MiB" : "—";
        var status = value.Status;
        UptimeText.Text = status is null ? "—" : FormatUptime(status.UptimeS);
        VoiceText.Text = status?.DefaultVoiceName ?? status?.DefaultVoiceId ?? "Unavailable";
        ReadinessText.Text = status is null ? "Voice and library readiness are unknown." :
            $"{status.VoiceCount} installed voices · Engine {(status.BackendReady ? "ready" : "not ready")} · Voice {(status.DefaultVoiceLoaded ? "loaded" : "not loaded")} · Library {(status.ReaderReady ? "ready" : "not ready")}";
        RequestsText.Text = status?.Activity.ActiveRequests.ToString() ?? "—";
        StreamsText.Text = status?.Activity.ActiveStreams.ToString() ?? "—";
        LeasesText.Text = status?.Activity.ContentLeases.ToString() ?? "—";
        ExportsText.Text = status?.Activity.PendingExports.ToString() ?? "—";
        JobsText.Text = status?.Activity.PendingJobs.ToString() ?? "—";
        SampleText.Text = (checkedAt is { } at ? $"Last checked {at.ToLocalTime():HH:mm:ss}. " : "No sample yet. ") +
            (rateLimited ? "Waiting before retrying." : "Checks slow down while this panel is closed.");
        StartButton.IsEnabled = !operating && !rateLimited && value.State == LocalServiceState.Stopped;
        StopButton.IsEnabled = RestartButton.IsEnabled = !operating && !rateLimited && value.CanRequestMaintenance;
        RefreshStatusButton.IsEnabled = !operating && !rateLimited;
    }

    private static string FormatUptime(long seconds)
    {
        // Avoid TimeSpan overflow for malformed, but nonnegative, wire values.
        if (seconds >= 86400) return $"{seconds / 86400:N0}d {seconds % 86400 / 3600}h";
        return $"{seconds / 3600:00}:{seconds % 3600 / 60:00}:{seconds % 60:00}";
    }
    internal void ShowCommandMessage(string message)
    { CommandMessage.Text = message; CommandMessage.Visibility = Visibility.Visible; }
    private void Start_Click(object sender, RoutedEventArgs e) => CommandRequested?.Invoke(this, LocalServiceCommand.Start);
    private void Stop_Click(object sender, RoutedEventArgs e) => CommandRequested?.Invoke(this, LocalServiceCommand.Stop);
    private void Restart_Click(object sender, RoutedEventArgs e) => CommandRequested?.Invoke(this, LocalServiceCommand.Restart);
    private void Refresh_Click(object sender, RoutedEventArgs e) => RefreshRequested?.Invoke(this, EventArgs.Empty);
    private void OpenReader_Click(object sender, RoutedEventArgs e) => OpenReaderRequested?.Invoke(this, EventArgs.Empty);
    private void Close_Click(object sender, RoutedEventArgs e) => Close();
}
