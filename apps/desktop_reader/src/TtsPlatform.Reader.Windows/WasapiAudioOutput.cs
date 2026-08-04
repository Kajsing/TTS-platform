using NAudio.CoreAudioApi;
using NAudio.Wave;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

public sealed class WasapiAudioOutput : IAudioOutput
{
    public static readonly TimeSpan MaximumBufferedDuration = TimeSpan.FromSeconds(10);
    public static readonly TimeSpan TargetBufferedDuration = TimeSpan.FromSeconds(2);
    private static readonly TimeSpan TargetLatency = TimeSpan.FromMilliseconds(100);
    private readonly object _sync = new();
    private readonly SemaphoreSlim _playGate = new(1, 1);
    private WasapiOut? _output;
    private BufferedWaveProvider? _buffer;
    private PcmAudioFormat? _format;
    private long _generation;
    private long _submittedBytes;
    private long _confirmedPlayedBytes;
    private bool _disposed;

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
                var bufferedBytes = _buffer?.BufferedBytes ?? 0;
                var latencyBytes = _format is null ? 0 : BytesFor(_format, TargetLatency);
                var estimatedPlayedBytes = Math.Max(
                    0,
                    _submittedBytes - bufferedBytes - latencyBytes);
                return new AudioPlaybackCheckpoint(
                    _generation,
                    Math.Max(_confirmedPlayedBytes, estimatedPlayedBytes));
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
                var samples = pcmBytes.ToArray();
                _buffer!.AddSamples(samples, 0, samples.Length);
                _submittedBytes = checked(_submittedBytes + samples.Length);
                if (_output!.PlaybackState != PlaybackState.Playing)
                {
                    _output.Play();
                }
            }

            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                lock (_sync)
                {
                    if (_buffer is null ||
                        _format is null ||
                        _buffer.BufferedBytes <= BufferedBytesFor(_format, TargetBufferedDuration))
                    {
                        return;
                    }
                }
                await Task.Delay(10, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
            StopCore();
            throw;
        }
        finally
        {
            _playGate.Release();
        }
    }

    public async Task DrainAsync(CancellationToken cancellationToken = default)
    {
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            lock (_sync)
            {
                ObjectDisposedException.ThrowIf(_disposed, this);
                if (_buffer is null || _buffer.BufferedBytes == 0)
                {
                    break;
                }
            }
            await Task.Delay(10, cancellationToken).ConfigureAwait(false);
        }

        await Task.Delay(TargetLatency, cancellationToken).ConfigureAwait(false);
        lock (_sync)
        {
            _confirmedPlayedBytes = _submittedBytes;
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
            _output?.Stop();
            _output?.Dispose();
            _output = null;
            _buffer = null;
            _format = null;
            ResetCheckpoints();
        }
        _playGate.Dispose();
        return ValueTask.CompletedTask;
    }

    private void EnsureFormat(PcmAudioFormat format)
    {
        if (_output is not null && _format == format)
        {
            return;
        }

        _output?.Stop();
        _output?.Dispose();
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
        _output = new WasapiOut(
            AudioClientShareMode.Shared,
            useEventSync: false,
            latency: (int)TargetLatency.TotalMilliseconds);
        _output.Init(_buffer);
        _format = format;
        ResetCheckpoints();
    }

    private void StopCore()
    {
        lock (_sync)
        {
            if (_disposed)
            {
                return;
            }

            _output?.Stop();
            _buffer?.ClearBuffer();
            ResetCheckpoints();
        }
    }

    private void ResetCheckpoints()
    {
        _generation = checked(_generation + 1);
        _submittedBytes = 0;
        _confirmedPlayedBytes = 0;
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
