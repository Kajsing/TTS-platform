using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

if (args.Length != 3)
{
    Console.Error.WriteLine("Usage: playback-smoke <service-base-url> <token-file> <document-id>");
    return 2;
}

using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(2));
using var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
var tokenProvider = new SmokeTokenProvider(args[1]);
var serviceClient = new ReaderServiceClient(httpClient, args[0], tokenProvider);
var page = await serviceClient.GetDocumentsAsync(limit: 50, cancellationToken: timeout.Token);
var document = page.Documents.SingleOrDefault(item => item.Id == args[2]);
if (document is null)
{
    Console.Error.WriteLine("The real-voice smoke document was not found.");
    return 3;
}

await using var playback = new ReaderPlaybackCoordinator(
    serviceClient,
    new ReaderStreamClient(args[0], tokenProvider),
    new WasapiAudioOutput());
var terminal = new TaskCompletionSource<PlaybackStateChanged>(
    TaskCreationOptions.RunContinuationsAsynchronously);
var highlightCount = 0;
playback.HighlightChanged += (_, _) => Interlocked.Increment(ref highlightCount);
playback.StateChanged += (_, change) =>
{
    if (change.State is ReaderPlaybackState.Completed or ReaderPlaybackState.Faulted)
    {
        terminal.TrySetResult(change);
    }
};

await playback.PlayAsync(document, cancellationToken: timeout.Token);
var result = await terminal.Task.WaitAsync(timeout.Token);
if (result.State != ReaderPlaybackState.Completed)
{
    Console.Error.WriteLine($"Reader playback failed: {result.Message}");
    return 4;
}

Console.WriteLine(JsonSerializer.Serialize(new
{
    real_voice_playback = true,
    document_id = document.Id,
    completed = true,
    highlight_count = highlightCount,
    final_block_ordinal = result.Cursor?.BlockOrdinal,
    final_character_offset = result.Cursor?.CharacterOffset,
}));
return 0;

file sealed class SmokeTokenProvider(string tokenPath) : ITokenProvider
{
    public async ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) =>
        (await File.ReadAllTextAsync(tokenPath, cancellationToken)).Trim();
}
