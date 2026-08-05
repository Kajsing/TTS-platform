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
    private StreamWriter? _writer;

    public JsonlPlaybackPerformanceSink(
        string? path = null,
        long maximumBytes = DefaultMaximumBytes)
    {
        Path = path ?? DesktopPaths.PlaybackPerformanceLogPath;
        if (maximumBytes <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumBytes));
        }

        try
        {
            var directory = System.IO.Path.GetDirectoryName(Path)
                ?? throw new ArgumentException("The performance log path has no directory.", nameof(path));
            Directory.CreateDirectory(directory);
            RotateIfNeeded(Path, maximumBytes);
            _writer = new StreamWriter(
                new FileStream(Path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
            {
                AutoFlush = true,
            };
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
                _writer.WriteLine(JsonSerializer.Serialize(
                    new PerformanceLogEntry(DateTimeOffset.UtcNow, performanceEvent),
                    JsonOptions));
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
        File.Move(path, previous, overwrite: true);
    }

    private sealed record PerformanceLogEntry(
        DateTimeOffset TimestampUtc,
        PlaybackPerformanceEvent Performance);
}
