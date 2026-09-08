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
    if (output.PlayedCheckpoint != output.SubmittedCheckpoint)
        throw new InvalidOperationException("Silent audio did not drain to its checkpoint.");
    var generation = output.SubmittedCheckpoint.Generation;
    await output.StopAsync();
    if (output.Snapshot.IsPlaying || output.Snapshot.BufferedDurationMs != 0)
        throw new InvalidOperationException("Stopped audio retained its device/buffer.");
    await output.PlayAsync(pcm, format);
    await output.DrainAsync();
    if (output.SubmittedCheckpoint.Generation <= generation || output.PlayedCheckpoint != output.SubmittedCheckpoint)
        throw new InvalidOperationException("Audio did not reopen and drain after Stop.");
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        windows_audio = true,
        output_reopened = true,
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
