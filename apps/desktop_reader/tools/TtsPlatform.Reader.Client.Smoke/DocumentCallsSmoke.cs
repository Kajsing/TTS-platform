using System.Diagnostics;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

internal static class DocumentCallsSmoke
{
    public static async Task<int> RunAsync(string baseUrl, ITokenProvider tokenProvider)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(110));
        var token = new FixedToken(await tokenProvider.GetTokenAsync(timeout.Token));
        var counter = new CountingHandler();
        using var http = new HttpClient(counter) { Timeout = TimeSpan.FromSeconds(20) };
        var client = new ReaderServiceClient(http, baseUrl, token);
        var duplicateReads = Enumerable.Range(0, 8).Select(_ => client.GetCapabilitiesAsync(timeout.Token)).ToArray();
        Require(counter.Count == 1);
        counter.Release.TrySetResult();
        await Task.WhenAll(duplicateReads);
        Require(counter.Count == 1);
        await client.GetCapabilitiesAsync(timeout.Token);
        Require(counter.Count == 2); // Completed responses are never reused.

        var document = (await client.GetDocumentsAsync(limit: 1, query: "Bounded document fixture",
            cancellationToken: timeout.Token)).Documents.Single();
        Require(document.TotalCharacters > 2_000_000);
        var before = counter.Count;
        var allocatedBefore = GC.GetTotalAllocatedBytes();
        var timer = Stopwatch.StartNew();
        var loaded = await new ReaderDocumentLoader(client).LoadAsync(document, timeout.Token);
        var loadMs = timer.Elapsed.TotalMilliseconds;
        var allocatedBytes = GC.GetTotalAllocatedBytes() - allocatedBefore;
        var loadCalls = counter.Count - before;
        Require(loaded.ContinuousText is null && loaded.Page.Blocks.Count == 64);
        var retainedCharacters = loaded.Page.Blocks.Sum(block => block.Text.Length);
        Require(retainedCharacters < 100_000);
        Require(loadCalls == 2); // One bounded page and one fresh revision fence.
        before = counter.Count;
        var follows = Enumerable.Range(0, 8).Select(_ => loaded.ReadingWindow.FollowPlaybackAsync(
            document.Id, 60, cancellationToken: timeout.Token)).ToArray();
        await Task.WhenAll(follows);
        var followCalls = counter.Count - before;
        Require(followCalls == 1 && loaded.ReadingWindow.Current.Blocks.Count == 64);

        var blocksBeforeSearch = counter.BlockGets;
        var searchTimer = Stopwatch.StartNew();
        var find = await client.CreateSearchAsync(document.Id,
            new ReaderSearchRequest(document.ContentRevision, "paragraph", WholeWord: true, MaxResults: 50), timeout.Token);
        Require(find.Failure is null && find.TotalMatches == 50 && find.Truncated, "capped remote Find summary");
        var findPage = await client.GetSearchResultsAsync(document.Id, find.SearchId,
            new ReaderSearchPageRequest(Limit: 50), timeout.Token);
        Require(findPage.Matches.Count == 50 && findPage.TotalMatches == 50 && findPage.Truncated &&
            findPage.NextOffset is null && findPage.Matches.All(hit => hit.Length == 9), "remote Find result page");
        Require(findPage.Matches[0].StartCursor.BlockOrdinal == 1 &&
            findPage.Matches[0].StartCursor.CharacterOffset == 10, "remote Find source cursor");
        var findMs = searchTimer.Elapsed.TotalMilliseconds;

        var crossBlock = await client.CreateSearchAsync(document.Id,
            new ReaderSearchRequest(document.ContentRevision, @"Short opening\.\r\n\r\nSynthetic", UseRegex: true), timeout.Token);
        Require(crossBlock.Failure is null && crossBlock.TotalMatches == 1 && !crossBlock.Truncated &&
            crossBlock.RegexDialect == "regex-v0", "cross-block regex summary and provider");
        var crossPage = await client.GetSearchResultsAsync(document.Id, crossBlock.SearchId,
            new ReaderSearchPageRequest(Limit: 1), timeout.Token);
        var crossHit = crossPage.Matches.Single();
        Require(crossHit.Start == 0 && crossHit.Length == 27 &&
            crossHit.StartCursor.BlockId == loaded.Page.Blocks[0].Id &&
            crossHit.StartCursor.BlockOrdinal == 0 && crossHit.StartCursor.CharacterOffset == 0 &&
            crossHit.EndCursor.BlockId == loaded.Page.Blocks[1].Id &&
            crossHit.EndCursor.BlockOrdinal == 1 && crossHit.EndCursor.CharacterOffset == 9 &&
            crossHit.EndCursor.ContentRevision == document.ContentRevision, "cross-block regex source cursors");

        var configuration = await client.GetHighlighterAsync(timeout.Token);
        configuration = await client.ReplaceHighlighterAsync(new ReplaceHighlighterRequest(configuration.RowVersion,
            [new SaveHighlighterTerm("paragraph"), new SaveHighlighterTerm("Synthetic paragraph")]), timeout.Token);
        var longTerm = configuration.Terms.Single(term => term.Term == "Synthetic paragraph");
        var shortTerm = configuration.Terms.Single(term => term.Term == "paragraph");
        var highlightTimer = Stopwatch.StartNew();
        var highlights = await client.CreateHighlightSearchAsync(document.Id,
            new ReaderHighlightSearchRequest(document.ContentRevision, configuration.RowVersion), timeout.Token);
        var highlightMs = highlightTimer.Elapsed.TotalMilliseconds;
        Require(highlights.Failure is null && highlights.TotalMatches == 104_000 && !highlights.Truncated &&
            highlights.RegexDialect == "regex-v0" && highlights.Counts.Count == 2 &&
            highlights.Counts[longTerm.Id] == 104_000 && highlights.Counts[shortTerm.Id] == 0,
            "full highlighter count and longest-term precedence");
        var highlightWindow = await client.GetSearchWindowAsync(document.Id, highlights.SearchId,
            new ReaderSearchWindowRequest(0, 63, Limit: 2000), timeout.Token);
        Require(highlightWindow.Matches.Count == 2000 && highlightWindow.Truncated &&
            highlightWindow.TotalMatches == 104_000 && highlightWindow.NextOffset is null &&
            highlightWindow.Matches.All(hit => hit.TermId == longTerm.Id &&
                hit.StartCursor.BlockOrdinal is >= 0 and <= 63), "bounded visible highlighter window");
        var beforeNext = counter.Count;
        var next = await client.GetNextSearchMatchAsync(document.Id, highlights.SearchId,
            new ReaderSearchNextRequest(longTerm.Id, AfterIndex: 103_998), timeout.Token);
        var nextHit = next.Match ?? throw new InvalidOperationException("Remote highlighter next hit was missing.");
        Require(counter.Count - beforeNext == 1 && nextHit.Index == 103_999 && nextHit.TermId == longTerm.Id &&
            nextHit.StartCursor.BlockOrdinal == 1600 && nextHit.StartCursor.CharacterOffset == 1344,
            "one near-end navigation hit");
        var searchBlockGets = counter.BlockGets - blocksBeforeSearch;
        Require(searchBlockGets == 0, "remote search and highlighting did not fetch article blocks");
        Require(counter.MaxSearchResponseBytes is > 0 and <= 1024 * 1024, "bounded search responses");
        var remoteSearchMs = searchTimer.Elapsed.TotalMilliseconds;

        before = counter.Count;
        var blocksBeforeNavigation = counter.BlockGets;
        var navigationPage = await loaded.ReadingWindow.LoadAsync(document.Id,
            nextHit.StartCursor.BlockOrdinal, timeout.Token);
        var navigationCalls = counter.Count - before;
        var navigationBlockGets = counter.BlockGets - blocksBeforeNavigation;
        Require(navigationCalls == 1 && navigationBlockGets == 1 &&
            navigationPage.Blocks.Count is > 0 and <= 64 &&
            navigationPage.Blocks.Any(block => block.Id == nextHit.StartCursor.BlockId) &&
            navigationPage.Blocks.Sum(block => block.Text.Length) < 100_000,
            "one bounded page for the remote navigation cursor");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            bounded_document_calls = true,
            overlapping_logical_reads = 8,
            overlapping_physical_reads = 1,
            initial_load_calls_with_metadata = loadCalls,
            overlapping_follow_calls = followCalls,
            source_characters = document.TotalCharacters,
            retained_blocks = loaded.Page.Blocks.Count,
            retained_source_characters = retainedCharacters,
            load_ms = Math.Round(loadMs, 2),
            observed_client_allocations_bytes = allocatedBytes,
            remote_paged_search = true,
            remote_cross_block_regex = true,
            remote_highlight_window = true,
            remote_highlight_navigation = true,
            remote_search_block_gets = searchBlockGets,
            search_response_count = counter.SearchResponses,
            max_search_response_bytes = counter.MaxSearchResponseBytes,
            find_hits = find.TotalMatches,
            find_truncated = find.Truncated,
            cross_block_hits = crossBlock.TotalMatches,
            regex_dialect = crossBlock.RegexDialect,
            highlight_long_term_hits = highlights.Counts[longTerm.Id],
            highlight_short_term_hits = highlights.Counts[shortTerm.Id],
            highlight_window_hits = highlightWindow.Matches.Count,
            highlight_window_truncated = highlightWindow.Truncated,
            navigation_hit_index = nextHit.Index,
            navigation_block_page_gets = navigationBlockGets,
            navigation_retained_blocks = navigationPage.Blocks.Count,
            find_ms = Math.Round(findMs, 2),
            highlight_scan_ms = Math.Round(highlightMs, 2),
            remote_search_ms = Math.Round(remoteSearchMs, 2),
        }));
        return 0;
    }

    private static void Require(bool condition, string? stage = null)
    {
        if (!condition) throw new InvalidOperationException($"Bounded document-call acceptance failed: {stage ?? "baseline"}.");
    }

    private sealed class FixedToken(string? value) : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult(value);
    }

    private sealed class CountingHandler : DelegatingHandler
    {
        private int _count;
        private int _blockGets;
        private int _searchResponses;
        private int _maxSearchResponseBytes;
        public int Count => Volatile.Read(ref _count);
        public int BlockGets => Volatile.Read(ref _blockGets);
        public int SearchResponses => Volatile.Read(ref _searchResponses);
        public int MaxSearchResponseBytes => Volatile.Read(ref _maxSearchResponseBytes);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public CountingHandler() : base(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false }) { }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _count);
            var path = request.RequestUri?.AbsolutePath ?? "";
            if (request.Method == HttpMethod.Get && path.EndsWith("/blocks", StringComparison.Ordinal))
                Interlocked.Increment(ref _blockGets);
            await Release.Task.WaitAsync(cancellationToken);
            var response = await base.SendAsync(request, cancellationToken);
            if (path.EndsWith("/search", StringComparison.Ordinal) ||
                path.EndsWith("/highlights", StringComparison.Ordinal) || path.Contains("/search/", StringComparison.Ordinal))
            {
                var size = (await response.Content.ReadAsByteArrayAsync(cancellationToken)).Length;
                Interlocked.Increment(ref _searchResponses);
                int previous;
                do { previous = Volatile.Read(ref _maxSearchResponseBytes); }
                while (size > previous && Interlocked.CompareExchange(ref _maxSearchResponseBytes, size, previous) != previous);
            }
            return response;
        }
    }
}
