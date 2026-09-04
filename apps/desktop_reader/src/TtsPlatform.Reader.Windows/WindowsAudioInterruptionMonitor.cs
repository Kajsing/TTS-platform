using System.Diagnostics;
using NAudio.CoreAudioApi;
using NAudio.CoreAudioApi.Interfaces;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

public sealed class AudioInterruptionChangedEventArgs(
    bool isActive,
    string? source) : EventArgs
{
    public bool IsActive { get; } = isActive;
    public string? Source { get; } = source;
}

public sealed class WindowsAudioInterruptionMonitor : IDisposable
{
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(200);
    private const float MinimumAudiblePeak = 0.002f;
    private readonly object _sync = new();
    private readonly CancellationTokenSource _cancellation = new();
    private readonly PlaybackInterruptionDebouncer _debouncer = new();
    private readonly Task _monitorTask;
    private bool _enabled;
    private bool _disposed;

    public WindowsAudioInterruptionMonitor()
    {
        _monitorTask = Task.Run(() => MonitorAsync(_cancellation.Token));
    }

    public event EventHandler<AudioInterruptionChangedEventArgs>? Changed;

    public bool Enabled
    {
        get
        {
            lock (_sync)
            {
                return _enabled;
            }
        }
        set => SetEnabled(value);
    }

    public static string? ClassifySource(
        string? processName,
        string? displayName,
        string? sessionIdentifier,
        bool isSystemSoundsSession,
        bool isCapture)
    {
        var process = NormalizeProcessName(processName);
        var identity = string.Join('|', process, displayName, sessionIdentifier)
            .ToLowerInvariant();
        if (process is "teams" or "ms-teams" or "msteams" ||
            identity.Contains("microsoftteams", StringComparison.Ordinal) ||
            identity.Contains("microsoft teams", StringComparison.Ordinal) ||
            identity.Contains("ms-teams", StringComparison.Ordinal) ||
            identity.Contains("\\teams.exe", StringComparison.Ordinal))
        {
            return "Microsoft Teams";
        }
        if (isCapture)
        {
            return null;
        }
        if (process is "time" or "windowsalarms" ||
            identity.Contains("microsoft.windowsalarms", StringComparison.Ordinal) ||
            identity.Contains("windowsalarms", StringComparison.Ordinal) ||
            identity.Contains("\\time.exe", StringComparison.Ordinal))
        {
            return "Windows alarm";
        }
        return isSystemSoundsSession ? "Windows alert or alarm" : null;
    }

    public void Dispose()
    {
        lock (_sync)
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            _enabled = false;
        }
        _cancellation.Cancel();
        try
        {
            _monitorTask.GetAwaiter().GetResult();
        }
        catch (OperationCanceledException)
        {
            // Disposal owns cancellation of the polling loop.
        }
        _cancellation.Dispose();
    }

    private void SetEnabled(bool enabled)
    {
        PlaybackInterruptionTransition? transition = null;
        lock (_sync)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_enabled == enabled)
            {
                return;
            }
            _enabled = enabled;
            if (!enabled)
            {
                transition = _debouncer.Reset();
            }
        }
        RaiseTransition(transition);
    }

    private async Task MonitorAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            bool enabled;
            lock (_sync)
            {
                enabled = _enabled;
            }
            if (enabled)
            {
                var source = DetectInterruptionSource();
                PlaybackInterruptionTransition? transition;
                lock (_sync)
                {
                    transition = _enabled
                        ? _debouncer.Observe(source, DateTimeOffset.UtcNow)
                        : null;
                }
                RaiseTransition(transition);
            }
            await Task.Delay(PollInterval, cancellationToken).ConfigureAwait(false);
        }
    }

    private static string? DetectInterruptionSource()
    {
        try
        {
            using var enumerator = new MMDeviceEnumerator();
            foreach (var flow in new[] { DataFlow.Render, DataFlow.Capture })
            {
                var devices = enumerator.EnumerateAudioEndPoints(flow, DeviceState.Active);
                foreach (var device in devices)
                {
                    using (device)
                    {
                        var source = DetectOnDevice(device, flow == DataFlow.Capture);
                        if (source is not null)
                        {
                            return source;
                        }
                    }
                }
            }
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or ArgumentException or System.Runtime.InteropServices.COMException)
        {
            // Audio devices and sessions can disappear while they are enumerated.
        }
        return null;
    }

    private static string? DetectOnDevice(MMDevice device, bool isCapture)
    {
        var sessions = device.AudioSessionManager.Sessions;
        for (var index = 0; index < sessions.Count; index++)
        {
            using var session = sessions[index];
            try
            {
                if (session.State != AudioSessionState.AudioSessionStateActive)
                {
                    continue;
                }
                var processName = ProcessName(session.GetProcessID);
                if (session.GetProcessID == Environment.ProcessId)
                {
                    continue;
                }
                var source = ClassifySource(
                    processName,
                    session.DisplayName,
                    session.GetSessionIdentifier,
                    session.IsSystemSoundsSession,
                    isCapture);
                if (source is null)
                {
                    continue;
                }
                if (isCapture && string.Equals(source, "Microsoft Teams", StringComparison.Ordinal))
                {
                    return source;
                }
                if (session.AudioMeterInformation.MasterPeakValue >= MinimumAudiblePeak)
                {
                    return source;
                }
            }
            catch (Exception exception) when (
                exception is InvalidOperationException or ArgumentException or
                    System.Runtime.InteropServices.COMException)
            {
                // One expired session must not disable monitoring of the others.
            }
        }
        return null;
    }

    private static string? ProcessName(uint processId)
    {
        if (processId == 0 || processId > int.MaxValue)
        {
            return null;
        }
        try
        {
            using var process = Process.GetProcessById((int)processId);
            return process.ProcessName;
        }
        catch (Exception exception) when (
            exception is ArgumentException or InvalidOperationException or
                System.ComponentModel.Win32Exception)
        {
            return null;
        }
    }

    private static string NormalizeProcessName(string? processName) =>
        Path.GetFileNameWithoutExtension(processName ?? string.Empty).Trim().ToLowerInvariant();

    private void RaiseTransition(PlaybackInterruptionTransition? transition)
    {
        if (transition is not null)
        {
            Changed?.Invoke(
                this,
                new AudioInterruptionChangedEventArgs(transition.IsActive, transition.Source));
        }
    }
}
