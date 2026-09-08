using System.Diagnostics;
using NAudio.CoreAudioApi;
using NAudio.Wave;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

public sealed class WasapiAudioOutput : IAudioOutput, IAudioOutputDiagnostics
{
    public static readonly TimeSpan MaximumBufferedDuration = TimeSpan.FromSeconds(10);
    public static readonly TimeSpan TargetBufferedDuration = TimeSpan.FromSeconds(2);
    private static readonly TimeSpan TargetLatency = TimeSpan.FromMilliseconds(100);
    private readonly object _sync = new();
    private readonly SemaphoreSlim _playGate = new(1, 1);
    private readonly Func<IWavePlayer> _createOutput;
    private readonly TimeSpan _stallTimeout;
    private IWavePlayer? _output;
    private OutputHealth? _health;
    private EventHandler<StoppedEventArgs>? _stoppedHandler;
    private BufferedWaveProvider? _buffer;
    private PcmAudioFormat? _format;
    private long _generation;
    private long _submittedBytes;
    private long _confirmedPlayedBytes;
    private long _lastReportedPlayedBytes;
    private long _suspectedUnderrunCount;
    private bool _detectUnderrun;
    private bool _disposed;

    public WasapiAudioOutput() : this(() => new WasapiOut(
        AudioClientShareMode.Shared, useEventSync: false,
        latency: (int)TargetLatency.TotalMilliseconds), TimeSpan.FromSeconds(3))
    { }

    // Inject only the device boundary; tests exercise the real buffering and
    // checkpoint implementation without opening the user's speakers.
    internal WasapiAudioOutput(Func<IWavePlayer> createOutput, TimeSpan stallTimeout)
    {
        _createOutput = createOutput;
        _stallTimeout = stallTimeout;
    }

    public AudioOutputSnapshot Snapshot
    {
        get
        {
            lock (_sync)
            {
                return new AudioOutputSnapshot(
                    BufferedDurationMs: BufferedDurationMilliseconds(),
                    SuspectedUnderrunCount: _suspectedUnderrunCount,
                    IsPlaying: _output?.PlaybackState == PlaybackState.Playing);
            }
        }
    }

    public AudioPlaybackCheckpoint SubmittedCheckpoint
    {
        get
        {
            lock (_sync)
            {
                return new AudioPlaybackCheckpoint(_generation, _submittedBytes);
            }
        }
    }

    public AudioPlaybackCheckpoint PlayedCheckpoint
    {
        get
        {
            lock (_sync)
            {
                if (_health is { } health && Volatile.Read(ref health.Failure) is not null)
                    return new AudioPlaybackCheckpoint(_generation, _lastReportedPlayedBytes);
                var bufferedBytes = _buffer?.BufferedBytes ?? 0;
                var latencyBytes = _format is null ? 0 : BytesFor(_format, TargetLatency);
                var estimatedPlayedBytes = Math.Max(
                    0,
                    _submittedBytes - bufferedBytes - latencyBytes);
                _lastReportedPlayedBytes = Math.Max(_lastReportedPlayedBytes,
                    Math.Max(_confirmedPlayedBytes, estimatedPlayedBytes));
                return new AudioPlaybackCheckpoint(_generation, _lastReportedPlayedBytes);
            }
        }
    }

    public static int MaximumBufferedBytes(PcmAudioFormat format)
    {
        ValidateFormat(format);
        return checked(
            format.SampleRateHz *
            format.Channels *
            (format.BitsPerSample / 8) *
            (int)MaximumBufferedDuration.TotalSeconds);
    }

    public async Task PlayAsync(
        ReadOnlyMemory<byte> pcmBytes,
        PcmAudioFormat format,
        CancellationToken cancellationToken = default)
    {
        ValidateFormat(format);
        if (pcmBytes.IsEmpty)
        {
            return;
        }
        if (pcmBytes.Length > MaximumBufferedBytes(format))
        {
            throw new ArgumentOutOfRangeException(
                nameof(pcmBytes),
                "A Reader PCM packet exceeds the ten-second audio buffer limit.");
        }

        await _playGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            lock (_sync)
            {
                ObjectDisposedException.ThrowIf(_disposed, this);
                EnsureFormat(format);
                ThrowIfDeviceFailed();
                if (_detectUnderrun &&
                    _buffer!.BufferedBytes == 0 &&
                    _output!.PlaybackState == PlaybackState.Playing)
                {
                    _suspectedUnderrunCount = checked(_suspectedUnderrunCount + 1);
                }
                var samples = pcmBytes.ToArray();
                _buffer!.AddSamples(samples, 0, samples.Length);
                _submittedBytes = checked(_submittedBytes + samples.Length);
                _detectUnderrun = true;
                if (_output!.PlaybackState != PlaybackState.Playing)
                {
                    try { _output.Play(); }
                    catch (Exception exception)
                    {
                        if (_health is { } health) Interlocked.Exchange(ref health.Failure, exception);
                        throw new AudioOutputException(AudioOutputFailure.Unavailable, exception);
                    }
                }
            }
            await WaitForBufferAsync(BufferedBytesFor(format, TargetBufferedDuration), cancellationToken)
                .ConfigureAwait(false);
        }
        finally
        {
            _playGate.Release();
        }
    }

    public async Task DrainAsync(CancellationToken cancellationToken = default)
    {
        await _playGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            long generation;
            lock (_sync) generation = _generation;
            await WaitForBufferAsync(0, cancellationToken).ConfigureAwait(false);
            await Task.Delay(TargetLatency, cancellationToken).ConfigureAwait(false);
            lock (_sync)
            {
                ThrowIfDeviceFailed();
                if (generation != _generation) throw new OperationCanceledException("Audio output was stopped.");
                _confirmedPlayedBytes = _submittedBytes;
                _detectUnderrun = false;
            }
        }
        finally { _playGate.Release(); }
    }

    private async Task WaitForBufferAsync(int targetBytes, CancellationToken cancellationToken)
    {
        var lastProgress = Stopwatch.GetTimestamp();
        var lastBuffered = int.MaxValue;
        long generation;
        lock (_sync) generation = _generation;
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            lock (_sync)
            {
                ObjectDisposedException.ThrowIf(_disposed, this);
                if (generation != _generation) throw new OperationCanceledException("Audio output was stopped.");
                ThrowIfDeviceFailed();
                var buffered = _buffer?.BufferedBytes ?? 0;
                if (buffered <= targetBytes) return;
                if (buffered < lastBuffered) lastProgress = Stopwatch.GetTimestamp();
                else if (Stopwatch.GetElapsedTime(lastProgress) >= _stallTimeout)
                {
                    var failure = new AudioOutputException(AudioOutputFailure.Stalled);
                    if (_health is { } health) Interlocked.Exchange(ref health.Failure, failure);
                    throw failure;
                }
                lastBuffered = buffered;
            }
            await Task.Delay(10, cancellationToken).ConfigureAwait(false);
        }
    }

    public Task StopAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        StopCore();
        return Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        lock (_sync)
        {
            if (_disposed)
            {
                return ValueTask.CompletedTask;
            }

            _disposed = true;
            ReleaseOutput();
            ResetCheckpoints();
        }
        // A cancelled in-flight write still owns its release. The managed gate
        // is collected with this instance; disposing it here races that writer.
        return ValueTask.CompletedTask;
    }

    private void EnsureFormat(PcmAudioFormat format)
    {
        if (_output is not null && _format == format)
        {
            return;
        }

        ReleaseOutput();
        var waveFormat = new WaveFormat(
            format.SampleRateHz,
            format.BitsPerSample,
            format.Channels);
        _buffer = new BufferedWaveProvider(waveFormat)
        {
            BufferDuration = MaximumBufferedDuration,
            DiscardOnBufferOverflow = false,
            ReadFully = true,
        };
        try
        {
            _output = _createOutput();
            var health = _health = new OutputHealth();
            // Never take _sync in this callback: Stop/Dispose may join NAudio's
            // worker while holding it. A detached device cannot fault its successor.
            _stoppedHandler = (_, args) => Interlocked.Exchange(ref health.Failure,
                args.Exception ?? new InvalidOperationException("Audio output stopped unexpectedly."));
            _output.PlaybackStopped += _stoppedHandler;
            _output.Init(_buffer);
            _format = format;
            ResetCheckpoints();
        }
        catch (Exception exception)
        {
            ReleaseOutput();
            throw new AudioOutputException(AudioOutputFailure.Unavailable, exception);
        }
    }

    private void StopCore()
    {
        lock (_sync)
        {
            if (_disposed)
            {
                return;
            }

            // Pausing cancels playback, so no output device needs to survive
            // idle time or Windows sleep. Next Play opens the current endpoint.
            ReleaseOutput();
            ResetCheckpoints();
        }
    }

    private void ReleaseOutput()
    {
        var output = _output;
        if (output is not null && _stoppedHandler is not null)
            output.PlaybackStopped -= _stoppedHandler;
        _output = null;
        _health = null;
        _stoppedHandler = null;
        _buffer = null;
        _format = null;
        if (output is null) return;
        // A lost endpoint may also throw during cleanup. Forget its ownership
        // regardless, so one broken device cannot prevent a fresh Play.
        try { output.Stop(); }
        catch (Exception) { /* Device is already lost; still release it. */ }
        try { output.Dispose(); }
        catch (Exception) { /* No stale output reference may be reused. */ }
    }

    private void ThrowIfDeviceFailed()
    {
        if (_health is { } health && Volatile.Read(ref health.Failure) is { } failure)
            throw failure is AudioOutputException audioFailure ? audioFailure :
                new AudioOutputException(AudioOutputFailure.Unavailable, failure);
    }

    private sealed class OutputHealth
    {
        internal Exception? Failure;
    }

    private void ResetCheckpoints()
    {
        _generation = checked(_generation + 1);
        _submittedBytes = 0;
        _confirmedPlayedBytes = 0;
        _lastReportedPlayedBytes = 0;
        _suspectedUnderrunCount = 0;
        _detectUnderrun = false;
    }

    private double BufferedDurationMilliseconds()
    {
        if (_buffer is null || _format is null)
        {
            return 0;
        }
        var bytesPerSecond = BytesFor(_format, TimeSpan.FromSeconds(1));
        return bytesPerSecond == 0
            ? 0
            : Math.Round(_buffer.BufferedBytes * 1000d / bytesPerSecond, 2);
    }

    private static void ValidateFormat(PcmAudioFormat format)
    {
        if (format.SampleRateHz is < 8_000 or > 192_000 ||
            format.Channels != 1 ||
            format.BitsPerSample != 16)
        {
            throw new ArgumentOutOfRangeException(
                nameof(format),
                "Reader playback supports mono signed PCM16 from 8 kHz through 192 kHz.");
        }
    }

    private static int BufferedBytesFor(PcmAudioFormat format, TimeSpan duration) => checked(
        (int)BytesFor(format, duration));

    private static long BytesFor(PcmAudioFormat format, TimeSpan duration) => checked(
        (long)(format.SampleRateHz *
        format.Channels *
        (format.BitsPerSample / 8) *
        duration.TotalSeconds));
}
