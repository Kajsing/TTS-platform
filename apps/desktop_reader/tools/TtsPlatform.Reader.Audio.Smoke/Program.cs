using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

const int sampleRate = 22_050;
const int durationMilliseconds = 200;
var format = new PcmAudioFormat(sampleRate, 1, 16);
var pcm = new byte[sampleRate * 2 * durationMilliseconds / 1000];

try
{
    await using var output = new WasapiAudioOutput();
    await output.PlayAsync(pcm, format);
    await output.DrainAsync();
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        windows_audio = true,
        sample_rate_hz = sampleRate,
        channels = 1,
        duration_ms = durationMilliseconds,
        maximum_buffer_seconds = WasapiAudioOutput.MaximumBufferedDuration.TotalSeconds,
    }));
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine($"Windows audio smoke failed: {exception.GetType().Name}: {exception.Message}");
    return 1;
}
