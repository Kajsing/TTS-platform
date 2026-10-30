using System.Reflection;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class DocumentReadCoordinationTests
{
    [Fact]
    public async Task Initial_metadata_hint_uses_one_bounded_page_and_a_fresh_revision_fence()
    {
        var (client, fake) = Client();
        fake.Document = Document() with { TotalCharacters = 2_000_000, TotalBlocks = 10_000 };
        fake.Blocks = (_, limit, _) => Task.FromResult(new BlockPage(Blocks(0, limit), limit - 1));
        var loaded = await new ReaderDocumentLoader(client).LoadAsync(fake.Document);
        Assert.Null(loaded.ContinuousText);
        Assert.Equal(64, loaded.Page.Blocks.Count);
        Assert.Equal(0, fake.MetadataReads);
        Assert.Equal(1, fake.FreshReads);
        Assert.Equal(64, Assert.Single(fake.BlockRequests).Limit);
    }

    [Fact]
    public async Task Superseded_loader_cancellation_stops_before_another_page_or_metadata_read()
    {
        var (client, fake) = Client();
        var release = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.Blocks = (_, _, _) => release.Task;
        using var cancellation = new CancellationTokenSource();
        var load = new ReaderDocumentLoader(client).LoadAsync(fake.Document, cancellation.Token);
        cancellation.Cancel();
        release.SetResult(new BlockPage(Blocks(0, 500), 499));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => load);
        Assert.Single(fake.BlockRequests);
        Assert.Equal(0, fake.FreshReads);
    }

    [Fact]
    public async Task Stale_small_hint_switches_to_a_bounded_page_when_article_grows()
    {
        var (client, fake) = Client();
        var hint = fake.Document;
        fake.Document = hint with { RowVersion = 2, ContentRevision = 2, TotalCharacters = 2_000_000 };
        fake.Blocks = (_, limit, _) => Task.FromResult(new BlockPage(
            limit == 500 ? Blocks(0, 500).Select(block => block with { CharacterCount = 3000 }).ToArray() : Blocks(0, limit),
            limit - 1));
        var loaded = await new ReaderDocumentLoader(client).LoadAsync(hint);
        Assert.Null(loaded.ContinuousText);
        Assert.Equal([500, 64], fake.BlockRequests.Select(request => request.Limit));
        Assert.Equal(2, fake.FreshReads);
    }

    [Fact]
    public async Task Cancellation_during_final_fresh_fence_cannot_return_a_snapshot()
    {
        var (client, fake) = Client();
        var release = new TaskCompletionSource<ReaderDocument>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.FreshResponse = release.Task;
        using var cancellation = new CancellationTokenSource();
        var loading = new ReaderDocumentLoader(client).LoadAsync(fake.Document, cancellation.Token);
        Assert.Equal(1, fake.FreshReads);
        cancellation.Cancel();
        release.SetResult(fake.Document);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => loading);
    }

    [Fact]
    public async Task Overlapping_follow_events_join_one_inflight_window()
    {
        var (client, fake) = Client();
        var release = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.Blocks = (_, _, _) => release.Task;
        var pager = new ReadingWindowPager(client);
        pager.UsePage(new ReadingWindowPage(Blocks(0, 64), 0, 63));
        var follows = Enumerable.Range(56, 8).Select(block => pager.FollowPlaybackAsync("article", block)).ToArray();
        Assert.Equal(39, Assert.Single(fake.BlockRequests).After);
        release.SetResult(new BlockPage(Blocks(40, 64), 103));
        var pages = await Task.WhenAll(follows);
        Assert.All(pages, page => Assert.Same(pager.Current, page));
        Assert.Equal(40, pager.Current.StartOrdinal);
    }

    [Fact]
    public async Task Cancelling_one_follow_waiter_preserves_another_and_cancelling_all_stops_transport()
    {
        var (client, fake) = Client();
        var release = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.Blocks = (_, _, _) => release.Task;
        var pager = new ReadingWindowPager(client);
        using var cancellation = new CancellationTokenSource();
        var first = pager.LoadAsync("article", 40, cancellation.Token);
        var second = pager.LoadAsync("article", 40);
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first);
        Assert.False(Assert.Single(fake.BlockRequests).Token.IsCancellationRequested);
        release.SetResult(new BlockPage(Blocks(40, 64), 103));
        await second;

        release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        using var lastCancellation = new CancellationTokenSource();
        var abandoned = pager.LoadAsync("article", 80, lastCancellation.Token);
        lastCancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => abandoned);
        Assert.True(fake.BlockRequests[^1].Token.IsCancellationRequested);
        var abandonedRelease = release;
        release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        var retry = pager.LoadAsync("article", 80);
        Assert.Equal(3, fake.BlockRequests.Count);
        release.SetResult(new BlockPage(Blocks(80, 64), 143));
        var retriedPage = await retry;
        abandonedRelease.SetResult(new BlockPage(Blocks(80, 1), null));
        Assert.Same(retriedPage, pager.Current);
    }

    [Fact]
    public async Task Late_page_response_cannot_replace_newer_navigation_or_a_refreshed_document()
    {
        var (client, fake) = Client();
        var old = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        var next = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.Blocks = (after, _, _) => after == -1 ? old.Task : next.Task;
        var pager = new ReadingWindowPager(client);
        var oldLoad = pager.LoadAsync("article", 0);
        var newLoad = pager.LoadAsync("article", 64);
        next.SetResult(new BlockPage(Blocks(64, 64), 127));
        await newLoad;
        old.SetResult(new BlockPage(Blocks(0, 64), 63));
        Assert.Same(pager.Current, await oldLoad);
        Assert.Equal(64, pager.Current.StartOrdinal);

        old = new(TaskCreationOptions.RunContinuationsAsynchronously);
        var superseded = pager.LoadAsync("article", 0);
        var replacement = pager.UseLoadedDocument("replacement", Blocks(0, 1, "replacement"));
        old.SetResult(new BlockPage(Blocks(0, 64), 63));
        await superseded;
        Assert.Same(replacement, pager.Current);
    }

    [Fact]
    public async Task Find_and_highlighter_share_one_full_source_load_and_validate_its_revision()
    {
        var (client, fake) = Client();
        fake.Document = fake.Document with { TotalBlocks = 3 };
        var release = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.Blocks = (after, _, _) => after == -1 ? release.Task : Task.FromResult(new BlockPage(Blocks(2, 1), null));
        var loader = new ArticleFindDocumentLoader(client, pageSize: 2);
        var find = loader.LoadAsync(fake.Document);
        var highlighter = loader.LoadAsync(fake.Document);
        Assert.Single(fake.BlockRequests);
        release.SetResult(new BlockPage(Blocks(0, 2), 1));
        Assert.Same(await find, await highlighter);
        Assert.Equal(2, fake.BlockRequests.Count);
        Assert.Equal(1, fake.FreshReads);

        loader.Invalidate();
        var stale = fake.Document;
        fake.Document = stale with { ContentRevision = 2, RowVersion = 2 };
        await Assert.ThrowsAsync<ReaderApiException>(() => loader.LoadAsync(stale));
    }

    [Fact]
    public async Task Invalidated_find_load_cannot_repopulate_the_cache_with_a_late_result()
    {
        var (client, fake) = Client();
        var release = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.Blocks = (_, _, _) => release.Task;
        var loader = new ArticleFindDocumentLoader(client);
        var loading = loader.LoadAsync(fake.Document);
        loader.Invalidate(fake.Document.Id);
        release.SetResult(new BlockPage(Blocks(0, 1), null));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => loading);
        _ = await loader.LoadAsync(fake.Document);
        Assert.Equal(2, fake.BlockRequests.Count);
        Assert.Equal(2, fake.FreshReads);
    }

    private static (IReaderServiceClient Client, ReadClient Fake) Client()
    {
        var client = DispatchProxy.Create<IReaderServiceClient, ReadClient>();
        return (client, (ReadClient)client);
    }

    private static ReaderDocument Document() => new("article", "Synthetic", "clipboard", null, null, null, null,
        "inbox", DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, null,
        1, 1, 1, 1, 10, JsonSerializer.SerializeToElement(new { }));

    private static ReaderBlock[] Blocks(int start, int count, string id = "article") => Enumerable.Range(start, count)
        .Select(ordinal => new ReaderBlock($"b-{ordinal}", id, null, ordinal, "paragraph", $"Block {ordinal}", 10,
            "hash", 1, JsonSerializer.SerializeToElement(new { }))).ToArray();

    public class ReadClient : DispatchProxy
    {
        public ReaderDocument Document { get; set; } = DocumentReadCoordinationTests.Document();
        public int MetadataReads { get; private set; }
        public int FreshReads { get; private set; }
        public Task<ReaderDocument>? FreshResponse { get; set; }
        public List<(int After, int Limit, CancellationToken Token)> BlockRequests { get; } = [];
        public Func<int, int, CancellationToken, Task<BlockPage>> Blocks { get; set; } = (_, _, _) =>
            Task.FromResult(new BlockPage(DocumentReadCoordinationTests.Blocks(0, 1), null));
        protected override object? Invoke(MethodInfo? method, object?[]? args)
        {
            switch (method!.Name)
            {
                case nameof(IReaderServiceClient.GetDocumentAsync): MetadataReads++; return Task.FromResult(Document);
                case nameof(IReaderServiceClient.GetDocumentFreshAsync): FreshReads++; return FreshResponse ?? Task.FromResult(Document);
                case nameof(IReaderServiceClient.GetBlocksAsync):
                    var after = (int)args![1]!;
                    var limit = (int)args[2]!;
                    var token = (CancellationToken)args[3]!;
                    BlockRequests.Add((after, limit, token));
                    return Blocks(after, limit, token);
                default: throw new InvalidOperationException(method.Name);
            }
        }
    }
}
