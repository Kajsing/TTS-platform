using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public enum LocalServiceState
{
    Unknown,
    Stopped,
    Starting,
    Ready,
    Busy,
    Degraded,
    Maintenance,
    Unreachable,
    AuthenticationRequired,
}

public sealed record ServiceDashboard(
    LocalServiceState State,
    string Message,
    LocalServiceStatus? Status = null,
    double? CpuPercent = null,
    double? WorkingSetMiB = null)
{
    public static ServiceDashboard FromStatus(LocalServiceStatus status, LocalServiceStatus? previous = null)
    {
        if (status.ContractVersion != 1 || string.IsNullOrWhiteSpace(status.InstanceId) ||
            status.Activity is null || !status.Activity.IsValid || status.Resources is null ||
            status.Resources.Scope != "service_process" || status.Resources.ProcessId <= 0 ||
            status.VoiceCount < 0 || status.UptimeS < 0)
            return new(LocalServiceState.Unreachable, "Unsupported service status. Update the local service before managing it.");

        var state = status.Maintenance ? LocalServiceState.Maintenance :
            !status.BackendReady || !status.DefaultVoiceLoaded || !status.ReaderReady ? LocalServiceState.Degraded :
            !status.Activity.IsIdle ? LocalServiceState.Busy : LocalServiceState.Ready;
        var message = state switch
        {
            LocalServiceState.Maintenance => "A local service operation is in progress.",
            LocalServiceState.Degraded => "The service is responding, but voice or Reader readiness needs attention.",
            LocalServiceState.Busy => "The service is processing requests, speech, or audio exports.",
            _ => "Ready for reading. No active service work.",
        };
        double? cpu = null;
        var current = status.Resources;
        var before = previous?.Resources;
        if (previous?.InstanceId == status.InstanceId && before?.ProcessId == current.ProcessId &&
            current.LogicalProcessors is > 0 && current.SampleMonotonicS > before.SampleMonotonicS &&
            current.CpuSeconds >= before.CpuSeconds)
        {
            var value = (current.CpuSeconds - before.CpuSeconds) /
                (current.SampleMonotonicS - before.SampleMonotonicS) / current.LogicalProcessors.Value * 100;
            if (double.IsFinite(value) && value >= 0) cpu = Math.Clamp(value, 0, 100);
        }
        double? ram = current.WorkingSetBytes is >= 0 ? current.WorkingSetBytes.Value / (1024.0 * 1024.0) : null;
        return new(state, message, status, cpu, ram);
    }

    public bool CanRequestMaintenance => Status is { Activity.IsIdle: true, Maintenance: false } &&
        State is LocalServiceState.Ready or LocalServiceState.Degraded;

    public static TimeSpan PollInterval(bool panelVisible, bool failed, bool rateLimited) =>
        TimeSpan.FromSeconds(rateLimited ? 65 : failed ? 30 : panelVisible ? 5 : 15);
}
