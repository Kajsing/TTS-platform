using System.Text.Json;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class PlaybackPerformanceLogTests
{
    [Fact]
    public void Jsonl_sink_writes_versioned_privacy_safe_entries_and_rotates_existing_file()
    {
        var directory = Path.Combine(Path.GetTempPath(), $"tts-reader-log-{Guid.NewGuid():N}");
        var path = Path.Combine(directory, "playback-performance.jsonl");
        Directory.CreateDirectory(directory);
        try
        {
            File.WriteAllLines(path, Enumerable.Repeat("{\"old\":true}", 400));
            using (var sink = new JsonlPlaybackPerformanceSink(
                path,
                maximumBytes: 4096,
                desktopSessionId: "desktop-session",
                appVersion: "1.2.3"))
            {
                sink.Record(new PlaybackPerformanceEvent(
                    "audio_packet_sample",
                    RunId: "playback-run",
                    DocumentId: "document-id",
                    WindowIndex: 1,
                    ChunkIndex: 2,
                    GapMs: 350,
                    PcmBytes: 4096,
                    AudioDurationMs: 100,
                    BufferAfterMs: 275,
                    SuspectedUnderruns: 3));
            }

            Assert.True(File.Exists(Path.ChangeExtension(path, ".previous.jsonl")));
            Assert.InRange(
                new FileInfo(Path.ChangeExtension(path, ".previous.jsonl")).Length,
                1,
                4096);
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            Assert.Equal(2, root.GetProperty("schema_version").GetInt32());
            Assert.Equal("desktop-session", root.GetProperty("desktop_session_id").GetString());
            Assert.Equal("1.2.3", root.GetProperty("app_version").GetString());
            Assert.Equal("audio_packet_sample", root.GetProperty("performance").GetProperty("name").GetString());
            Assert.Equal("playback-run", root.GetProperty("performance").GetProperty("run_id").GetString());
            Assert.Equal(350, root.GetProperty("performance").GetProperty("gap_ms").GetInt64());
            Assert.Equal(3, root.GetProperty("performance").GetProperty("suspected_underruns").GetInt64());
            Assert.DoesNotContain("title", root.ToString(), StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("text", root.ToString(), StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void Jsonl_sink_rotates_while_the_same_process_keeps_recording()
    {
        var directory = Path.Combine(Path.GetTempPath(), $"tts-reader-log-{Guid.NewGuid():N}");
        var path = Path.Combine(directory, "playback-performance.jsonl");
        Directory.CreateDirectory(directory);
        try
        {
            using (var sink = new JsonlPlaybackPerformanceSink(
                path,
                maximumBytes: 1024,
                desktopSessionId: "desktop-session",
                appVersion: "1.2.3"))
            {
                for (var index = 0; index < 40; index++)
                {
                    sink.Record(new PlaybackPerformanceEvent(
                        "state_change",
                        RunId: "playback-run",
                        DocumentId: "document-id",
                        ChunkIndex: index,
                        State: $"state-{index}"));
                }
            }

            var previous = Path.ChangeExtension(path, ".previous.jsonl");
            Assert.True(File.Exists(previous));
            Assert.InRange(new FileInfo(path).Length, 1, 1024);
            Assert.InRange(new FileInfo(previous).Length, 1, 1024);
            Assert.Contains("state-39", File.ReadAllText(path), StringComparison.Ordinal);
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }
}
