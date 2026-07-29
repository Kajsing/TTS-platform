using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;

namespace TtsPlatform.Reader.Windows;

public sealed record ReaderServiceProcessLease(
    int SchemaVersion,
    int ProcessId,
    long StartTimeUtcTicks,
    string ExecutablePath,
    string LauncherPath);

public sealed class ReaderServiceProcessLeaseStore(string leasePath)
{
    private const int CurrentSchemaVersion = 1;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    public string LeasePath { get; } = Path.GetFullPath(leasePath);

    public void Save(Process process, string launcherPath)
    {
        ArgumentNullException.ThrowIfNull(process);
        ArgumentException.ThrowIfNullOrWhiteSpace(launcherPath);
        if (process.HasExited)
        {
            throw new InvalidOperationException("The local service launcher exited before ownership was recorded.");
        }

        var executablePath = process.MainModule?.FileName
            ?? throw new InvalidOperationException("The local service launcher executable could not be identified.");
        var lease = new ReaderServiceProcessLease(
            CurrentSchemaVersion,
            process.Id,
            process.StartTime.ToUniversalTime().Ticks,
            Path.GetFullPath(executablePath),
            Path.GetFullPath(launcherPath));
        var directory = Path.GetDirectoryName(LeasePath)
            ?? throw new InvalidOperationException("The service ownership path must have a parent directory.");
        Directory.CreateDirectory(directory);
        var temporaryPath = Path.Combine(
            directory,
            $".{Path.GetFileName(LeasePath)}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var stream = new FileStream(
                temporaryPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                4096,
                FileOptions.WriteThrough))
            {
                JsonSerializer.Serialize(stream, lease, JsonOptions);
                stream.Flush(flushToDisk: true);
            }
            File.Move(temporaryPath, LeasePath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }

    public bool TryOpenVerified(
        string expectedLauncherPath,
        string expectedExecutablePath,
        out Process? process,
        out string error)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedLauncherPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedExecutablePath);
        process = null;
        if (!File.Exists(LeasePath))
        {
            error = "No persisted Reader service ownership record exists.";
            return false;
        }

        ReaderServiceProcessLease? lease;
        try
        {
            using var stream = new FileStream(
                LeasePath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read);
            lease = JsonSerializer.Deserialize<ReaderServiceProcessLease>(stream, JsonOptions);
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or JsonException)
        {
            TryClear();
            error = $"The persisted Reader service ownership record is unreadable: {exception.Message}";
            return false;
        }

        if (lease is null ||
            lease.SchemaVersion != CurrentSchemaVersion ||
            lease.ProcessId <= 0 ||
            string.IsNullOrWhiteSpace(lease.LauncherPath) ||
            string.IsNullOrWhiteSpace(lease.ExecutablePath) ||
            !PathsEqual(lease.LauncherPath, expectedLauncherPath) ||
            !PathsEqual(lease.ExecutablePath, expectedExecutablePath))
        {
            TryClear();
            error = "The persisted Reader service ownership record does not match this Reader installation.";
            return false;
        }

        Process? candidate = null;
        try
        {
            candidate = Process.GetProcessById(lease.ProcessId);
            var candidateExecutable = candidate.MainModule?.FileName;
            if (candidate.HasExited ||
                candidate.StartTime.ToUniversalTime().Ticks != lease.StartTimeUtcTicks ||
                candidateExecutable is null ||
                !PathsEqual(candidateExecutable, expectedExecutablePath))
            {
                candidate.Dispose();
                TryClear();
                error = "The recorded Reader service launcher is no longer the same running process.";
                return false;
            }
        }
        catch (Exception exception) when (
            exception is ArgumentException or InvalidOperationException or Win32Exception or NotSupportedException)
        {
            candidate?.Dispose();
            TryClear();
            error = $"The recorded Reader service launcher is no longer available: {exception.Message}";
            return false;
        }

        process = candidate;
        error = string.Empty;
        return true;
    }

    public void Clear()
    {
        if (File.Exists(LeasePath))
        {
            File.Delete(LeasePath);
        }
    }

    private void TryClear()
    {
        try
        {
            Clear();
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A stale record is harmless; a later operation may be able to remove it.
        }
    }

    private static bool PathsEqual(string left, string right)
    {
        try
        {
            return string.Equals(
                Path.GetFullPath(left),
                Path.GetFullPath(right),
                StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception exception) when (
            exception is ArgumentException or IOException or NotSupportedException)
        {
            return false;
        }
    }
}
