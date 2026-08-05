using System.Text.Json;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class PlaybackPerformanceLogTests
{
    [Fact]
    public void Jsonl_sink_writes_sanitized_timing_fields_and_rotates_bounded_file()
    {
        var directory = Path.Combine(Path.GetTempPath(), $"tts-reader-log-{Guid.NewGuid():N}");
        var path = Path.Combine(directory, "playback-performance.jsonl");
        Directory.CreateDirectory(directory);
        try
        {
            File.WriteAllText(path, "old log content");
            using (var sink = new JsonlPlaybackPerformanceSink(path, maximumBytes: 4))
            {
                sink.Record(new PlaybackPerformanceEvent(
                    "audio_packet",
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
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            Assert.Equal("audio_packet", root.GetProperty("performance").GetProperty("name").GetString());
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
}
