using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ServiceDashboardTests
{
    private static LocalServiceStatus Ready() => new(1, "instance", true, true, "voice", "Example", 5, 123,
        true, new(0, 0, 0, 0, 0), false, new("service_process", 42, 5, 100, 8, 104857600));

    [Fact]
    public void Ready_busy_degraded_and_maintenance_are_distinct()
    {
        var ready = Ready();
        Assert.Equal(LocalServiceState.Ready, ServiceDashboard.FromStatus(ready).State);
        Assert.True(ServiceDashboard.FromStatus(ready).CanRequestMaintenance);
        var busy = ServiceDashboard.FromStatus(ready with { Activity = new(0, 0, 0, 1, 0) });
        Assert.Equal(LocalServiceState.Busy, busy.State);
        Assert.False(busy.CanRequestMaintenance);
        var degraded = ServiceDashboard.FromStatus(ready with { BackendReady = false });
        Assert.Equal(LocalServiceState.Degraded, degraded.State);
        Assert.True(degraded.CanRequestMaintenance); // Idle degraded service can still be repaired/restarted.
        Assert.False(ServiceDashboard.FromStatus(ready with { Maintenance = true }).CanRequestMaintenance);
    }

    [Fact]
    public void Cpu_is_delta_over_capacity_and_first_sample_is_unknown()
    {
        var first = Ready();
        var next = first with { Resources = first.Resources with { CpuSeconds = 9, SampleMonotonicS = 102 } };
        Assert.Null(ServiceDashboard.FromStatus(first).CpuPercent);
        var value = ServiceDashboard.FromStatus(next, first);
        Assert.Equal(25, value.CpuPercent);
        Assert.Equal(100, value.WorkingSetMiB);
        Assert.Null(ServiceDashboard.FromStatus(next with { InstanceId = "restarted" }, first).CpuPercent);
        Assert.Null(ServiceDashboard.FromStatus(next with { Resources = next.Resources with { ProcessId = 99 } }, first).CpuPercent);
        Assert.Null(ServiceDashboard.FromStatus(first, first).CpuPercent);
    }

    [Fact]
    public void Missing_resources_and_malformed_status_never_become_idle_zeroes()
    {
        var ready = Ready();
        var unavailable = ServiceDashboard.FromStatus(ready with { Resources = ready.Resources with { WorkingSetBytes = null, LogicalProcessors = null } });
        Assert.Null(unavailable.WorkingSetMiB);
        Assert.Null(unavailable.CpuPercent);
        Assert.False(ServiceDashboard.FromStatus(ready with { ContractVersion = 9 }).CanRequestMaintenance);
        Assert.False(ServiceDashboard.FromStatus(ready with { Activity = new(-1, 0, 0, 0, 0) }).CanRequestMaintenance);
        Assert.False(ServiceDashboard.FromStatus(ready with { Activity = null! }).CanRequestMaintenance);
        Assert.False(ServiceDashboard.FromStatus(ready with { Resources = null! }).CanRequestMaintenance);
        Assert.Null(ServiceDashboard.FromStatus(ready with { Resources = ready.Resources with { CpuSeconds = double.NaN } }, ready).CpuPercent);
    }

    [Fact]
    public void Polling_is_bounded_and_backs_off_on_failure_and_rate_limit()
    {
        Assert.Equal(TimeSpan.FromSeconds(5), ServiceDashboard.PollInterval(true, false, false));
        Assert.Equal(TimeSpan.FromSeconds(15), ServiceDashboard.PollInterval(false, false, false));
        Assert.Equal(TimeSpan.FromSeconds(30), ServiceDashboard.PollInterval(true, true, false));
        Assert.Equal(TimeSpan.FromSeconds(65), ServiceDashboard.PollInterval(true, true, true));
    }
}
