using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class RemoteArticleSearchTests
{
    [Fact]
    public async Task Find_pages_only_positions_and_preserves_source_mapping_without_fetching_blocks()
    {
        var client = new SearchClient();
        var result = await RemoteArticleSearch.FindAsync(client, Document(), "needle", new(WholeWord: true));
        Assert.Equal(3, result.Hits.Count);
        Assert.Equal([0, 2], client.ResultOffsets);
        Assert.Equal("needle", client.Query!.Query);
        Assert.True(client.Query.WholeWord);
        Assert.Equal(7, client.Query.ExpectedContentRevision);
        Assert.Equal(20, result.Result.Matches[1].Start);
        Assert.Equal(1999, RemoteArticleSearch.Locate(result.Hits[2]).StartCursor.BlockOrdinal);
        Assert.Equal(0, client.BlockReads);
    }

    [Fact]
    public async Task Highlight_counts_window_and_next_do_not_materialize_all_matches_or_source()
    {
        var client = new SearchClient();
        var configuration = new ReaderHighlighterConfiguration("global", 4, DateTimeOffset.UnixEpoch,
            [new("term", "needle", "needle", true, "#ABCDEF", 0, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch)]);
        var summary = await RemoteArticleSearch.HighlightsAsync(client, Document(), configuration);
        Assert.Equal(250_000, summary.TotalMatches);
        Assert.Equal(250_000, summary.Counts["term"]);
        var blocks = new[] { Block("first", 0, "A😀 needle"), Block("second", 1, "needle B") };
        var window = await RemoteArticleSearch.WindowAsync(client, Document(), summary, blocks);
        Assert.Single(window.Matches);
        Assert.True(window.Truncated);
        Assert.Equal(new ReaderSearchWindowRequest(0, 1), client.WindowRequest);
        var map = RemoteArticleSearch.MapHighlights(blocks, window.Matches, configuration.Terms);
        Assert.Equal(4, Assert.Single(map[0]).Start);
        Assert.Equal(6, Assert.Single(map[0]).Length);
        Assert.Empty(map[1]);
        var next = await RemoteArticleSearch.NextAsync(client, Document(), summary, "term", 12);
        Assert.Equal(1999, next!.StartCursor.BlockOrdinal);
        Assert.Equal(new ReaderSearchNextRequest("term", 12), client.NextRequest);
        Assert.Empty(client.ResultOffsets);
        Assert.Equal(0, client.BlockReads);
    }

    [Fact]
    public async Task Find_navigation_revalidates_session_hit_before_using_retained_positions()
    {
        var client = new SearchClient();
        var find = await RemoteArticleSearch.FindAsync(client, Document(), "needle", new());
        var hit = await RemoteArticleSearch.FindHitAsync(client, Document(), find, 2);
        Assert.Equal(find.Hits[2], hit);
        Assert.Equal(1, client.LastPageLimit);
        client.PageError = new ReaderApiException("reader_search_expired", "Run Find again.", 410);
        var error = await Assert.ThrowsAsync<ReaderApiException>(() => RemoteArticleSearch.FindHitAsync(client, Document(), find, 2));
        Assert.Equal("reader_search_expired", error.ErrorType);
    }

    [Fact]
    public void Remote_cross_block_highlights_are_clipped_to_visible_source_only()
    {
        var terms = new[] { new ReaderHighlighterTerm("term", "phrase", "phrase", true, "#ABCDEF", 0,
            DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch) };
        var hit = new ReaderSearchHit(0, 10, 30, "term",
            new("doc", "before", 0, 10, 7), new("doc", "last", 2, 3, 7));
        var middle = Block("middle", 1, "Visible😀");
        var last = Block("last", 2, "ending");
        var map = RemoteArticleSearch.MapHighlights([middle, last], [hit], terms);
        Assert.Equal(new RemoteBlockHighlight(0, middle.Text.Length, "#ABCDEF", "term"), Assert.Single(map[1]));
        Assert.Equal(new RemoteBlockHighlight(0, 3, "#ABCDEF", "term"), Assert.Single(map[2]));
        Assert.Equal(2, map.Count);
    }

    [Theory]
    [InlineData("pattern_too_long", ArticleFindFailure.PatternTooLong)]
    [InlineData("document_too_large", ArticleFindFailure.DocumentTooLarge)]
    [InlineData("invalid_regex", ArticleFindFailure.InvalidRegex)]
    [InlineData("regex_timed_out", ArticleFindFailure.RegexTimedOut)]
    [InlineData("unsupported_regex", ArticleFindFailure.UnsupportedRegex)]
    [InlineData("search_timed_out", ArticleFindFailure.SearchTimedOut)]
    public async Task Search_failures_are_explicit_without_a_source_download(string failure, ArticleFindFailure expected)
    {
        var client = new SearchClient { Failure = failure };
        var result = await RemoteArticleSearch.FindAsync(client, Document(), "pattern", new(UseRegex: true));
        Assert.Equal(expected, result.Result.Failure);
        Assert.Empty(client.ResultOffsets);
        Assert.Equal(0, client.BlockReads);
    }

    [Fact]
    public async Task Older_service_has_actionable_failure_and_no_download_fallback()
    {
        var client = new SearchClient { CreateError = new ReaderApiException("not_found", "Missing", 404) };
        var error = await Assert.ThrowsAsync<ReaderApiException>(() => RemoteArticleSearch.FindAsync(client, Document(), "needle", new()));
        Assert.Equal("reader_search_unavailable", error.ErrorType);
        Assert.Contains("Update", error.Message, StringComparison.Ordinal);
        Assert.Equal(0, client.BlockReads);
    }

    [Fact]
    public async Task Cancellation_during_ignored_create_response_stops_before_result_fetch()
    {
        var response = new TaskCompletionSource<ReaderSearchSummary>(TaskCreationOptions.RunContinuationsAsynchronously);
        var client = new SearchClient { PendingSummary = response.Task };
        using var cancelled = new CancellationTokenSource();
        var pending = RemoteArticleSearch.FindAsync(client, Document(), "needle", new(), cancelled.Token);
        cancelled.Cancel();
        response.SetResult(Summary());
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Empty(client.ResultOffsets);
    }

    [Fact]
    public async Task Rate_limit_wait_is_cancellable_and_does_not_repeat_an_unknown_failure()
    {
        var client = new SearchClient
        {
            CreateError = new ReaderApiException("rate_limited", "Wait", 429,
            details: new Dictionary<string, object?> { ["retry_after_seconds"] = 60 })
        };
        using var cancelled = new CancellationTokenSource();
        var pending = RemoteArticleSearch.FindAsync(client, Document(), "needle", new(), cancelled.Token);
        cancelled.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(1, client.CreateCalls);
        client.CreateError = new ReaderServiceUnavailableException("Lost response");
        await Assert.ThrowsAsync<ReaderServiceUnavailableException>(() => RemoteArticleSearch.FindAsync(client, Document(), "needle", new()));
        Assert.Equal(2, client.CreateCalls);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Invalid_revision_or_nonadvancing_results_fail_closed(bool wrongRevision)
    {
        var client = new SearchClient { WrongRevision = wrongRevision, BadContinuation = !wrongRevision };
        var error = await Assert.ThrowsAsync<ReaderApiException>(() => RemoteArticleSearch.FindAsync(client, Document(), "needle", new()));
        Assert.Equal("reader_search_invalid_response", error.ErrorType);
    }

    [Fact]
    public async Task A_missing_source_cursor_is_an_explicit_contract_error()
    {
        var client = new SearchClient { MissingCursor = true };
        var error = await Assert.ThrowsAsync<ReaderApiException>(() => RemoteArticleSearch.FindAsync(client, Document(), "needle", new()));
        Assert.Equal("reader_search_invalid_response", error.ErrorType);
        Assert.Equal(0, client.BlockReads);
    }

    private static ReaderDocument Document() => new("doc", "Synthetic", "html", null, null, null, null, "inbox",
        DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch, null, 7, 8, 1, 2000, 2_000_000,
        JsonDocument.Parse("{}").RootElement.Clone());

    private static ReaderBlock Block(string id, int ordinal, string text) => new(id, "doc", null, ordinal,
        "paragraph", text, text.Length, "hash", 1, JsonDocument.Parse("{}").RootElement.Clone());

    private static ReaderSearchSummary Summary(string kind = "find", int count = 3, string? failure = null) =>
        new("session", "doc", 7, kind, failure is null ? count : 0,
            new Dictionary<string, int> { ["term"] = count }, false, failure, "regex-v0", 300);

    private static ReaderSearchHit Hit(int index, int start, int ordinal = 0, string? term = null) => new(index, start, 6, term,
        new ReaderCursor("doc", ordinal == 0 ? "first" : $"block-{ordinal}", ordinal, ordinal == 0 ? start : 0, 7),
        new ReaderCursor("doc", ordinal == 0 ? "first" : $"block-{ordinal}", ordinal, ordinal == 0 ? start + 6 : 6, 7));

    private sealed class SearchClient : IReaderServiceClient
    {
        public int BlockReads, CreateCalls, LastPageLimit;
        public bool WrongRevision, BadContinuation, MissingCursor;
        public string? Failure;
        public Exception? CreateError, PageError;
        public Task<ReaderSearchSummary>? PendingSummary;
        public ReaderSearchRequest? Query;
        public ReaderSearchWindowRequest? WindowRequest;
        public ReaderSearchNextRequest? NextRequest;
        public List<int> ResultOffsets { get; } = [];
        private readonly ReaderSearchHit[] _hits = [Hit(0, 4), Hit(1, 20), Hit(2, 1_999_000, 1999)];
        public Task<ReaderSearchSummary> CreateSearchAsync(string documentId, ReaderSearchRequest request, CancellationToken cancellationToken = default)
        {
            CreateCalls++;
            Query = request;
            return CreateError is not null ? Task.FromException<ReaderSearchSummary>(CreateError) : PendingSummary ?? Task.FromResult(Summary(failure: Failure));
        }
        public Task<ReaderSearchSummary> CreateHighlightSearchAsync(string documentId, ReaderHighlightSearchRequest request, CancellationToken cancellationToken = default) =>
            Task.FromResult(Summary("highlighter", 250_000));
        public Task<ReaderSearchPage> GetSearchResultsAsync(string documentId, string searchId, ReaderSearchPageRequest request, CancellationToken cancellationToken = default)
        {
            ResultOffsets.Add(request.Offset);
            LastPageLimit = request.Limit;
            if (PageError is not null) return Task.FromException<ReaderSearchPage>(PageError);
            var hits = _hits.Skip(request.Offset).Take(Math.Min(request.Limit, 2)).ToArray();
            if (MissingCursor && hits.Length > 0) hits[0] = hits[0] with { StartCursor = null! };
            return Task.FromResult(new ReaderSearchPage("doc", WrongRevision ? 8 : 7, hits,
                BadContinuation ? 0 : request.Offset + hits.Length < 3 ? request.Offset + hits.Length : null, 3, false));
        }
        public Task<ReaderSearchPage> GetSearchWindowAsync(string documentId, string searchId, ReaderSearchWindowRequest request, CancellationToken cancellationToken = default)
        {
            WindowRequest = request;
            return Task.FromResult(new ReaderSearchPage("doc", 7, [Hit(0, 4, term: "term")], null, 250_000, true));
        }
        public Task<ReaderSearchNext> GetNextSearchMatchAsync(string documentId, string searchId, ReaderSearchNextRequest request, CancellationToken cancellationToken = default)
        {
            NextRequest = request;
            return Task.FromResult(new ReaderSearchNext(Hit(13, 1_999_000, 1999, "term")));
        }
        public Task<BlockPage> GetBlocksAsync(string documentId, int afterOrdinal = -1, int limit = 200, CancellationToken cancellationToken = default)
        { BlockReads++; throw new InvalidOperationException("Remote search must not download source."); }
        public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderCapabilities> GetCapabilitiesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderDocument> CreateDocumentAsync(CreateDocumentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DocumentPage> GetDocumentsAsync(int limit = 50, string? cursor = null, string? query = null, string? state = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> ReplaceContentAsync(string documentId, ReplaceContentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> AppendContentAsync(string documentId, AppendContentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> UndoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> RedoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition?> GetPositionAsync(string documentId, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition> SavePositionAsync(string documentId, SavePositionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<byte[]> SynthesizeAsync(EphemeralSynthesisRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}
