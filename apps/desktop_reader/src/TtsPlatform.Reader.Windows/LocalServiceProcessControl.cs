using System.ComponentModel;
using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Windows;

// Mutations require an exact persisted launcher or verified current-user task
// instance. Unknown processes are visible, never adopted from an API PID alone.
public sealed class LocalServiceProcessControl(Uri endpoint, string? startDirectory = null,
    string? leasePath = null, TimeSpan? operationTimeout = null,
    Func<IReadOnlyList<StartupTaskRecord>>? readLegacyTasks = null) : ILocalServiceProcesses
{
    private readonly Uri _endpoint = ServiceBaseUrl.Parse(endpoint.AbsoluteUri);
    private readonly string _startDirectory = startDirectory ?? AppContext.BaseDirectory;
    private readonly ReaderServiceProcessLeaseStore _leases = new(leasePath ?? DesktopPaths.ServiceProcessLeasePath);
    private (int Pid, long Started)? _verifiedService;
    private readonly LegacyServiceTasks _legacy = new(startDirectory ?? AppContext.BaseDirectory,
        UserStartupRegistration.CurrentUserSid(), endpoint.Port, readLegacyTasks);
    private bool _scheduledOwner;
    private readonly SemaphoreSlim _operationGate = new(1, 1);

    public Task<bool?> IsListeningAsync(CancellationToken cancellationToken) => Task.Run<bool?>(() =>
    {
        cancellationToken.ThrowIfCancellationRequested();
        try { return IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners().Any(address => address.Port == _endpoint.Port); }
        catch (NetworkInformationException) { return null; }
    }, cancellationToken);

    public Task<ServiceCommandResult> VerifyOwnerAsync(LocalServiceStatus status, CancellationToken cancellationToken) => RunOperationAsync(token =>
    {
        token.ThrowIfCancellationRequested();
        _verifiedService = null;
        _scheduledOwner = false;
        if (!TryOpenOwner(out var owner, out _))
        {
            var result = _legacy.VerifyOwner(status);
            _scheduledOwner = result.Succeeded;
            return result;
        }
        using (owner)
        {
            try
            {
                using var service = Process.GetProcessById(status.Resources.ProcessId);
                if (!ProcessAncestry.IsDescendant(service, owner!))
                    return new(false, "This endpoint does not belong to the recorded local launcher. Nothing was stopped.");
                _verifiedService = (service.Id, service.StartTime.ToUniversalTime().Ticks);
                return new(true, "Local launcher ownership verified.");
            }
            catch (Exception exception) when (IsProcessFailure(exception))
            { return new(false, "The service process changed or could not be verified. Refresh status before trying again."); }
        }
    }, cancellationToken);

    public async Task<ServiceCommandResult> StartAsync(CancellationToken cancellationToken)
    {
        if (await IsListeningAsync(cancellationToken) != false)
            return new(false, "The local port is occupied or could not be checked. No second service was started.");
        return await RunOperationAsync(token =>
        {
            token.ThrowIfCancellationRequested();
            if (TryOpenOwner(out var existing, out _))
            {
                existing!.Dispose();
                return new ServiceCommandResult(false, "A recorded service launcher is already running. Wait for it to finish starting; no duplicate was launched.");
            }
            if (_legacy.Start(token) is { } legacyResult) return legacyResult;
            var launcher = ScheduledServiceController.FindLocalServiceLauncher(_startDirectory);
            if (launcher is null) return new(false, "The local service launcher is missing from this installation.");
            try
            {
                var info = new ProcessStartInfo(PowerShellPath)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                    WorkingDirectory = launcher.DirectoryName!,
                    ArgumentList = { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", launcher.FullName,
                        "-HostOverride", "127.0.0.1", "-Port", _endpoint.Port.ToString(System.Globalization.CultureInfo.InvariantCulture) },
                };
                token.ThrowIfCancellationRequested();
                using var process = Process.Start(info);
                if (process is null) return new(false, "Windows could not start the local service launcher.");
                try { _leases.Save(process, launcher.FullName); }
                catch (Exception exception) when (IsProcessFailure(exception) || exception is IOException or UnauthorizedAccessException)
                {
                    // Only the exact just-created child is eligible for this cleanup.
                    if (!process.HasExited) { process.Kill(entireProcessTree: true); process.WaitForExit(5000); }
                    return new(false, "Launcher ownership could not be saved; the new launcher was stopped safely.");
                }
                return new(true, "The local launcher was started. Waiting for service readiness.");
            }
            catch (Exception exception) when (IsProcessFailure(exception))
            { return new(false, "Windows could not start the local service launcher."); }
        }, cancellationToken);
    }

    public Task<ServiceCommandResult> StopAsync(LocalServiceStatus status, Func<bool> reservationValid,
        CancellationToken cancellationToken) => RunOperationAsync(token =>
    {
        if (_scheduledOwner) return _legacy.Stop(status, reservationValid, token);
        if (!TryOpenOwner(out var owner, out var error)) return new ServiceCommandResult(false, error);
        using (owner)
        {
            try
            {
                using var service = Process.GetProcessById(status.Resources.ProcessId);
                if (_verifiedService != (service.Id, service.StartTime.ToUniversalTime().Ticks) ||
                    !ProcessAncestry.IsDescendant(service, owner!))
                    return new(false, "Service ownership changed during confirmation. Nothing was stopped.");
                // This is the last check before the actual OS mutation, not a timer
                // computed after an HTTP request or before queued background work.
                if (token.IsCancellationRequested || !reservationValid())
                    return new(false, "The maintenance reservation expired. Nothing was stopped; please try again.");
                owner!.Kill(entireProcessTree: true);
                if (!owner.WaitForExit(5000) || !service.WaitForExit(5000))
                    return new(false, "The verified local service did not finish stopping. Restart was not attempted.");
                _leases.Clear();
                _verifiedService = null;
                return new(true, "The verified local service was stopped.");
            }
            catch (Exception exception) when (IsProcessFailure(exception) || exception is IOException or UnauthorizedAccessException)
            { return new(false, "Service shutdown could not be confirmed. No unrelated process was terminated."); }
        }
    }, cancellationToken);

    private async Task<ServiceCommandResult> RunOperationAsync(Func<CancellationToken, ServiceCommandResult> operation,
        CancellationToken cancellationToken)
    {
        if (!await _operationGate.WaitAsync(0, cancellationToken))
            return new(false, "Windows is still finishing the previous operation. No duplicate operation was started.");
        var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var work = Task.Run(() =>
        {
            try { return operation(lifetime.Token); }
            finally { lifetime.Dispose(); _operationGate.Release(); }
        });
        _ = work.ContinueWith(task => _ = task.Exception, CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        try { return await work.WaitAsync(operationTimeout ?? TimeSpan.FromSeconds(12), cancellationToken); }
        catch (Exception exception) when (exception is TimeoutException or OperationCanceledException)
        {
            // Native COM calls are not abortable. Retain the gate until they
            // return, but cancel any mutation they have not reached yet.
            try { lifetime.Cancel(); } catch (ObjectDisposedException) { }
            return new(false, "Windows has not confirmed completion. Refresh status before trying again; no duplicate operation or forced fallback was started.");
        }
    }

    private bool TryOpenOwner(out Process? process, out string error)
    {
        process = null;
        var launcher = ScheduledServiceController.FindLocalServiceLauncher(_startDirectory);
        if (launcher is not null && _leases.TryOpenVerified(launcher.FullName, PowerShellPath, out process, out _))
        { error = ""; return true; }
        error = "This service has no verified Reader launcher record. If it was started in a terminal or by the legacy scheduled task, stop it there first. No process was adopted or terminated.";
        return false;
    }

    internal static string PowerShellPath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
    private static bool IsProcessFailure(Exception exception) => exception is ArgumentException or InvalidOperationException or Win32Exception or NotSupportedException;
}

internal static class ProcessAncestry
{
    // Toolhelp returns parent PIDs, which can be reused. Keep each process handle
    // alive and check chronological identity along the chain, including the owner.
    internal static bool IsDescendant(Process child, Process owner)
    {
        using var snapshot = CreateToolhelp32Snapshot(2, 0); // TH32CS_SNAPPROCESS
        if (snapshot.IsInvalid) return false;
        var entry = new ProcessEntry { Size = (uint)Marshal.SizeOf<ProcessEntry>(), Executable = "" };
        var parents = new Dictionary<int, int>();
        if (!Process32FirstW(snapshot, ref entry)) return false;
        do { parents[(int)entry.ProcessId] = (int)entry.ParentProcessId; }
        while (Process32NextW(snapshot, ref entry));
        var chain = new List<Process>();
        try
        {
            var current = child;
            for (var depth = 0; depth < 16; depth++)
            {
                if (current.HasExited || owner.HasExited || !parents.TryGetValue(current.Id, out var parentId) || parentId <= 0) return false;
                if (parentId == owner.Id)
                    return owner.StartTime.ToUniversalTime() <= current.StartTime.ToUniversalTime();
                if (chain.Any(process => process.Id == parentId) || parentId == child.Id) return false;
                var parent = Process.GetProcessById(parentId);
                chain.Add(parent);
                _ = parent.Handle;
                if (parent.HasExited || parent.StartTime.ToUniversalTime() > current.StartTime.ToUniversalTime()) return false;
                current = parent;
            }
            return false;
        }
        finally { foreach (var process in chain) process.Dispose(); }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry
    {
        public uint Size, Usage, ProcessId;
        public UIntPtr DefaultHeapId;
        public uint ModuleId, Threads, ParentProcessId;
        public int Priority;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string Executable;
    }
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern SafeFileHandle CreateToolhelp32Snapshot(uint flags, uint processId);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32FirstW(SafeFileHandle snapshot, ref ProcessEntry entry);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32NextW(SafeFileHandle snapshot, ref ProcessEntry entry);
}
