using System.Reflection;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class PagedChapterNavigationTests
{
    [Fact]
    public void The_empty_document_has_an_empty_index_and_no_current_chapter()
    {
        var index = new ReaderChapterIndex("doc", 7, []);
        PagedChapterNavigation.ValidateIndex(Document() with { TotalBlocks = 0 }, index);
        Assert.Null(PagedChapterNavigation.AtCursor(index, new("doc", "unused", 0, 0, 7), []));
        AssertError(502, () => PagedChapterNavigation.ValidateIndex(Document(), index));
    }

    [Fact]
    public void The_index_count_is_bounded_before_navigation()
    {
        var chapters = Enumerable.Range(0, PagedChapterNavigation.MaxChapters)
            .Select(ordinal => new ReaderChapterAnchor($"chapter-{ordinal}", $"Chapter {ordinal}", $"block-{ordinal}", ordinal, 0)).ToArray();
        PagedChapterNavigation.ValidateIndex(Document(), new("doc", 7, chapters));
        AssertError(502, () => PagedChapterNavigation.ValidateIndex(Document(), new("doc", 7,
            [.. chapters, new("extra", "Too many", "extra-block", 1024, 0)])));
    }

    [Theory]
    [InlineData("id")]
    [InlineData("title")]
    [InlineData("block")]
    [InlineData("duplicate")]
    [InlineData("order")]
    [InlineData("root-ordinal")]
    [InlineData("root-offset")]
    [InlineData("negative-offset")]
    [InlineData("ordinal-limit")]
    [InlineData("same-ordinal-wrong-block")]
    [InlineData("same-block-wrong-ordinal")]
    public void Invalid_index_payloads_are_explicit_contract_failures(string fault)
    {
        var root = Root;
        var second = Second;
        switch (fault)
        {
            case "id": second = second with { Id = " " }; break;
            case "title": second = second with { Title = " " }; break;
            case "block": second = second with { BlockId = "" }; break;
            case "duplicate": second = second with { Id = root.Id }; break;
            case "order": second = root with { Id = "another" }; break;
            case "root-ordinal": root = root with { BlockOrdinal = 1 }; break;
            case "root-offset": root = root with { CodepointOffset = 1 }; break;
            case "negative-offset": second = second with { CodepointOffset = -1 }; break;
            case "ordinal-limit": second = second with { BlockOrdinal = 2000 }; break;
            case "same-ordinal-wrong-block": second = second with { BlockOrdinal = 0, CodepointOffset = 2 }; break;
            case "same-block-wrong-ordinal": second = second with { BlockId = root.BlockId }; break;
        }
        var error = AssertError(502, () => PagedChapterNavigation.ValidateIndex(Document(), new("doc", 7, [root, second])));
        Assert.Equal("reader_chapter_index_invalid_response", error.ErrorType);
    }

    [Fact]
    public void Index_identity_revision_and_deleted_document_are_fenced()
    {
        AssertError(502, () => PagedChapterNavigation.ValidateIndex(Document(), Index() with { DocumentId = "other" }));
        AssertError(409, () => PagedChapterNavigation.ValidateIndex(Document(), Index() with { ContentRevision = 8 }));
        AssertError(409, () => PagedChapterNavigation.ValidateIndex(Document() with { DeletedAt = DateTimeOffset.UtcNow }, Index()));
    }

    [Theory]
    [InlineData("A😀BCD", 2, 3)]
    [InlineData("A😀BCD", 5, 6)]
    [InlineData("A\ud800B\udc00C", 4, 4)]
    public void Codepoint_anchors_become_canonical_utf16_cursors(string text, int codepointOffset, int expectedOffset)
    {
        var chapter = Second with { CodepointOffset = codepointOffset };
        var cursor = PagedChapterNavigation.ResolveCursor(Document(), chapter, [Block(20, text)]);
        Assert.Equal(new ReaderCursor("doc", "block-20", 20, expectedOffset, 7), cursor);
    }

    [Theory]
    [InlineData("id")]
    [InlineData("document")]
    [InlineData("ordinal")]
    [InlineData("offset")]
    [InlineData("duplicate")]
    public void Destination_source_identity_and_offsets_must_match(string fault)
    {
        var block = Block(20, "A😀B");
        var chapter = Second;
        IReadOnlyList<ReaderBlock> blocks = [block];
        switch (fault)
        {
            case "id": blocks = [block with { Id = "replaced" }]; break;
            case "document": blocks = [block with { DocumentId = "other" }]; break;
            case "ordinal": blocks = [block with { Ordinal = 21 }]; break;
            case "offset": chapter = chapter with { CodepointOffset = 4 }; break;
            case "duplicate": blocks = [block, block]; break;
        }
        AssertError(502, () => PagedChapterNavigation.ResolveCursor(Document(), chapter, blocks));
    }

    [Fact]
    public void Multiple_chapters_in_one_block_use_loaded_text_to_compare_utf16_playback_offsets()
    {
        var middle = Root with { Id = "middle", Title = "Middle", CodepointOffset = 2 };
        var last = Root with { Id = "last", Title = "Last", CodepointOffset = 3 };
        var index = new ReaderChapterIndex("doc", 7, [Root, middle, last]);
        var blocks = new[] { Block(0, "A😀BCD") };
        Assert.Same(Root, PagedChapterNavigation.AtCursor(index, new("doc", "block-0", 0, 1, 7), blocks));
        Assert.Same(middle, PagedChapterNavigation.AtCursor(index, new("doc", "block-0", 0, 3, 7), blocks));
        Assert.Same(last, PagedChapterNavigation.AtCursor(index, new("doc", "block-0", 0, 4, 7), blocks));
        AssertError(502, () => PagedChapterNavigation.AtCursor(index, new("doc", "block-0", 0, 2, 7), blocks));
    }

    [Fact]
    public void Unloaded_playback_blocks_do_not_mix_codepoint_and_utf16_offsets()
    {
        var start = Second with { CodepointOffset = 0 };
        var later = Second with { Id = "later", Title = "Later", CodepointOffset = 4 };
        var index = new ReaderChapterIndex("doc", 7, [Root, start, later]);
        Assert.Same(start, PagedChapterNavigation.AtCursor(index, new("doc", "block-20", 20, 99, 7), []));
        Assert.Same(later, PagedChapterNavigation.AtCursor(index, new("doc", "block-21", 21, 0, 7), []));
        Assert.Same(Root, PagedChapterNavigation.AtCursor(Index(), new("doc", "block-20", 20, 99, 7), []));
    }

    [Fact]
    public void Current_chapter_rejects_a_wrong_cursor_identity_or_revision()
    {
        AssertError(502, () => PagedChapterNavigation.AtCursor(Index(), new("other", "block-20", 20, 0, 7), []));
        AssertError(502, () => PagedChapterNavigation.AtCursor(Index(), new("doc", "replacement", 20, 0, 7), []));
        AssertError(409, () => PagedChapterNavigation.AtCursor(Index(), new("doc", "block-20", 20, 0, 8), []));
    }

    [Fact]
    public async Task Navigation_stages_one_exact_ordinal_page_between_two_fresh_metadata_fences()
    {
        var (client, fake) = Client();
        var visible = new ReadingWindowPager(client);
        var oldPage = visible.UsePage(new([Block(0, "Previously displayed")], 0, 0));
        // A pre-existing metadata-only row change is acceptable; the source
        // revision and both fresh fences must still agree.
        fake.Current = Document() with { RowVersion = 9 };
        var destination = await PagedChapterNavigation.StageNavigationAsync(client, Document(), Index(), Second);
        Assert.Equal(["metadata", "blocks", "metadata"], fake.Calls);
        Assert.Equal((19, 64), Assert.Single(fake.BlockRequests));
        Assert.Equal(20, destination.Page.StartOrdinal);
        Assert.Equal(new ReaderCursor("doc", "block-20", 20, 3, 7), destination.Cursor);
        Assert.Same(oldPage, visible.Current);
    }

    [Fact]
    public async Task Navigation_rejects_an_anchor_not_in_the_validated_index_without_reads()
    {
        var (client, fake) = Client();
        await AssertErrorAsync(502, () => PagedChapterNavigation.StageNavigationAsync(client, Document(), Index(), Second with { CodepointOffset = 3 }));
        Assert.Empty(fake.Calls);
    }

    [Theory]
    [InlineData("revision")]
    [InlineData("deleted")]
    [InlineData("identity")]
    [InlineData("folder")]
    public async Task A_changed_initial_fence_stops_before_fetching_blocks(string fault)
    {
        var (client, fake) = Client();
        fake.Current = Changed(fake.Current, fault);
        await AssertErrorAsync(fault == "identity" ? 502 : 409,
            () => PagedChapterNavigation.StageNavigationAsync(client, Document(), Index(), Second));
        Assert.Equal(["metadata"], fake.Calls);
    }

    [Theory]
    [InlineData("revision")]
    [InlineData("row-version")]
    [InlineData("deleted")]
    [InlineData("folder")]
    public async Task A_delayed_source_page_cannot_publish_after_a_metadata_change(string fault)
    {
        var (client, fake) = Client();
        var response = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        fake.PendingPage = response.Task;
        var staged = PagedChapterNavigation.StageNavigationAsync(client, Document(), Index(), Second);
        fake.Current = Changed(fake.Current, fault);
        response.SetResult(new([Block(20, "A😀BCD")], 20));
        await AssertErrorAsync(409, () => staged);
        Assert.Equal(["metadata", "blocks", "metadata"], fake.Calls);
        Assert.Single(fake.BlockRequests);
    }

    [Theory]
    [InlineData("before")]
    [InlineData("page")]
    [InlineData("after")]
    public async Task Cancellation_after_an_ignored_response_stops_at_each_await_boundary(string stage)
    {
        var (client, fake) = Client();
        var metadata = new TaskCompletionSource<ReaderDocument>(TaskCreationOptions.RunContinuationsAsynchronously);
        var page = new TaskCompletionSource<BlockPage>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (stage == "page") fake.PendingPage = page.Task;
        else fake.MetadataReply = read => read == (stage == "before" ? 1 : 2) ? metadata.Task : Task.FromResult(fake.Current);
        using var cancelled = new CancellationTokenSource();
        var pending = PagedChapterNavigation.StageNavigationAsync(client, Document(), Index(), Second, cancelled.Token);
        cancelled.Cancel();
        metadata.TrySetResult(fake.Current);
        page.TrySetResult(new([Block(20, "A😀BCD")], 20));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(stage == "before" ? 1 : stage == "page" ? 2 : 3, fake.Calls.Count);
    }

    [Fact]
    public async Task Oversized_blocks_preserve_the_typed_413_without_a_retry_or_source_download()
    {
        var (client, fake) = Client();
        var oversized = new ReaderApiException("reader_block_too_large", "Split this source block before importing it again.", 413);
        fake.PageFailure = oversized;
        var error = await AssertErrorAsync(413, () => PagedChapterNavigation.StageNavigationAsync(client, Document(), Index(), Second));
        Assert.Same(oversized, error);
        Assert.Equal(["metadata", "blocks"], fake.Calls);
        Assert.Single(fake.BlockRequests);
    }

    private static readonly ReaderChapterAnchor Root = new("root", "First", "block-0", 0, 0);
    private static readonly ReaderChapterAnchor Second = new("second", "Second", "block-20", 20, 2);
    private static ReaderChapterIndex Index() => new("doc", 7, [Root, Second]);
    private static ReaderDocument Document() => new("doc", "Synthetic", "html", null, null, null, null, "inbox",
        DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, null, 7, 8, 1, 2000, 2_000_000,
        JsonSerializer.SerializeToElement(new { }));
    private static ReaderBlock Block(int ordinal, string text) => new($"block-{ordinal}", "doc", null, ordinal,
        "paragraph", text, text.EnumerateRunes().Count(), "hash", 1, JsonSerializer.SerializeToElement(new { }));
    private static ReaderDocument Changed(ReaderDocument document, string fault) => fault switch
    {
        "revision" => document with { ContentRevision = document.ContentRevision + 1 },
        "row-version" => document with { RowVersion = document.RowVersion + 1 },
        "identity" => document with { Id = "other" },
        "folder" => document with { FolderId = "closed-folder" },
        "deleted" => document with { DeletedAt = DateTimeOffset.UtcNow },
        _ => throw new InvalidOperationException(fault),
    };
    private static ReaderApiException AssertError(int status, Action action)
    {
        var error = Assert.Throws<ReaderApiException>(action);
        Assert.Equal(status, error.StatusCode);
        return error;
    }
    private static async Task<ReaderApiException> AssertErrorAsync(int status, Func<Task> action)
    {
        var error = await Assert.ThrowsAsync<ReaderApiException>(action);
        Assert.Equal(status, error.StatusCode);
        return error;
    }
    private static (IReaderServiceClient, ChapterClient) Client()
    {
        var client = DispatchProxy.Create<IReaderServiceClient, ChapterClient>();
        return (client, (ChapterClient)client);
    }

    public class ChapterClient : DispatchProxy
    {
        public ReaderDocument Current = Document();
        public List<string> Calls { get; } = [];
        public List<(int AfterOrdinal, int Limit)> BlockRequests { get; } = [];
        public Task<BlockPage>? PendingPage;
        public Exception? PageFailure;
        public Func<int, Task<ReaderDocument>>? MetadataReply;
        private int _metadataReads;
        protected override object? Invoke(MethodInfo? method, object?[]? args)
        {
            switch (method?.Name)
            {
                case nameof(IReaderServiceClient.GetDocumentFreshAsync):
                    Calls.Add("metadata");
                    Assert.Equal("doc", args![0]);
                    return MetadataReply?.Invoke(++_metadataReads) ?? Task.FromResult(Current);
                case nameof(IReaderServiceClient.GetBlocksAsync):
                    Calls.Add("blocks");
                    Assert.Equal("doc", args![0]);
                    BlockRequests.Add(((int)args[1]!, (int)args[2]!));
                    return PageFailure is not null ? Task.FromException<BlockPage>(PageFailure) :
                        PendingPage ?? Task.FromResult(new BlockPage([Block(20, "A😀BCD")], 20));
                default: throw new InvalidOperationException($"Unexpected API in chapter navigation: {method?.Name}");
            }
        }
    }
}
