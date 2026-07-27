using System.Text.Json;
using TtsPlatform.Reader.Client;

if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: client-smoke <service-base-url> <token-file>");
    return 2;
}

using var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
var client = new ReaderServiceClient(httpClient, args[0], new SmokeTokenProvider(args[1]));
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

Console.WriteLine(JsonSerializer.Serialize(new
{
    live_reader_paging = true,
    live_utf16_edit = true,
    first_page_count = first.Documents.Count,
    second_page_count = second.Documents.Count,
}));
return 0;

file sealed class SmokeTokenProvider(string tokenPath) : ITokenProvider
{
    public async ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) =>
        (await File.ReadAllTextAsync(tokenPath, cancellationToken)).Trim();
}
