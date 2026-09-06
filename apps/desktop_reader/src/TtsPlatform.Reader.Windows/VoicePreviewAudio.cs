using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

public sealed class VoicePreviewAudio(IAudioOutput? output = null) : IVoicePreviewAudio
{
    private readonly IAudioOutput _output = output ?? new WasapiAudioOutput();
    private DecodedPcm? _decoded;
    public TimeSpan Load(ReadOnlyMemory<byte> wave)
    {
        if (wave.Length > 2 * 1024 * 1024) throw new VoiceLibraryException("The preview audio is too large.");
        try { _decoded = WavePcmDecoder.Decode(wave); }
        catch (Exception error) when (error is IOException or InvalidDataException or FormatException or ArgumentException)
        { throw new VoiceLibraryException("The voice returned an unsupported audio sample."); }
        return TimeSpan.FromSeconds((double)_decoded.Bytes.Length / (_decoded.Format.SampleRateHz * 2));
    }
    public async Task PlayAsync(CancellationToken cancellationToken)
    {
        var data = _decoded ?? throw new InvalidOperationException("Load preview audio first.");
        var frameSize = Math.Max(2, data.Format.SampleRateHz * 2 * 40 / 1000);
        frameSize -= frameSize % 2;
        for (var offset = 0; offset < data.Bytes.Length; offset += frameSize)
            await _output.PlayAsync(data.Bytes.AsMemory(offset, Math.Min(frameSize, data.Bytes.Length - offset)), data.Format, cancellationToken);
        await _output.DrainAsync(cancellationToken);
    }
    public Task StopAsync() => _output.StopAsync();
    public ValueTask DisposeAsync() => _output.DisposeAsync();
}
