using System.Reflection;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ReaderDocumentLoaderTests
{
    [Fact]
    public async Task Load_uses_fresh_metadata_and_keeps_all_appended_blocks()
    {
        var (client, fake) = Client();
        fake.Current = fake.Current with { RowVersion = 12, ContentRevision = 9, TotalBlocks = 501 };
        fake.Blocks = (after, _) => Task.FromResult(new BlockPage(
            after < 0 ? [Block(0)] : [Block(500)], after < 0 ? 499 : null));
        var result = await new ReaderDocumentLoader(client).LoadAsync("article");
        Assert.Equal(12, result.Document.RowVersion);
        Assert.Equal(9, result.Document.ContentRevision);
        Assert.Equal(2, result.ContinuousText!.Blocks.Count);
        Assert.Contains("block 500", result.ContinuousText.Text);
    }

    [Fact]
    public async Task Revision_changed_during_load_retries_with_a_fresh_snapshot()
    {
        var (client, fake) = Client();
        fake.Blocks = (_, _) =>
        {
            fake.Current = fake.Current with { RowVersion = 2, ContentRevision = 2 };
            return Task.FromResult(new BlockPage([Block(0)], null));
        };
        var result = await new ReaderDocumentLoader(client).LoadAsync("article");
        Assert.Equal(2, result.Document.ContentRevision);
        Assert.Equal(4, fake.DocumentReads);
    }

    [Fact]
    public async Task Repeated_changes_have_a_bounded_retry_instead_of_a_request_loop()
    {
        var (client, fake) = Client();
        fake.Blocks = (_, _) =>
        {
            fake.Current = fake.Current with { RowVersion = fake.Current.RowVersion + 1 };
            return Task.FromResult(new BlockPage([Block(0)], null));
        };
        var error = await Assert.ThrowsAsync<ReaderApiException>(() => new ReaderDocumentLoader(client).LoadAsync("article"));
        Assert.Equal(409, error.StatusCode);
        Assert.Equal(4, fake.DocumentReads);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Deleted_articles_cannot_be_loaded_even_if_API_returns_metadata(bool initiallyDeleted)
    {
        var (client, fake) = Client();
        if (initiallyDeleted) fake.Current = fake.Current with { DeletedAt = DateTimeOffset.UtcNow };
        fake.Blocks = (_, _) =>
        {
            fake.Current = fake.Current with { DeletedAt = DateTimeOffset.UtcNow };
            return Task.FromResult(new BlockPage([Block(0)], null));
        };
        var error = await Assert.ThrowsAsync<ReaderApiException>(() => new ReaderDocumentLoader(client).LoadAsync("article"));
        Assert.Equal(404, error.StatusCode);
        Assert.Equal(initiallyDeleted ? 1 : 2, fake.DocumentReads);
    }

    [Fact]
    public async Task Large_or_structured_document_keeps_a_bounded_first_page()
    {
        var (client, fake) = Client();
        fake.Current = fake.Current with { TotalCharacters = 2_000_000 };
        fake.Blocks = (_, limit) =>
        {
            Assert.Equal(64, limit);
            return Task.FromResult(new BlockPage([Block(0)], 63));
        };
        var result = await new ReaderDocumentLoader(client).LoadAsync("article");
        Assert.Null(result.ContinuousText);
        Assert.True(result.Page.HasNext);
        Assert.Same(result.Page, result.ReadingWindow.Current);
        Assert.Equal(2, fake.DocumentReads);
    }

    [Fact]
    public async Task A_late_library_response_cannot_resurrect_a_confirmed_deletion()
    {
        var (client, fake) = Client();
        var pending = new TaskCompletionSource<DocumentPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.LibraryPage = pending.Task;
        var library = new LibraryPager(client);
        library.Documents.Add(fake.Current);
        var refresh = library.RefreshAsync();
        library.RemoveDocument(fake.Current.Id);
        pending.SetResult(new DocumentPage([fake.Current], null));
        await refresh;
        Assert.Empty(library.Documents);
        library.ReplaceDocument(fake.Current);
        Assert.Empty(library.Documents);
    }

    private static (IReaderServiceClient, LoaderClient) Client()
    {
        var client = DispatchProxy.Create<IReaderServiceClient, LoaderClient>();
        return (client, (LoaderClient)client);
    }

    private static ReaderBlock Block(int ordinal) => new($"b-{ordinal}", "article", "section", ordinal,
        "paragraph", $"block {ordinal}", 10, "hash", 1, JsonSerializer.SerializeToElement(new { }));

    public class LoaderClient : DispatchProxy
    {
        public ReaderDocument Current { get; set; } = new("article", "Title", "clipboard", null, null, null, null,
            "inbox", DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, null,
            1, 1, 1, 1, 10, JsonSerializer.SerializeToElement(new { }));
        public int DocumentReads { get; private set; }
        public Func<int, int, Task<BlockPage>> Blocks { get; set; } = (_, _) => Task.FromResult(new BlockPage([Block(0)], null));
        public Task<DocumentPage>? LibraryPage { get; set; }

        protected override object? Invoke(MethodInfo? method, object?[]? args)
        {
            switch (method?.Name)
            {
                case nameof(IReaderServiceClient.GetDocumentAsync):
                    DocumentReads++;
                    return Task.FromResult(Current);
                case nameof(IReaderServiceClient.GetBlocksAsync):
                    return Blocks((int)args![1]!, (int)args[2]!);
                case nameof(IReaderServiceClient.GetDocumentsByFolderAsync):
                    return LibraryPage!;
                default: throw new InvalidOperationException($"Unexpected test method: {method?.Name}");
            }
        }
    }
}
