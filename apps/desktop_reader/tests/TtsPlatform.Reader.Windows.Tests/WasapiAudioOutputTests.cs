using NAudio.Wave;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class WasapiAudioOutputTests
{
    private static readonly PcmAudioFormat Format = new(8000, 1, 16);
    private static readonly TimeSpan TestTimeout = TimeSpan.FromMilliseconds(100);

    [Fact]
    public async Task Pause_stop_releases_device_and_next_play_opens_a_fresh_endpoint()
    {
        var devices = new List<Device>();
        await using var output = new WasapiAudioOutput(() => { var device = new Device(); devices.Add(device); return device; }, TestTimeout);
        await output.PlayAsync(new byte[1600], Format);
        await output.PlayAsync(new byte[1600], Format);
        Assert.Single(devices);
        var generation = output.SubmittedCheckpoint.Generation;
        await output.StopAsync();
        Assert.Equal(1, devices[0].Disposals);
        Assert.False(output.Snapshot.IsPlaying);
        Assert.Equal(0, output.PlayedCheckpoint.BytePosition);
        await output.PlayAsync(new byte[1600], Format);
        Assert.Equal(2, devices.Count);
        Assert.True(output.SubmittedCheckpoint.Generation > generation);
        devices[1].Consume(1600);
        await output.DrainAsync();
        Assert.Equal(output.SubmittedCheckpoint, output.PlayedCheckpoint);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Stalled_write_or_final_drain_is_bounded_and_never_confirms_unheard_audio(bool drain)
    {
        var device = new Device();
        await using var output = new WasapiAudioOutput(() => device, TestTimeout);
        var pending = output.PlayAsync(new byte[drain ? 1600 : 34000], Format);
        if (drain) { await pending; pending = output.DrainAsync(); }
        var error = await Assert.ThrowsAsync<AudioOutputException>(() => pending.WaitAsync(TimeSpan.FromSeconds(3)));
        Assert.Equal(AudioOutputFailure.Stalled, error.Failure);
        Assert.Equal(0, output.PlayedCheckpoint.BytePosition);
        Assert.Contains("Press Play", error.Message);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Unexpected_device_stop_is_reported_even_without_driver_exception(bool withException)
    {
        var device = new Device();
        await using var output = new WasapiAudioOutput(() => device, TestTimeout);
        await output.PlayAsync(new byte[1600], Format);
        device.Fail(withException ? new InvalidOperationException("PRIVATE driver detail") : null);
        var error = await Assert.ThrowsAsync<AudioOutputException>(() => output.DrainAsync());
        Assert.Equal(AudioOutputFailure.Unavailable, error.Failure);
        Assert.DoesNotContain("PRIVATE", error.Message);
        Assert.Equal(0, output.PlayedCheckpoint.BytePosition);
    }

    [Fact]
    public async Task Failed_initialization_is_disposed_and_does_not_poison_retry()
    {
        var bad = new Device { FailInit = true };
        var good = new Device();
        var count = 0;
        await using var output = new WasapiAudioOutput(() => ++count == 1 ? bad : good, TestTimeout);
        await Assert.ThrowsAsync<AudioOutputException>(() => output.PlayAsync(new byte[1600], Format));
        Assert.Equal(1, bad.Disposals);
        await output.PlayAsync(new byte[1600], Format);
        Assert.True(output.Snapshot.IsPlaying);
    }

    [Fact]
    public async Task Stop_releases_a_blocked_writer_and_old_callbacks_cannot_fault_the_next_device()
    {
        var old = new Device { FailStop = true };
        var next = new Device();
        var count = 0;
        await using var output = new WasapiAudioOutput(() => ++count == 1 ? old : next, TestTimeout);
        var pending = output.PlayAsync(new byte[34000], Format);
        var staleCallback = old.StoppedCallback;
        await output.StopAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending.WaitAsync(TimeSpan.FromSeconds(3)));
        Assert.Equal(1, old.Disposals);
        await output.PlayAsync(new byte[1600], Format);
        staleCallback?.Invoke(old, new StoppedEventArgs(new InvalidOperationException("Old device")));
        next.Consume(1600);
        await output.DrainAsync();
        Assert.Equal(output.SubmittedCheckpoint, output.PlayedCheckpoint);
    }

    [Fact]
    public async Task Buffer_consumption_resets_watchdog_instead_of_limiting_total_play_time()
    {
        var device = new Device();
        await using var output = new WasapiAudioOutput(() => device, TimeSpan.FromMilliseconds(300));
        await output.PlayAsync(new byte[16000], Format);
        var drain = output.DrainAsync();
        for (var i = 0; i < 8; i++)
        {
            await Task.Delay(70);
            device.Consume(2000);
        }
        await drain.WaitAsync(TimeSpan.FromSeconds(3));
        Assert.Equal(16000, output.PlayedCheckpoint.BytePosition);
    }

    [Fact]
    public async Task Device_failure_freezes_reported_progress_even_if_the_driver_discards_queued_bytes()
    {
        var device = new Device();
        await using var output = new WasapiAudioOutput(() => device, TestTimeout);
        await output.PlayAsync(new byte[16000], Format);
        device.Consume(4000);
        var heard = output.PlayedCheckpoint;
        Assert.True(heard.BytePosition > 0);
        device.Fail(new InvalidOperationException("Device lost"));
        device.Consume(12000);
        Assert.Equal(heard, output.PlayedCheckpoint);
        await Assert.ThrowsAsync<AudioOutputException>(() => output.DrainAsync());
        Assert.Equal(heard, output.PlayedCheckpoint);
    }

    [Fact]
    public async Task Cancelled_drain_does_not_confirm_queued_bytes_and_disposal_is_idempotent()
    {
        var device = new Device();
        var output = new WasapiAudioOutput(() => device, TestTimeout);
        await output.PlayAsync(new byte[1600], Format);
        using var cancel = new CancellationTokenSource();
        var drain = output.DrainAsync(cancel.Token);
        cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => drain);
        Assert.Equal(0, output.PlayedCheckpoint.BytePosition);
        await output.DisposeAsync();
        await output.DisposeAsync();
        Assert.Equal(1, device.Disposals);
    }

    private sealed class Device : IWavePlayer
    {
        private IWaveProvider? _provider;
        public bool FailInit { get; init; }
        public bool FailStop { get; init; }
        public int Disposals { get; private set; }
        public float Volume { get; set; }
        public WaveFormat OutputWaveFormat => _provider?.WaveFormat ?? new WaveFormat(8000, 16, 1);
        public PlaybackState PlaybackState { get; private set; }
        public event EventHandler<StoppedEventArgs>? PlaybackStopped;
        public EventHandler<StoppedEventArgs>? StoppedCallback => PlaybackStopped;
        public void Init(IWaveProvider provider)
        {
            if (FailInit) throw new InvalidOperationException("PRIVATE initialization detail");
            _provider = provider;
        }
        public void Consume(int count) => _provider!.Read(new byte[count], 0, count);
        public void Play() => PlaybackState = PlaybackState.Playing;
        public void Pause() => PlaybackState = PlaybackState.Paused;
        public void Stop()
        {
            PlaybackState = PlaybackState.Stopped;
            if (FailStop) throw new InvalidOperationException("Lost endpoint");
        }
        public void Fail(Exception? error)
        {
            PlaybackState = PlaybackState.Stopped;
            PlaybackStopped?.Invoke(this, new StoppedEventArgs(error));
        }
        public void Dispose() => Disposals++;
    }
}
