using System.Text.Json;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public enum LocalServiceCommand { Start, Stop, Restart }
public sealed record ServiceCommandResult(bool Succeeded, string Message);

// The OS adapter must independently prove ownership; an API PID is not permission
// to terminate it. The deadline callback must be checked immediately before stop.
public interface ILocalServiceProcesses
{
    Task<bool?> IsListeningAsync(CancellationToken cancellationToken);
    Task<ServiceCommandResult> VerifyOwnerAsync(LocalServiceStatus status, CancellationToken cancellationToken);
    Task<ServiceCommandResult> StartAsync(CancellationToken cancellationToken);
    Task<ServiceCommandResult> StopAsync(LocalServiceStatus status, Func<bool> reservationValid, CancellationToken cancellationToken);
}

public sealed class LocalServiceCoordinator(
    ILocalServiceClient client, ILocalServiceProcesses processes, TimeProvider? timeProvider = null)
{
    private readonly TimeProvider _time = timeProvider ?? TimeProvider.System;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private DateTimeOffset _retryAfter;
    private LocalServiceStatus? _previous;
    public ServiceDashboard Dashboard { get; private set; } = new(LocalServiceState.Unknown, "Checking this computer's service…");
    public bool IsOperating { get; private set; }
    public DateTimeOffset? LastCheckedAt { get; private set; }
    public bool IsRateLimited => _time.GetUtcNow() < _retryAfter;
    public event EventHandler? Changed;

    private void Show(ServiceDashboard dashboard)
    {
        Dashboard = dashboard;
        Changed?.Invoke(this, EventArgs.Empty);
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (!await _gate.WaitAsync(0, cancellationToken)) return;
        try { if (!IsRateLimited) await ReadAsync(cancellationToken); }
        finally { _gate.Release(); }
    }

    private async Task ReadAsync(CancellationToken cancellationToken)
    {
        try
        {
            var status = await client.GetLocalStatusAsync(cancellationToken);
            LastCheckedAt = _time.GetUtcNow();
            Show(ServiceDashboard.FromStatus(status, _previous));
            _previous = Dashboard.Status;
        }
        catch (Exception exception) when (IsExpected(exception) && !cancellationToken.IsCancellationRequested)
        {
            _previous = null;
            LastCheckedAt = _time.GetUtcNow();
            var state = LocalServiceState.Unreachable;
            var message = ErrorMessage(exception);
            if (exception is ReaderTokenUnavailableException or ReaderApiException { StatusCode: 401 or 403 })
                state = LocalServiceState.AuthenticationRequired;
            else if (exception is ReaderServiceUnavailableException or HttpRequestException)
            {
                // A timeout alone never means stopped or safe to start another process.
                if (await processes.IsListeningAsync(cancellationToken) == false)
                {
                    state = LocalServiceState.Stopped;
                    message = "No local service is listening at this address.";
                }
            }
            if (exception is ReaderApiException { StatusCode: 429 })
                _retryAfter = _time.GetUtcNow().AddSeconds(65);
            Show(new(state, message));
        }
    }

    public async Task<ServiceCommandResult> ExecuteAsync(LocalServiceCommand command,
        Func<Task<bool>> confirmAndPrepareReader, CancellationToken cancellationToken = default)
    {
        if (!await _gate.WaitAsync(0, cancellationToken))
            return new(false, "Another check or service operation is still in progress.");
        IsOperating = true;
        Changed?.Invoke(this, EventArgs.Empty);
        try
        {
            if (IsRateLimited) return new(false, "The service asked us to wait. Try again after one minute.");
            await ReadAsync(cancellationToken);
            if (command == LocalServiceCommand.Start)
                return await StartAndWaitAsync(cancellationToken);
            if (!Dashboard.CanRequestMaintenance)
                return new(false, "Stop was not attempted. Wait for active speech, imports and exports to finish; service activity must be known and idle.");
            var status = Dashboard.Status!;
            var owner = await processes.VerifyOwnerAsync(status, cancellationToken);
            if (!owner.Succeeded) return owner;
            // Confirmation/Reader cleanup must not consume the short reservation.
            if (!await confirmAndPrepareReader()) return new(false, "Service operation cancelled. Nothing was stopped.");
            var beforeRequest = _time.GetTimestamp();
            ServiceMaintenanceReservation? reservation = null;
            try
            {
                reservation = await client.ReserveMaintenanceAsync(status.InstanceId, cancellationToken);
                if (string.IsNullOrWhiteSpace(reservation.Reservation) || reservation.ExpiresInSeconds is <= 1 or > 15)
                    return new(false, "The service returned an invalid maintenance reservation. Nothing was stopped.");
                bool Valid() => !cancellationToken.IsCancellationRequested &&
                    _time.GetElapsedTime(beforeRequest) < TimeSpan.FromSeconds(reservation.ExpiresInSeconds - 1);
                if (!Valid()) return new(false, "The maintenance reservation expired before stop. Please try again.");
                var stopped = await processes.StopAsync(status, Valid, cancellationToken);
                if (!stopped.Succeeded) return stopped;
                // Never restart on an uncertain stop, even if the OS command succeeded.
                if (await processes.IsListeningAsync(cancellationToken) != false)
                    return new(false, "Shutdown could not be confirmed. Restart was not attempted.");
                Show(new(LocalServiceState.Stopped, "The local service is stopped."));
                if (command == LocalServiceCommand.Restart) return await StartAndWaitAsync(cancellationToken);
                return new(true, "The local service is stopped. Articles and saved audio are unchanged.");
            }
            finally
            {
                // On successful stop the endpoint is gone. Otherwise release even on
                // cancellation; the client's bounded timeout and server expiry protect exit.
                if (reservation is not null && Dashboard.State != LocalServiceState.Stopped &&
                    Dashboard.Status?.InstanceId == status.InstanceId)
                {
                    try { await client.ReleaseMaintenanceAsync(reservation.Reservation, CancellationToken.None); }
                    catch (Exception exception) when (IsExpected(exception)) { }
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return new(false, "The service operation was cancelled. Check status before trying again.");
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            if (exception is ReaderApiException { StatusCode: 429 }) _retryAfter = _time.GetUtcNow().AddSeconds(65);
            Show(new(LocalServiceState.Unreachable, ErrorMessage(exception)));
            return new(false, ErrorMessage(exception));
        }
        finally
        {
            IsOperating = false;
            Changed?.Invoke(this, EventArgs.Empty);
            _gate.Release();
        }
    }

    private async Task<ServiceCommandResult> StartAndWaitAsync(CancellationToken cancellationToken)
    {
        if (Dashboard.State != LocalServiceState.Stopped)
            return new(false, "Start was not attempted: the address is in use, or service state could not be verified.");
        var result = await processes.StartAsync(cancellationToken);
        if (!result.Succeeded) return result;
        Show(new(LocalServiceState.Starting, "Starting the local service and checking voice readiness…"));
        for (var attempt = 0; attempt < 24; attempt++)
        {
            await Task.Delay(TimeSpan.FromSeconds(2), _time, cancellationToken);
            await ReadAsync(cancellationToken);
            if (Dashboard.State is LocalServiceState.Ready or LocalServiceState.Busy)
                return new(true, "The local service is ready.");
            if (IsRateLimited || Dashboard.State == LocalServiceState.AuthenticationRequired) break;
            if (Dashboard.State == LocalServiceState.Stopped)
                Show(new(LocalServiceState.Starting, "Waiting for the local service to accept connections…"));
        }
        return new(false, "The launcher ran, but readiness was not confirmed. Status checks will continue; no second process was started.");
    }

    public static bool IsExpected(Exception exception) => exception is ReaderApiException or
        ReaderTokenUnavailableException or ReaderServiceUnavailableException or HttpRequestException or
        IOException or UnauthorizedAccessException or JsonException or ReaderClientConfigurationException or OperationCanceledException;

    private static string ErrorMessage(Exception exception) => exception switch
    {
        ReaderTokenUnavailableException or ReaderApiException { StatusCode: 401 or 403 } =>
            "Local owner authentication is unavailable. Check the local token file in Reader connection settings.",
        ReaderApiException { StatusCode: 429 } => "Too many requests. Status checks will resume after one minute.",
        ReaderApiException { StatusCode: 404 } => "This service does not support Service Center yet. Update the local service before managing it.",
        ReaderApiException { ErrorType: "service_busy" } => "The service became busy. Finish or cancel active work before stopping it.",
        ReaderApiException { ErrorType: "service_instance_changed" } => "The service restarted during this operation. Refresh status and try again.",
        ReaderApiException { ErrorType: "service_maintenance_busy" } => "Another service operation is holding maintenance. Please wait.",
        JsonException => "The service returned an invalid status. Nothing was stopped.",
        _ => "The local service could not be reached or verified. No unsafe fallback was attempted.",
    };
}
