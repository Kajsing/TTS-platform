using System.Text.Json;
using TtsPlatform.Reader.Client;

internal static class RequestBudgetSmoke
{
    public static async Task<int> RunAsync(string baseUrl, ITokenProvider token)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        var cooldown = new ReaderRequestCooldown();
        var client = new ReaderServiceClient(http, baseUrl, token, cooldown: cooldown);
        var document = (await client.GetDocumentsAsync(limit: 1, cancellationToken: timeout.Token)).Documents.Single();
        var exhausted = false;
        for (var i = 0; i < 20; i++)
        {
            try { await client.GetLocalStatusAsync(timeout.Token); }
            catch (ReaderApiException error) when (error.StatusCode == 429)
            {
                Require(error.Details["request_budget"] as string == ReaderRequestBudget.Background);
                exhausted = true;
                break;
            }
        }
        Require(exhausted);
        Require(cooldown.RemainingSecondsFor(ReaderRequestBudget.Background) > 0);
        Require(cooldown.RemainingSecondsFor(ReaderRequestBudget.Playback) == 0);
        var metadata = await client.GetDocumentAsync(document.Id, timeout.Token);
        var block = (await client.GetBlocksAsync(document.Id, cancellationToken: timeout.Token)).Blocks.Single();
        var cursor = new ReaderCursor(document.Id, block.Id, block.Ordinal, 0, metadata.ContentRevision);
        var stream = new ReaderStreamClient(baseUrl, token, cooldown: cooldown);
        var pcmBytes = 0;
        var spans = 0;
        ReaderStreamDone? done = null;
        await using (var session = await stream.OpenAsync(new ReaderStreamStartRequest(document.Id, cursor), timeout.Token))
        {
            await foreach (var item in session.ReadEventsAsync(timeout.Token))
            {
                if (item is ReaderAudioPacket audio) { pcmBytes += audio.PcmBytes.Length; spans += audio.SourceSpans.Count; }
                else if (item is ReaderStreamDone complete) done = complete;
                else if (item is ReaderStreamError) throw new InvalidOperationException("Background saturation blocked live speech.");
            }
            await session.ReleaseAsync(timeout.Token);
        }
        Require(done is not null && pcmBytes > 0 && spans > 0);
        var position = await client.SavePositionAsync(document.Id,
            new SavePositionRequest(done!.Cursor, ExpectedRowVersion: 0), timeout.Token);
        Require((await client.GetPositionAsync(document.Id, timeout.Token))?.Cursor == position.Cursor);
        using var wave = new MemoryStream(await client.SynthesizeAsync(new EphemeralSynthesisRequest("Synthetic immediate speech."), timeout.Token));
        Require(wave.Length > 44);
        var playbackExhausted = false;
        for (var i = 0; i < 30; i++)
        {
            try { await client.GetPositionAsync(document.Id, timeout.Token); }
            catch (ReaderApiException error) when (error.StatusCode == 429)
            {
                Require(error.Details["request_budget"] as string == ReaderRequestBudget.Playback);
                playbackExhausted = true;
                break;
            }
        }
        Require(playbackExhausted);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            independent_request_budgets = true,
            background_saturation = true,
            playback_still_limited = true,
            live_position_resume = true,
            pcm_bytes = pcmBytes,
            source_spans = spans,
        }));
        return 0;
    }

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidOperationException("Live request-budget acceptance failed.");
    }
}
