using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

public sealed class JsonlPlaybackPerformanceSink : IPlaybackPerformanceSink, IDisposable
{
    private const long DefaultMaximumBytes = 4 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly object _sync = new();
    private readonly long _maximumBytes;
    private readonly string _previousPath;
    private readonly string _desktopSessionId;
    private readonly string _appVersion;
    private StreamWriter? _writer;

    public JsonlPlaybackPerformanceSink(
        string? path = null,
        long maximumBytes = DefaultMaximumBytes,
        string? desktopSessionId = null,
        string? appVersion = null)
    {
        Path = path ?? DesktopPaths.PlaybackPerformanceLogPath;
        if (maximumBytes <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumBytes));
        }
        _maximumBytes = maximumBytes;
        _previousPath = System.IO.Path.ChangeExtension(Path, ".previous.jsonl");
        _desktopSessionId = desktopSessionId ?? Guid.NewGuid().ToString("N");
        _appVersion = appVersion ??
            typeof(JsonlPlaybackPerformanceSink).Assembly.GetName().Version?.ToString() ??
            "unknown";

        try
        {
            var directory = System.IO.Path.GetDirectoryName(Path)
                ?? throw new ArgumentException("The performance log path has no directory.", nameof(path));
            Directory.CreateDirectory(directory);
            RotateIfNeeded(Path, maximumBytes);
            _writer = OpenWriter(Path);
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            _writer = null;
        }
    }

    public string Path { get; }

    public void Record(PlaybackPerformanceEvent performanceEvent)
    {
        ArgumentNullException.ThrowIfNull(performanceEvent);
        lock (_sync)
        {
            if (_writer is null)
            {
                return;
            }
            try
            {
                var line = JsonSerializer.Serialize(
                    new PerformanceLogEntry(
                        2,
                        DateTimeOffset.UtcNow,
                        _desktopSessionId,
                        _appVersion,
                        performanceEvent),
                    JsonOptions);
                RotateBeforeWriteIfNeeded(line);
                _writer?.WriteLine(line);
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException or ObjectDisposedException)
            {
                _writer.Dispose();
                _writer = null;
            }
        }
    }

    public void Dispose()
    {
        lock (_sync)
        {
            _writer?.Dispose();
            _writer = null;
        }
    }

    private static void RotateIfNeeded(string path, long maximumBytes)
    {
        var current = new FileInfo(path);
        if (!current.Exists || current.Length < maximumBytes)
        {
            return;
        }
        var previous = System.IO.Path.ChangeExtension(path, ".previous.jsonl");
        CopyBoundedTail(path, previous, maximumBytes);
        File.Delete(path);
    }

    private static void CopyBoundedTail(string sourcePath, string destinationPath, long maximumBytes)
    {
        var temporaryPath = $"{destinationPath}.{Guid.NewGuid():N}.tmp";
        try
        {
            using (var source = new FileStream(
                sourcePath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite))
            {
                var tailStart = Math.Max(0, source.Length - maximumBytes);
                source.Position = tailStart;
                using var reader = new StreamReader(
                    source,
                    Encoding.UTF8,
                    detectEncodingFromByteOrderMarks: true);
                if (tailStart > 0)
                {
                    _ = reader.ReadLine();
                }

                using var writer = new StreamWriter(
                    temporaryPath,
                    append: false,
                    new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
                while (reader.ReadLine() is { } line)
                {
                    writer.WriteLine(line);
                }
            }

            File.Move(temporaryPath, destinationPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }

    private static StreamWriter OpenWriter(string path) => new(
        new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite),
        new UTF8Encoding(encoderShouldEmitUTF8Identifier: false))
    {
        AutoFlush = true,
    };

    private void RotateBeforeWriteIfNeeded(string line)
    {
        if (_writer is null)
        {
            return;
        }

        var lineBytes = Encoding.UTF8.GetByteCount(line) + Environment.NewLine.Length;
        if (_writer.BaseStream.Length == 0 ||
            _writer.BaseStream.Length + lineBytes <= _maximumBytes)
        {
            return;
        }

        _writer.Dispose();
        _writer = null;
        File.Move(Path, _previousPath, overwrite: true);
        _writer = OpenWriter(Path);
    }

    private sealed record PerformanceLogEntry(
        int SchemaVersion,
        DateTimeOffset TimestampUtc,
        string DesktopSessionId,
        string AppVersion,
        PlaybackPerformanceEvent Performance);
}
