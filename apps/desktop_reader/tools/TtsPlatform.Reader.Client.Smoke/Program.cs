using System.Text.Json;
using TtsPlatform.Reader.Client;

if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: client-smoke <service-base-url> <token-file>");
    return 2;
}

using var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
var tokenProvider = new SmokeTokenProvider(args[1]);
var client = new ReaderServiceClient(httpClient, args[0], tokenProvider);
var first = await client.GetDocumentsAsync(limit: 1);
if (first.Documents.Count != 1 || first.NextCursor is null)
{
    Console.Error.WriteLine("The live Reader service did not return the expected first page and cursor.");
    return 3;
}

var second = await client.GetDocumentsAsync(limit: 1, cursor: first.NextCursor);
if (second.Documents.Count != 1 || second.Documents[0].Id == first.Documents[0].Id)
{
    Console.Error.WriteLine("The live Reader service did not return a distinct second page.");
    return 4;
}

var documentCountBeforeImmediateSpeech = (await client.GetDocumentsAsync(limit: 50)).Documents.Count;
var immediateWave = await client.SynthesizeAsync(
    new EphemeralSynthesisRequest("Immediate clipboard smoke."));
var documentCountAfterImmediateSpeech = (await client.GetDocumentsAsync(limit: 50)).Documents.Count;
if (immediateWave.Length == 0 || documentCountAfterImmediateSpeech != documentCountBeforeImmediateSpeech)
{
    Console.Error.WriteLine("Immediate clipboard speech persisted a document or returned no audio.");
    return 9;
}

var document = first.Documents[0];
var blocks = await client.GetBlocksAsync(document.Id);
var block = blocks.Blocks.Single();
var replacement = "Edited through .NET 😀";
var mutation = await client.ReplaceContentAsync(
    document.Id,
    new ReplaceContentRequest(
        document.RowVersion,
        block.Id,
        0,
        block.Text.Length,
        replacement));
var editedBlocks = await client.GetBlocksAsync(document.Id);
if (editedBlocks.Blocks.Single().Text != replacement || mutation.Document.RowVersion <= document.RowVersion)
{
    Console.Error.WriteLine("The live UTF-16 Reader edit did not round-trip.");
    return 5;
}

var editedBlock = editedBlocks.Blocks.Single();
var streamClient = new ReaderStreamClient(args[0], tokenProvider);
var startCursor = new ReaderCursor(
    document.Id,
    editedBlock.Id,
    editedBlock.Ordinal,
    0,
    mutation.Document.ContentRevision);
var pcmFrames = 0;
var pcmBytes = 0;
var sourceSpans = 0;
ReaderStreamDone? completed = null;
await using (var session = await streamClient.OpenAsync(
    new ReaderStreamStartRequest(document.Id, startCursor)))
{
    await foreach (var streamEvent in session.ReadEventsAsync())
    {
        if (streamEvent is ReaderAudioPacket packet)
        {
            pcmFrames++;
            pcmBytes += packet.PcmBytes.Length;
            sourceSpans += packet.SourceSpans.Count;
        }
        else if (streamEvent is ReaderStreamDone done)
        {
            completed = done;
        }
        else if (streamEvent is ReaderStreamError error)
        {
            Console.Error.WriteLine($"Reader stream failed: {error.ErrorType}: {error.Message}");
            return 6;
        }
    }
    await session.ReleaseAsync();
}
if (completed is null || !completed.DocumentComplete || pcmFrames == 0 || pcmBytes == 0 || sourceSpans == 0)
{
    Console.Error.WriteLine("The live Reader WebSocket did not return paired source-mapped PCM.");
    return 7;
}

var savedPosition = await client.SavePositionAsync(
    document.Id,
    new SavePositionRequest(completed.Cursor, ExpectedRowVersion: 0));
var loadedPosition = await client.GetPositionAsync(document.Id);
if (loadedPosition?.Cursor != savedPosition.Cursor)
{
    Console.Error.WriteLine("The live Reader position did not round-trip.");
    return 8;
}

var clipboardDocument = await client.CreateDocumentAsync(
    new CreateDocumentRequest(
        "Clipboard append smoke",
        "clipboard",
        "Initial paragraph",
        AllowDuplicate: true));
var selections = new[] { "First selected excerpt", "Second selected excerpt", "Latest selected excerpt" };
foreach (var selection in selections)
{
    var appended = await client.AppendContentAsync(
        clipboardDocument.Id,
        new AppendContentRequest(clipboardDocument.RowVersion, selection));
    clipboardDocument = appended.Document;
}
var appendedBlocks = await client.GetBlocksAsync(clipboardDocument.Id);
if (appendedBlocks.Blocks.Count != 4 ||
    !appendedBlocks.Blocks.Skip(1).Select(item => item.Text).SequenceEqual(selections) ||
    appendedBlocks.Blocks.Skip(1).Any(item => item.Kind != "paragraph"))
{
    Console.Error.WriteLine("Repeated clipboard appends did not create separate paragraph operations.");
    return 10;
}

var undone = await client.UndoAsync(
    clipboardDocument.Id,
    new ExpectedVersionRequest(clipboardDocument.RowVersion));
var undoneBlocks = await client.GetBlocksAsync(clipboardDocument.Id);
if (undoneBlocks.Blocks.Count != 3 ||
    undoneBlocks.Blocks.Any(item => item.Text == selections[^1]) ||
    !undoneBlocks.Blocks.Skip(1).Select(item => item.Text).SequenceEqual(selections[..^1]) ||
    undone.Document.RowVersion <= clipboardDocument.RowVersion)
{
    Console.Error.WriteLine("One Undo did not remove exactly the latest clipboard append.");
    return 11;
}

Console.WriteLine(JsonSerializer.Serialize(new
{
    live_reader_paging = true,
    live_utf16_edit = true,
    first_page_count = first.Documents.Count,
    second_page_count = second.Documents.Count,
    live_reader_stream = true,
    live_position_resume = true,
    live_clipboard_no_persist = true,
    live_clipboard_append_undo = true,
    pcm_frames = pcmFrames,
    pcm_bytes = pcmBytes,
    source_spans = sourceSpans,
    clipboard_paragraphs_before_undo = appendedBlocks.Blocks.Count,
    clipboard_paragraphs_after_undo = undoneBlocks.Blocks.Count,
}));
return 0;

file sealed class SmokeTokenProvider(string tokenPath) : ITokenProvider
{
    public async ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) =>
        (await File.ReadAllTextAsync(tokenPath, cancellationToken)).Trim();
}
