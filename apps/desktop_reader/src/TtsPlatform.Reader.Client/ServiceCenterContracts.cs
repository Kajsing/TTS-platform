namespace TtsPlatform.Reader.Client;

public interface ILocalServiceClient
{
    Task<LocalServiceStatus> GetLocalStatusAsync(CancellationToken cancellationToken = default);
    Task<ServiceMaintenanceReservation> ReserveMaintenanceAsync(string instanceId, CancellationToken cancellationToken = default);
    Task<ServiceMaintenanceRelease> ReleaseMaintenanceAsync(string reservation, CancellationToken cancellationToken = default);
}

public sealed record LocalServiceStatus(
    int ContractVersion,
    string InstanceId,
    bool BackendReady,
    bool DefaultVoiceLoaded,
    string? DefaultVoiceId,
    string? DefaultVoiceName,
    int VoiceCount,
    long UptimeS,
    bool ReaderReady,
    LocalServiceActivity Activity,
    bool Maintenance,
    LocalServiceResources Resources);

public sealed record LocalServiceActivity(
    int ActiveRequests,
    int ActiveStreams,
    int ContentLeases,
    int PendingExports,
    int PendingJobs)
{
    public bool IsIdle => ActiveRequests == 0 && ActiveStreams == 0 && ContentLeases == 0 &&
        PendingExports == 0 && PendingJobs == 0;

    public bool IsValid => ActiveRequests >= 0 && ActiveStreams >= 0 && ContentLeases >= 0 &&
        PendingExports >= 0 && PendingJobs >= 0;
}

public sealed record LocalServiceResources(
    string Scope,
    int ProcessId,
    double CpuSeconds,
    double SampleMonotonicS,
    int? LogicalProcessors,
    long? WorkingSetBytes);

public sealed record ServiceMaintenanceReservation(string Reservation, int ExpiresInSeconds);
public sealed record ServiceMaintenanceRelease(bool Released);
