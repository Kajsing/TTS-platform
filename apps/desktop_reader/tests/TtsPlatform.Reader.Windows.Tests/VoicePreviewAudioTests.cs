using NAudio.Wave;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class VoicePreviewAudioTests
{
    [Fact]
    public async Task Decodes_bounded_PCM16_WAV_then_submits_small_frames_and_drains()
    {
        var output = new Output();
        await using (var audio = new VoicePreviewAudio(output))
        {
            Assert.Equal(TimeSpan.FromSeconds(1), audio.Load(Wave()));
            await audio.PlayAsync(CancellationToken.None);
            Assert.Equal(25, output.Frames.Count);
            Assert.All(output.Frames, frame => Assert.Equal(1920, frame));
            Assert.True(output.Drained);
            await audio.StopAsync();
            Assert.True(output.Stopped);
        }
        Assert.True(output.Disposed);
    }

    [Theory]
    [InlineData("empty")]
    [InlineData("junk")]
    [InlineData("oversize")]
    [InlineData("stereo")]
    public void Invalid_audio_never_reaches_output(string fault)
    {
        var output = new Output();
        var audio = new VoicePreviewAudio(output);
        byte[] bytes = fault switch
        {
            "empty" => [],
            "junk" => [1, 2, 3],
            "oversize" => new byte[2 * 1024 * 1024 + 1],
            _ => Wave(2),
        };
        Assert.Throws<VoiceLibraryException>(() => audio.Load(bytes));
        Assert.Empty(output.Frames);
    }

    [Fact]
    public async Task Cancellation_reaches_audio_output_without_draining()
    {
        var output = new Output();
        await using var audio = new VoicePreviewAudio(output);
        audio.Load(Wave());
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => audio.PlayAsync(cancellation.Token));
        Assert.Empty(output.Frames);
        Assert.False(output.Drained);
        await audio.StopAsync();
        Assert.True(output.Stopped);
    }

    private static byte[] Wave(int channels = 1)
    {
        using var stream = new MemoryStream();
        using (var writer = new WaveFileWriter(stream, new WaveFormat(24000, 16, channels)))
            writer.Write(new byte[48000 * channels], 0, 48000 * channels);
        return stream.ToArray();
    }

    private sealed class Output : IAudioOutput
    {
        internal readonly List<int> Frames = [];
        internal bool Drained, Stopped, Disposed;
        public AudioPlaybackCheckpoint SubmittedCheckpoint => new(0, 0);
        public AudioPlaybackCheckpoint PlayedCheckpoint => new(0, 0);
        public Task PlayAsync(ReadOnlyMemory<byte> bytes, PcmAudioFormat format, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            Assert.Equal(new PcmAudioFormat(24000, 1, 16), format);
            Frames.Add(bytes.Length);
            return Task.CompletedTask;
        }
        public Task DrainAsync(CancellationToken token) { Drained = true; return Task.CompletedTask; }
        public Task StopAsync(CancellationToken token = default) { Stopped = true; return Task.CompletedTask; }
        public ValueTask DisposeAsync() { Disposed = true; return ValueTask.CompletedTask; }
    }
}
