using NAudio.Wave;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

public sealed record DecodedPcm(PcmAudioFormat Format, byte[] Bytes);

public static class WavePcmDecoder
{
    private const int MaximumWaveBytes = 64 * 1024 * 1024;

    public static DecodedPcm Decode(ReadOnlyMemory<byte> waveBytes)
    {
        if (waveBytes.IsEmpty || waveBytes.Length > MaximumWaveBytes)
        {
            throw new InvalidDataException("Immediate speech WAV data is empty or oversized.");
        }
        using var stream = new MemoryStream(waveBytes.ToArray(), writable: false);
        using var reader = new WaveFileReader(stream);
        var format = reader.WaveFormat;
        if (format.Encoding != WaveFormatEncoding.Pcm ||
            format.BitsPerSample != 16 ||
            format.Channels != 1 ||
            format.SampleRate is < 8_000 or > 192_000)
        {
            throw new InvalidDataException("Immediate speech requires mono PCM16 WAV audio.");
        }
        if (reader.Length <= 0 || reader.Length > MaximumWaveBytes)
        {
            throw new InvalidDataException("Immediate speech WAV payload is empty or oversized.");
        }

        var pcm = new byte[reader.Length];
        var offset = 0;
        while (offset < pcm.Length)
        {
            var read = reader.Read(pcm, offset, pcm.Length - offset);
            if (read == 0)
            {
                break;
            }
            offset += read;
        }
        if (offset != pcm.Length)
        {
            Array.Resize(ref pcm, offset);
        }
        return new DecodedPcm(new PcmAudioFormat(format.SampleRate, 1, 16), pcm);
    }
}
