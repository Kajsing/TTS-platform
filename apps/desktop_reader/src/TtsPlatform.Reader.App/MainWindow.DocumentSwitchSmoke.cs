using System.Reflection;
using System.Text.Json;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    // Isolated --smoke-test only; delayed fake HTTP replies exercise the real
    // WPF selection/load/delete paths without private articles or real audio.
    internal async Task VerifyDocumentSwitchAsync()
    {
        if (!_smokeTest || _playback is not null || _editor is not null)
            throw new InvalidOperationException("Document switch smoke requires an isolated Reader.");
        var client = DispatchProxy.Create<IReaderServiceClient, DocumentSwitchSmokeClient>();
        var fake = (DocumentSwitchSmokeClient)client;
        _client = client;
        _editor = new DocumentEditor(client);
        _library = new LibraryPager(client);
        DocumentsGrid.ItemsSource = _library.Documents;
        async Task Idle() => await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        static void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
        }
        void SelectWithoutLoading(ReaderDocument document)
        {
            _suppressDocumentSelectionLoad = true;
            try { DocumentsGrid.SelectedItem = _library.Documents.Single(item => item.Id == document.Id); }
            finally { _suppressDocumentSelectionLoad = false; }
        }
        try
        {
            await RefreshLibraryAsync();
            var first = fake.Documents[0];
            var second = fake.Documents[1];
            await LoadDocumentAsync(first);
            Require(_editor.Document?.Id == first.Id && DeleteDocumentButton.IsEnabled,
                "Initial article was not actionable after loading.");

            // The library row can be older than an appended/moved article.
            fake.Documents[1] = second with { RowVersion = 2, ContentRevision = 2 };
            await LoadDocumentAsync(second);
            Require(_editor.Document?.RowVersion == 2 && _editor.Document.ContentRevision == 2 &&
                ReferenceEquals(DocumentsGrid.SelectedItem, _editor.Document), "A stale library row caused a revision ghost.");
            await LoadDocumentAsync(first);
            var originalText = EditorTextBox.Text;
            var originalMapping = _continuousDocument;

            // While B is pending, do not delete A. A newer selection wins even
            // when B's blocks arrive later, and its metadata must never publish.
            fake.BlockGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            SelectWithoutLoading(second);
            var pending = LoadDocumentAsync(second);
            Require(_documentReloadInProgress && !DeleteDocumentButton.IsEnabled && !PlayPauseButton.IsEnabled,
                "Pending article load left destructive/playback controls enabled.");
            await DeleteDisplayedDocumentAsync(first);
            Require(fake.DeleteCalls == 0, "Delete targeted the previous editor during a pending selection.");
            var supersededToken = fake.BlockCancellationTokens[^1];
            var newer = LoadDocumentAsync(first);
            Require(supersededToken.IsCancellationRequested,
                "Superseded document transport was not cancelled.");
            fake.BlockGate.SetResult(new BlockPage([fake.Block(second.Id)], null));
            await Task.WhenAll(pending, newer);
            fake.BlockGate = null;
            Require(_editor.Document?.Id == first.Id && EditorTextBox.Text == originalText &&
                ReferenceEquals(DocumentsGrid.SelectedItem, _editor.Document), "An older load overwrote a newer selection.");

            fake.MetadataGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            using (var cancellation = new CancellationTokenSource())
            {
                SelectWithoutLoading(second);
                var cancelledFence = LoadDocumentAsync(second, cancellationToken: cancellation.Token);
                cancellation.Cancel();
                fake.MetadataGate.SetResult(fake.Documents.Single(item => item.Id == second.Id));
                await cancelledFence;
                Require(_editor.Document?.Id == first.Id && EditorTextBox.Text == originalText &&
                    ReferenceEquals(DocumentsGrid.SelectedItem, _editor.Document),
                    "An externally cancelled final metadata fence published a stale editor.");
            }
            fake.MetadataGate = null;

            originalMapping = _continuousDocument;
            fake.FailBlocks = true;
            SelectWithoutLoading(second);
            await LoadDocumentAsync(second);
            Require(_editor.Document?.Id == first.Id && EditorTextBox.Text == originalText &&
                ReferenceEquals(_continuousDocument, originalMapping) && ReferenceEquals(DocumentsGrid.SelectedItem, _editor.Document) &&
                DeleteDocumentButton.IsEnabled && !EditorTextBox.IsReadOnly,
                "Failed load mixed editor state, retained the wrong selection, or left the editor locked.");
            fake.FailBlocks = false;

            // A successful delete must stay removed if refresh fails, and two
            // invocations/another selection must not send a second mutation.
            fake.DeleteGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            fake.FailLibrary = true;
            var deletion = DeleteDisplayedDocumentAsync(first);
            Require(_documentMutationInProgress && !DeleteDocumentButton.IsEnabled && !DocumentsGrid.IsEnabled,
                "Pending delete did not guard the UI.");
            await DeleteDisplayedDocumentAsync(first);
            await LoadDocumentAsync(second);
            Require(fake.DeleteCalls == 1, "Concurrent delete was submitted twice.");
            fake.DeleteGate.SetResult(first with { DeletedAt = DateTimeOffset.UtcNow });
            await deletion;
            await Idle();
            Require(_library.Documents.All(item => item.Id != first.Id) && _editor.Document?.Id != first.Id &&
                !_documentMutationInProgress && DocumentsGrid.IsEnabled,
                "Deleted article survived a failed library refresh or locked the UI.");

            // A stale row for an externally deleted article must also disappear.
            fake.Documents[1] = fake.Documents[1] with { DeletedAt = DateTimeOffset.UtcNow };
            await LoadDocumentAsync(second);
            Require(_editor.Document is null && _library.Documents.Count == 0 &&
                EditorTextBox.Text.Length == 0 && !DeleteDocumentButton.IsEnabled && !PlayPauseButton.IsEnabled,
                "A deleted article remained visible or actionable.");

            // An inactive highlighter must not turn a paged article open into
            // an eager full-book download. Active terms retain full-source counts.
            var large = first with { Id = "large", SourceType = "html", TotalBlocks = 2000, TotalCharacters = 2_002_000 };
            fake.Documents.Add(large);
            _library.Documents.Add(large);
            _findLoader = new ArticleFindDocumentLoader(client);
            foreach (var term in new ReaderHighlighterTerm?[]
            {
                null,
                new("inactive", "needle", "needle", false, "#BFE8D5", 0, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch),
                new("empty", " ", " ", true, "#BFE8D5", 0, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch),
            })
            {
                _highlighterConfiguration = new("global", 1, DateTimeOffset.UnixEpoch, term is null ? [] : [term]);
                var beforeReads = fake.BlockReads;
                await LoadDocumentAsync(large);
                Require(fake.BlockReads - beforeReads == 1 && _readingBlocks.Count == 64 && _continuousDocument is null,
                    "Inactive Word Highlighter downloaded more than the first 64-block page.");
            }
            _highlighterConfiguration = new("global", 2, DateTimeOffset.UnixEpoch,
                [new("active", "needle", "needle", true, "#BFE8D5", 0, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch)]);
            var beforeFullSource = fake.BlockReads;
            await RefreshWordHighlightsAsync();
            Require(fake.BlockReads == beforeFullSource && _wordHighlightDocument is null &&
                _remoteWordSearch?.TotalMatches == 2000 && _wordHighlightResult.Counts.GetValueOrDefault("active") == 2000 &&
                fake.HighlightSearches == 1 && fake.SearchWindowReads == 1 && _readingBlocks.All(block => block.WordHighlights.Count == 1),
                "Active Word Highlighter downloaded source or lost full-article counts/visible overlays.");
            beforeFullSource = fake.BlockReads;
            FindTextBox.Text = "needle";
            await ExecuteFindAsync(++_findGeneration, CancellationToken.None);
            Require(_remoteFind?.Hits.Count == 2000 && _findDocument is null && fake.BlockReads == beforeFullSource &&
                fake.FindSearches == 1 && fake.SearchPageReads == 3 && _readingBlocks[0].FindStart == 991,
                "Paged Find downloaded article source or lost source-mapped navigation.");

            // Old failed replies must not clear a newer page/session, even when
            // the transport ignored cancellation before returning the error.
            fake.SearchWindowGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var oldWindowGate = fake.SearchWindowGate;
            var oldWindow = RefreshRemoteWordWindowAsync();
            fake.SearchWindowGate = null;
            await RefreshRemoteWordWindowAsync();
            FooterText.Text = "New window owns the UI";
            oldWindowGate.SetException(new ReaderApiException("reader_search_expired", "Expired old window.", 410));
            await oldWindow;
            Require(_remoteWordSearch is not null && _readingBlocks.All(block => block.WordHighlights.Count == 1) &&
                FooterText.Text == "New window owns the UI", "A cancelled highlighter failure cleared the newer window.");

            fake.SearchResultGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var oldFindGate = fake.SearchResultGate;
            var oldNavigation = ShowCurrentFindMatchAsync();
            fake.SearchResultGate = null;
            CancelFindWork(clearHighlights: true);
            await ExecuteFindAsync(++_findGeneration, CancellationToken.None);
            var newFind = _remoteFind;
            var newFindStatus = FindStatusText.Text;
            oldFindGate.SetException(new ReaderApiException("reader_search_expired", "Expired old Find.", 410));
            await oldNavigation;
            Require(ReferenceEquals(newFind, _remoteFind) && FindStatusText.Text == newFindStatus && _readingBlocks[0].FindStart == 991,
                "A superseded Find failure cleared a newer search.");

            fake.SearchResultFailure = new ReaderApiException("reader_search_expired", "Run Find again.", 410);
            await ShowCurrentFindMatchAsync();
            await ShowReadingPageAsync(_readingWindow!.Current);
            Require(_remoteFind is null && _findResult.Matches.Count == 0 && _readingBlocks.All(block => block.FindLength == 0),
                "Expired retained Find positions reappeared after rendering a page.");
            fake.SearchResultFailure = null;
            await ExecuteFindAsync(++_findGeneration, CancellationToken.None);

            var correctDisplay = _readingBlocks[0];
            _readingBlocks[0] = new ReaderBlockDisplay(_readingWindow.Current.Blocks[0] with { Id = "replacement-block" });
            ApplyCurrentFindToReadingBlocks();
            Require(_readingBlocks.All(block => block.FindLength == 0), "Find painted a replacement block at the same ordinal.");
            _readingBlocks[0] = correctDisplay;
            ApplyCurrentFindToReadingBlocks();

            fake.SearchWindowGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var oldDestinationGate = fake.SearchWindowGate;
            _findMatchIndex = 1999;
            var oldDestination = ShowCurrentFindMatchAsync();
            fake.SearchWindowGate = null;
            CancelFindWork(clearHighlights: true);
            await ExecuteFindAsync(++_findGeneration, CancellationToken.None);
            oldDestinationGate.SetException(new ReaderApiException("reader_search_expired", "Old destination expired.", 410));
            await oldDestination;
            Require(_readingWindow.Current.StartOrdinal == 0 && ReadingBlocksList.SelectedItem is ReaderBlockDisplay { Ordinal: 0 },
                "A superseded navigation selected a stale destination after awaiting page highlights.");

            beforeFullSource = fake.BlockReads;
            _wordHighlightMatchIndex = 1998;
            await HandleWordHighlightJumpAsync("active");
            Require(fake.SearchNextReads == 1 && fake.BlockReads == beforeFullSource + 1 &&
                _readingWindow!.Current.Blocks.Any(block => block.Ordinal == 1999) && _wordHighlightMatchIndex == 1999,
                "Remote highlighter navigation did not fetch only its destination window.");
            fake.BoundSearchContext = true;
            var beforeBoundedContext = fake.BlockReads;
            var destination = await LoadSearchDestinationAsync(new ReadingWindowPager(client), "large", 1999, CancellationToken.None);
            Require(fake.BlockReads == beforeBoundedContext + 2 && destination.Blocks.Any(block => block.Ordinal == 1999),
                "A byte-bounded context page silently prevented navigation to the search destination.");
            fake.BoundSearchContext = false;
            var priorPage = _readingWindow.Current;
            var priorDisplay = _readingBlocks[0];
            fake.LargeBlockFailure = new ReaderApiException("reader_block_too_large", "Synthetic oversized source block.", 413);
            var beforeOversized = fake.BlockReads;
            await ChangeReadingPageAsync(next: false);
            Require(fake.BlockReads == beforeOversized + 1 && ReferenceEquals(priorPage, _readingWindow.Current) &&
                ReferenceEquals(priorDisplay, _readingBlocks[0]) && FooterText.Text.Contains("Split it into smaller blocks", StringComparison.Ordinal),
                "Oversized page navigation did not retain the current page and show an actionable diagnostic.");
            fake.LargeBlockFailure = null;
        }
        finally
        {
            ClearDocumentDisplay();
            DocumentsGrid.ItemsSource = null;
            _library = null;
            _editor = null;
            _readingWindow = null;
            _client = null;
            _findLoader = null;
            _highlighterConfiguration = null;
        }
    }
}

public class DocumentSwitchSmokeClient : DispatchProxy
{
    private static readonly JsonElement Metadata = JsonSerializer.SerializeToElement(new { });
    public List<ReaderDocument> Documents { get; } = [Document("first"), Document("second")];
    public TaskCompletionSource<BlockPage>? BlockGate { get; set; }
    public TaskCompletionSource<ReaderDocument>? MetadataGate { get; set; }
    public TaskCompletionSource<ReaderDocument>? DeleteGate { get; set; }
    public bool FailBlocks { get; set; }
    public bool FailLibrary { get; set; }
    public int DeleteCalls { get; private set; }
    public TaskCompletionSource<CaptureReceipt>? CaptureGate { get; set; }
    public ReaderApiException? CaptureFailure { get; set; }
    public int CaptureCalls { get; private set; }
    public int BlockReads { get; private set; }
    public List<CancellationToken> BlockCancellationTokens { get; } = [];
    public int FindSearches, HighlightSearches, SearchPageReads, SearchWindowReads, SearchNextReads;
    public bool BoundSearchContext;
    public TaskCompletionSource<ReaderSearchPage>? SearchResultGate, SearchWindowGate;
    public ReaderApiException? SearchResultFailure;
    public ReaderApiException? LargeBlockFailure;
    private static ReaderSearchHit SearchHit(int ordinal, bool highlight) => new(ordinal, ordinal * 1005 + 991, 6,
        highlight ? "active" : null,
        new ReaderCursor("large", $"large-{ordinal}", ordinal, 991, 1),
        new ReaderCursor("large", $"large-{ordinal}", ordinal, 997, 1));
    private static ReaderDocument Document(string id) => new(id, $"Synthetic {id}", "clipboard",
        null, null, null, null, "inbox", DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch,
        DateTimeOffset.UnixEpoch, null, 1, 1, 1, 1, 20, Metadata);
    public ReaderBlock Block(string id) => new($"block-{id}", id, null, 0, "paragraph",
        $"Synthetic text {id}.", 20, "hash", 1, Metadata);

    protected override object? Invoke(MethodInfo? method, object?[]? args)
    {
        var id = args?.FirstOrDefault() as string;
        switch (method?.Name)
        {
            case nameof(IReaderServiceClient.GetChapterIndexAsync):
                return Task.FromResult(new ReaderChapterIndex(id!, 1,
                    [new ReaderChapterAnchor("root", "Chapter 1", id == "large" ? "large-0" : $"block-{id}", 0, 0)]));
            case nameof(IReaderServiceClient.CreateSearchAsync):
                FindSearches++;
                return Task.FromResult(new ReaderSearchSummary("find-session", id!, 1, "find", 2000,
                    new Dictionary<string, int>(), false, null, null, 300));
            case nameof(IReaderServiceClient.CreateHighlightSearchAsync):
                HighlightSearches++;
                return Task.FromResult(new ReaderSearchSummary("highlight-session", id!, 1, "highlighter", 2000,
                    new Dictionary<string, int> { ["active"] = 2000 }, false, null, "regex-v0", 300));
            case nameof(IReaderServiceClient.GetSearchResultsAsync):
                SearchPageReads++;
                if (SearchResultGate is not null) return SearchResultGate.Task;
                if (SearchResultFailure is not null) return Task.FromException<ReaderSearchPage>(SearchResultFailure);
                var resultRequest = (ReaderSearchPageRequest)args![2]!;
                var resultCount = Math.Min(resultRequest.Limit, 2000 - resultRequest.Offset);
                return Task.FromResult(new ReaderSearchPage("large", 1,
                    Enumerable.Range(resultRequest.Offset, resultCount).Select(ordinal => SearchHit(ordinal, false)).ToArray(),
                    resultRequest.Offset + resultCount < 2000 ? resultRequest.Offset + resultCount : null, 2000, false));
            case nameof(IReaderServiceClient.GetSearchWindowAsync):
                SearchWindowReads++;
                if (SearchWindowGate is not null) return SearchWindowGate.Task;
                var windowRequest = (ReaderSearchWindowRequest)args![2]!;
                return Task.FromResult(new ReaderSearchPage("large", 1,
                    Enumerable.Range(windowRequest.StartOrdinal, windowRequest.EndOrdinal - windowRequest.StartOrdinal + 1)
                        .Select(ordinal => SearchHit(ordinal, true)).ToArray(), null, 2000, false));
            case nameof(IReaderServiceClient.GetNextSearchMatchAsync):
                SearchNextReads++;
                var nextRequest = (ReaderSearchNextRequest)args![2]!;
                return Task.FromResult(new ReaderSearchNext(SearchHit((nextRequest.AfterIndex + 1) % 2000, true)));
            case nameof(IReaderServiceClient.DeliverCaptureAsync):
                CaptureCalls++;
                if (CaptureFailure is not null) return Task.FromException<CaptureReceipt>(CaptureFailure);
                return CaptureGate?.Task ?? Task.FromResult(new CaptureReceipt(id!, "first", "delivered"));
            case nameof(IReaderServiceClient.GetDocumentFreshAsync):
                if (id == "second" && MetadataGate is not null) return MetadataGate.Task;
                return Task.FromResult(Documents.Single(item => item.Id == id));
            case nameof(IReaderServiceClient.GetDocumentAsync):
                return Task.FromResult(Documents.Single(item => item.Id == id));
            case nameof(IReaderServiceClient.GetBlocksAsync):
                BlockReads++;
                var cancellation = (CancellationToken)args![3]!;
                BlockCancellationTokens.Add(cancellation);
                if (FailBlocks) return Task.FromException<BlockPage>(new ReaderApiException("synthetic", "Synthetic load failed.", 503));
                if (id == "large")
                {
                    if (LargeBlockFailure is not null) return Task.FromException<BlockPage>(LargeBlockFailure);
                    var after = (int)args[1]!;
                    var limit = (int)args[2]!;
                    var count = Math.Min(limit, 2000 - after - 1);
                    if (BoundSearchContext && after == 1990) count = Math.Min(count, 3);
                    var blocks = Enumerable.Range(after + 1, count).Select(ordinal =>
                        new ReaderBlock($"large-{ordinal}", "large", null, ordinal, "paragraph", new string('x', 990) + " needle end", 1001, "hash", 1, Metadata)).ToArray();
                    return Task.FromResult(new BlockPage(blocks, after + count < 1999 ? after + count : null));
                }
                return id == "second" && BlockGate is not null ? BlockGate.Task.WaitAsync(cancellation) :
                    Task.FromResult(new BlockPage([Block(id!)], null));
            case nameof(IReaderServiceClient.GetFoldersAsync):
                return Task.FromResult(new ReaderFolderPage([]));
            case nameof(IReaderServiceClient.GetDocumentsByFolderAsync):
                return FailLibrary ? Task.FromException<DocumentPage>(new ReaderApiException("synthetic", "Synthetic refresh failed.", 503)) :
                    Task.FromResult(new DocumentPage(Documents.ToArray(), null));
            case nameof(IReaderServiceClient.DeleteDocumentAsync):
                DeleteCalls++;
                return DeleteGate!.Task;
            default: throw new InvalidOperationException($"Unexpected API in document switch smoke: {method?.Name}");
        }
    }
}
