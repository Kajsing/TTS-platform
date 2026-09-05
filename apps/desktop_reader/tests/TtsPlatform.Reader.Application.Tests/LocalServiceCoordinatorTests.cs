using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class LocalServiceCoordinatorTests
{
    private sealed class Clock : TimeProvider
    {
        public long Seconds;
        public override long TimestampFrequency => 1;
        public override long GetTimestamp() => Seconds;
        public override DateTimeOffset GetUtcNow() => DateTimeOffset.UnixEpoch.AddSeconds(Seconds);
    }
    private sealed class Client : ILocalServiceClient
    {
        public LocalServiceStatus Status = new(1, "instance", true, true, "voice", "Example", 5, 20, true,
            new(0, 0, 0, 0, 0), false, new("service_process", 42, 0, 10, 8, 10485760));
        public Exception? Error;
        public Exception? ReserveError;
        public Action? Reserving;
        public int Reads, Reserves, Releases;
        public Task<LocalServiceStatus> GetLocalStatusAsync(CancellationToken cancellationToken)
        { Reads++; return Error is null ? Task.FromResult(Status) : Task.FromException<LocalServiceStatus>(Error); }
        public Task<ServiceMaintenanceReservation> ReserveMaintenanceAsync(string instanceId, CancellationToken cancellationToken)
        {
            Assert.Equal(Status.InstanceId, instanceId);
            Reserves++;
            Reserving?.Invoke();
            return ReserveError is null ? Task.FromResult(new ServiceMaintenanceReservation("private-reservation", 15)) :
                Task.FromException<ServiceMaintenanceReservation>(ReserveError);
        }
        public Task<ServiceMaintenanceRelease> ReleaseMaintenanceAsync(string reservation, CancellationToken cancellationToken)
        { Assert.Equal("private-reservation", reservation); Releases++; return Task.FromResult(new ServiceMaintenanceRelease(true)); }
    }
    private sealed class Processes : ILocalServiceProcesses
    {
        public bool? Listening = true;
        public bool Owned = true;
        public bool StopSucceeds = true;
        public bool RemainsListening;
        public int Starts, Stops, OwnershipChecks;
        public Action? BeforeStop;
        public Action? Starting;
        public Task<bool?> IsListeningAsync(CancellationToken cancellationToken) => Task.FromResult(Listening);
        public Task<ServiceCommandResult> VerifyOwnerAsync(LocalServiceStatus status, CancellationToken cancellationToken)
        { OwnershipChecks++; return Task.FromResult(new ServiceCommandResult(Owned, "Ownership result")); }
        public Task<ServiceCommandResult> StartAsync(CancellationToken cancellationToken)
        { Starts++; Starting?.Invoke(); return Task.FromResult(new ServiceCommandResult(true, "Started")); }
        public Task<ServiceCommandResult> StopAsync(LocalServiceStatus status, Func<bool> reservationValid, CancellationToken cancellationToken)
        {
            BeforeStop?.Invoke();
            if (!reservationValid()) return Task.FromResult(new ServiceCommandResult(false, "Expired before mutation"));
            Stops++;
            if (StopSucceeds) Listening = RemainsListening;
            return Task.FromResult(new ServiceCommandResult(StopSucceeds, "Stop result"));
        }
    }
    private static Task<bool> Confirm() => Task.FromResult(true);

    [Fact]
    public async Task Idle_owned_service_stops_only_after_reservation_and_verified_shutdown()
    {
        var client = new Client(); var processes = new Processes();
        var coordinator = new LocalServiceCoordinator(client, processes);
        var result = await coordinator.ExecuteAsync(LocalServiceCommand.Stop, Confirm);
        Assert.True(result.Succeeded);
        Assert.Equal(1, client.Reserves);
        Assert.Equal(1, processes.Stops);
        Assert.Equal(0, processes.Starts);
        Assert.Equal(LocalServiceState.Stopped, coordinator.Dashboard.State);
    }

    [Fact]
    public async Task Busy_unknown_and_unowned_services_are_never_stopped()
    {
        foreach (var variant in new[] { "busy", "unknown", "unowned", "invalid" })
        {
            var client = new Client(); var processes = new Processes();
            if (variant == "busy") client.Status = client.Status with { Activity = new(0, 0, 0, 1, 0) };
            if (variant == "unknown") client.Error = new ReaderServiceUnavailableException("Timeout");
            if (variant == "unowned") processes.Owned = false;
            if (variant == "invalid") client.Status = client.Status with { ContractVersion = 99 };
            var coordinator = new LocalServiceCoordinator(client, processes);
            Assert.False((await coordinator.ExecuteAsync(LocalServiceCommand.Stop, Confirm)).Succeeded);
            Assert.Equal(0, client.Reserves);
            Assert.Equal(0, processes.Stops);
        }
    }

    [Theory]
    [InlineData("service_busy")]
    [InlineData("service_instance_changed")]
    [InlineData("service_maintenance_busy")]
    public async Task Reservation_races_do_not_fall_back_to_force_stop(string error)
    {
        var client = new Client { ReserveError = new ReaderApiException(error, "Rejected", 409) };
        var processes = new Processes();
        var coordinator = new LocalServiceCoordinator(client, processes);
        Assert.False((await coordinator.ExecuteAsync(LocalServiceCommand.Restart, Confirm)).Succeeded);
        Assert.Equal(0, processes.Stops);
        Assert.Equal(0, processes.Starts);
    }

    [Fact]
    public async Task Declined_confirmation_and_reader_cleanup_failure_never_reserve()
    {
        var client = new Client(); var processes = new Processes();
        var coordinator = new LocalServiceCoordinator(client, processes);
        Assert.False((await coordinator.ExecuteAsync(LocalServiceCommand.Stop, () => Task.FromResult(false))).Succeeded);
        Assert.Equal(0, client.Reserves);
        Assert.Equal(0, processes.Stops);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Deadline_includes_request_latency_and_is_checked_again_by_os_adapter(bool duringRequest)
    {
        var clock = new Clock(); var client = new Client(); var processes = new Processes();
        if (duringRequest) client.Reserving = () => clock.Seconds += 15;
        else processes.BeforeStop = () => clock.Seconds += 15;
        var coordinator = new LocalServiceCoordinator(client, processes, clock);
        Assert.False((await coordinator.ExecuteAsync(LocalServiceCommand.Stop, Confirm)).Succeeded);
        Assert.Equal(0, processes.Stops);
        Assert.Equal(1, client.Releases);
    }

    [Fact]
    public async Task Long_confirmation_does_not_consume_reservation()
    {
        var clock = new Clock(); var client = new Client(); var processes = new Processes();
        var coordinator = new LocalServiceCoordinator(client, processes, clock);
        var result = await coordinator.ExecuteAsync(LocalServiceCommand.Stop, () => { clock.Seconds += 600; return Confirm(); });
        Assert.True(result.Succeeded);
    }

    [Fact]
    public async Task Failed_or_uncertain_stop_releases_maintenance_and_does_not_restart()
    {
        foreach (var succeeds in new[] { true, false })
        {
            var client = new Client(); var processes = new Processes { StopSucceeds = succeeds, RemainsListening = true };
            var coordinator = new LocalServiceCoordinator(client, processes);
            Assert.False((await coordinator.ExecuteAsync(LocalServiceCommand.Restart, Confirm)).Succeeded);
            Assert.Equal(1, client.Releases);
            Assert.Equal(0, processes.Starts);
        }
    }

    [Fact]
    public async Task Only_verified_absent_listener_is_stopped_not_http_timeout_or_missing_auth()
    {
        foreach (var listening in new bool?[] { false, true, null })
        {
            var client = new Client { Error = new ReaderServiceUnavailableException("Timeout") };
            var coordinator = new LocalServiceCoordinator(client, new Processes { Listening = listening });
            await coordinator.RefreshAsync();
            Assert.Equal(listening == false ? LocalServiceState.Stopped : LocalServiceState.Unreachable, coordinator.Dashboard.State);
            client.Error = new ReaderTokenUnavailableException("Missing");
            await coordinator.RefreshAsync();
            Assert.Equal(LocalServiceState.AuthenticationRequired, coordinator.Dashboard.State);
        }
    }

    [Fact]
    public async Task Rate_limit_blocks_manual_checks_and_commands_until_backoff_expires()
    {
        var clock = new Clock(); var client = new Client { Error = new ReaderApiException("rate_limit", "Slow down", 429) };
        var processes = new Processes();
        var coordinator = new LocalServiceCoordinator(client, processes, clock);
        await coordinator.RefreshAsync();
        await coordinator.RefreshAsync();
        Assert.False((await coordinator.ExecuteAsync(LocalServiceCommand.Start, Confirm)).Succeeded);
        Assert.Equal(1, client.Reads);
        clock.Seconds = 65;
        client.Error = null;
        await coordinator.RefreshAsync();
        Assert.Equal(2, client.Reads);
        Assert.False(coordinator.IsRateLimited);
    }

    [Fact]
    public async Task Overlapping_commands_and_poll_do_not_run_during_confirmation()
    {
        var client = new Client(); var processes = new Processes();
        var coordinator = new LocalServiceCoordinator(client, processes);
        var confirmation = new TaskCompletionSource<bool>();
        var pending = coordinator.ExecuteAsync(LocalServiceCommand.Stop, () => confirmation.Task);
        Assert.True(coordinator.IsOperating);
        await coordinator.RefreshAsync();
        Assert.False((await coordinator.ExecuteAsync(LocalServiceCommand.Restart, Confirm)).Succeeded);
        Assert.Equal(1, client.Reads);
        confirmation.SetResult(true);
        Assert.True((await pending).Succeeded);
        Assert.False(coordinator.IsOperating);
    }

    [Fact]
    public async Task Restart_waits_for_new_readiness_after_verified_stop()
    {
        var client = new Client(); var processes = new Processes();
        processes.Starting = () => client.Status = client.Status with { InstanceId = "new-instance" };
        var coordinator = new LocalServiceCoordinator(client, processes);
        Assert.True((await coordinator.ExecuteAsync(LocalServiceCommand.Restart, Confirm)).Succeeded);
        Assert.Equal(1, processes.Starts);
        Assert.Equal("new-instance", coordinator.Dashboard.Status?.InstanceId);
        Assert.Null(coordinator.Dashboard.CpuPercent);
    }
}
