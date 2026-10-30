using System.Reflection;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    internal async Task VerifyPagedChaptersAsync()
    {
        if (!_smokeTest || _editor is not null || _playback is not null)
            throw new InvalidOperationException("Paged chapter smoke requires an isolated Reader.");
        var client = DispatchProxy.Create<IReaderServiceClient, PagedChapterSmokeClient>();
        var fake = (PagedChapterSmokeClient)client;
        _client = client;
        _editor = new DocumentEditor(client);
        async Task Idle() => await Dispatcher.InvokeAsync(() => UpdateLayout(), DispatcherPriority.ApplicationIdle);
        static void Require(bool value, string message)
        { if (!value) throw new InvalidOperationException(message); }
        try
        {
            await LoadDocumentAsync(fake.Document);
            await Idle();
            Require(_continuousDocument is null && _readingBlocks.Count == 64 && fake.BlockStarts.SequenceEqual([0]) &&
                _pagedChapterIndex?.Chapters.Count == 3 && ChapterToolbar.Visibility == Visibility.Visible &&
                ChapterComboBox.Items.Count == 3 && !SingleChapterCheckBox.IsEnabled && !AddChapterMenuItem.IsEnabled &&
                !FindCurrentChapterCheckBox.IsEnabled && !PreviousChapterButton.IsEnabled && NextChapterButton.IsEnabled,
                "Large article did not expose its scalar chapter index with one bounded source page.");
            var index = _pagedChapterIndex!;
            var middle = index.Chapters[1];
            var last = index.Chapters[2];
            var intent = new ReaderCursor(fake.Document.Id, fake.Block(0).Id, 0, 3, 1);
            _textCursor = intent;
            var before = fake.BlockStarts.Count;
            await NavigatePagedChapterAsync(middle);
            await Idle();
            Require(fake.BlockStarts.Count == before + 1 && fake.BlockStarts[^1] == 800 &&
                _selectedChapterId == middle.Id && _readingWindow!.Current.StartOrdinal == 800 &&
                _readingBlocks.Count == 64 && _textCursor == intent && fake.Writes == 0,
                "Chapter selection fetched hidden source, lost its selection or changed playback intent.");
            var cursor = PagedChapterNavigation.ResolveCursor(fake.Document, middle, _readingWindow!.Current.Blocks);
            Require(cursor.CharacterOffset == 12, "Emoji codepoints did not resolve to the canonical UTF-16 anchor.");
            // Page starts before a mid-block boundary; actual audible source selects
            // the chapter only after that exact boundary is reached.
            SyncPagedChapterWithCursor(cursor with { CharacterOffset = 0 });
            Require(_selectedChapterId == "root", "A mid-block chapter was selected before its source boundary.");
            SyncPagedChapterWithCursor(cursor);
            Require(_selectedChapterId == middle.Id && _textCursor == intent, "Audible chapter sync changed caret intent.");
            _readingBlocks[0].HighlightStart = 12;
            _readingBlocks[0].HighlightLength = 20;
            Playback_StateChanged(null, new(ReaderPlaybackState.Paused, fake.Document.Id, cursor));
            await Idle();
            Require(_readingBlocks[0].HighlightStart == 12 && _selectedChapterId == middle.Id && _textCursor == intent,
                "Pause lost the source marker or chapter selection.");
            await NavigateChapterAsync(1);
            Require(_selectedChapterId == last.Id && !NextChapterButton.IsEnabled && PreviousChapterButton.IsEnabled &&
                _readingWindow.Current.StartOrdinal == 1600 && _readingBlocks.Count == 1,
                "Next chapter did not open the final bounded page.");
            await NavigateChapterAsync(-1);
            Require(_selectedChapterId == middle.Id, "Previous chapter did not return to its canonical anchor.");

            // An ordinary page request can return Current when superseded inside
            // its pager. It must not repaint/cancel the newer staged chapter.
            fake.GateOrdinal = 864;
            fake.BlockGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            fake.WindowGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            _highlighterConfiguration = new("global", 1, DateTimeOffset.UnixEpoch,
                [new("term", "source", "source", true, "#FFFF00", 0, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch)]);
            _remoteWordSearch = new("words", fake.Document.Id, 1, "highlighter", 0,
                new Dictionary<string, int>(), false, null, "regex-v0", 300);
            var oldPage = ChangeReadingPageAsync(next: true);
            var newerChapter = NavigatePagedChapterAsync(last);
            fake.BlockGate.SetResult(fake.Page(864));
            await oldPage;
            fake.WindowGate.SetResult(new(fake.Document.Id, 1, [], null, 0, false));
            await newerChapter;
            Require(_selectedChapterId == last.Id && _readingWindow.Current.StartOrdinal == 1600,
                "An older page handler cancelled the newer chapter's final anchor/selection.");
            fake.BlockGate = null;
            fake.WindowGate = null;
            fake.GateOrdinal = 800;
            ClearWordHighlights();
            _highlighterConfiguration = null;
            await NavigatePagedChapterAsync(middle);

            var priorPage = _readingWindow.Current;
            fake.BlockFailure = new ReaderApiException("reader_block_too_large", "Synthetic limit.", 413);
            await NavigatePagedChapterAsync(last);
            Require(ReferenceEquals(priorPage, _readingWindow.Current) && _selectedChapterId == middle.Id &&
                FooterText.Text.Contains("Split it"), "An oversized destination replaced the previous page or lacked remediation.");
            fake.BlockFailure = null;
            fake.RevisionAfterPage = true;
            await NavigatePagedChapterAsync(last);
            Require(ReferenceEquals(priorPage, _readingWindow.Current) && FooterText.Text.Contains("changed"),
                "An external revision crossed the staged page fence.");
            fake.RevisionAfterPage = false;
            fake.FreshRevision = 1;
            fake.FreshFolder = "closed-folder";
            await NavigatePagedChapterAsync(last);
            Require(ReferenceEquals(priorPage, _readingWindow.Current), "A move into another folder crossed workspace ownership.");
            fake.FreshFolder = null;

            fake.GateOrdinal = 800;
            fake.BlockGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var abandoned = NavigatePagedChapterAsync(middle);
            var abandonedToken = fake.LastBlockToken;
            await NavigatePagedChapterAsync(last);
            fake.BlockGate.SetResult(fake.Page(800));
            await abandoned;
            Require(abandonedToken.IsCancellationRequested && _selectedChapterId == last.Id &&
                _readingWindow.Current.StartOrdinal == 1600, "A superseded chapter page replaced the latest choice.");
            fake.BlockGate = null;

            // A newer chapter intent also supersedes held Find/term navigation,
            // including transports that ignore the cancellation request.
            var hit = fake.Hit();
            var summary = new ReaderSearchSummary("find", fake.Document.Id, 1, "find", 1,
                new Dictionary<string, int>(), false, null, null, 300);
            _findResult = new([new(0, 1)]);
            _remoteFind = new(summary, [hit], _findResult);
            _findMatchIndex = 0;
            fake.FindGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var oldFind = ShowCurrentFindMatchAsync();
            await NavigatePagedChapterAsync(middle);
            fake.FindGate.SetResult(new(fake.Document.Id, 1, [hit], null, 1, false));
            await oldFind;
            Require(_selectedChapterId == middle.Id && _readingWindow.Current.StartOrdinal == 800 &&
                _remoteFind is not null && _findResult.Matches.Count == 1,
                "An older Find jump replaced a newer chapter or discarded retained search results.");
            fake.FindGate = null;
            _remoteWordSearch = summary with { Kind = "highlighter" };
            _wordHighlightMatchIndex = 17;
            fake.NextGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var oldTerm = JumpToNextWordHighlightAsync("term");
            await NavigatePagedChapterAsync(last);
            fake.NextGate.SetResult(new(hit with { TermId = "term" }));
            await oldTerm;
            Require(_selectedChapterId == last.Id && _readingWindow.Current.StartOrdinal == 1600 && _wordHighlightMatchIndex == 17,
                "An older term jump replaced a newer chapter or changed newer navigation state.");
            fake.NextGate = null;
            _remoteWordSearch = null;

            ChapterComboBox.SelectedItem = middle;
            for (var attempt = 0; attempt < 50 && _pagedChapterNavigationCancellation is not null; attempt++) await Idle();
            Require(_selectedChapterId == middle.Id && _readingWindow.Current.StartOrdinal == 800,
                "The actual chapter selector did not navigate through its async event handler.");

            // A late index reply must not resurrect a cleared/private workspace.
            fake.IndexGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            using var cancellation = new CancellationTokenSource();
            var lateIndex = RefreshPagedChapterCatalogAsync(client, fake.Document, _documentLoadGeneration, cancellation.Token);
            ClearDocumentDisplay();
            fake.IndexGate.SetResult(index);
            await lateIndex;
            Require(_pagedChapterIndex is null && ChapterToolbar.Visibility == Visibility.Collapsed && _readingBlocks.Count == 0,
                "A late chapter index resurrected a cleared workspace.");
            fake.IndexGate = null;
            await LoadDocumentAsync(fake.Document);
            fake.BlockGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var closedJump = NavigatePagedChapterAsync(middle);
            ClearDocumentDisplay();
            fake.BlockGate.SetResult(fake.Page(800));
            await closedJump;
            Require(_editor.Document is null && _readingBlocks.Count == 0 && fake.Writes == 0,
                "An abandoned chapter jump changed a closed document or persisted a position.");
        }
        finally
        {
            ClearDocumentDisplay();
            _editor = null;
            _readingWindow = null;
            _client = null;
            _textCursor = null;
        }
    }
}

public class PagedChapterSmokeClient : DispatchProxy
{
    private static readonly JsonElement Metadata = JsonSerializer.SerializeToElement(new { });
    public ReaderDocument Document { get; } = new("paged-chapter", "Synthetic paged chapters", "clipboard",
        null, null, null, null, "inbox", DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch,
        DateTimeOffset.UnixEpoch, null, 1, 1, 1, 1601, 3_000_000, Metadata);
    public List<int> BlockStarts { get; } = [];
    public int Writes { get; private set; }
    public int FreshRevision = 1;
    public string? FreshFolder;
    public bool RevisionAfterPage;
    public int GateOrdinal = 800;
    public CancellationToken LastBlockToken;
    public TaskCompletionSource<BlockPage>? BlockGate;
    public TaskCompletionSource<ReaderChapterIndex>? IndexGate;
    public TaskCompletionSource<ReaderSearchPage>? FindGate;
    public TaskCompletionSource<ReaderSearchNext>? NextGate;
    public TaskCompletionSource<ReaderSearchPage>? WindowGate;
    public ReaderApiException? BlockFailure;
    public ReaderBlock Block(int ordinal)
    {
        var text = "😀 prefix 😀 marker " + string.Concat(Enumerable.Repeat("A source-faithful navigation sentence. ", 40));
        return new($"paged-{ordinal}", Document.Id, null, ordinal, "paragraph", text, text.Length - 2, "hash", 1, Metadata);
    }
    public BlockPage Page(int ordinal) => new(Enumerable.Range(ordinal, Math.Min(64, 1601 - ordinal)).Select(Block).ToArray(),
        ordinal + 64 < 1601 ? ordinal + 63 : null);
    private ReaderChapterIndex Index() => new(Document.Id, 1,
        [new("root", "Arrival", "paged-0", 0, 0), new("middle", "Across the boundary", "paged-800", 800, 10),
            new("last", "Home again", "paged-1600", 1600, 10)]);
    public ReaderSearchHit Hit() => new(0, 0, 1, null,
        new(Document.Id, "paged-0", 0, 0, 1), new(Document.Id, "paged-0", 0, 1, 1));
    protected override object? Invoke(MethodInfo? method, object?[]? args)
    {
        switch (method?.Name)
        {
            case nameof(IReaderServiceClient.GetSearchResultsAsync):
                return FindGate!.Task;
            case nameof(IReaderServiceClient.GetSearchWindowAsync):
                return WindowGate!.Task;
            case nameof(IReaderServiceClient.GetNextSearchMatchAsync):
                return NextGate!.Task;
            case nameof(IReaderServiceClient.GetDocumentAsync):
            case nameof(IReaderServiceClient.GetDocumentFreshAsync):
                return Task.FromResult(Document with { ContentRevision = FreshRevision, FolderId = FreshFolder });
            case nameof(IReaderServiceClient.GetChapterIndexAsync):
                return IndexGate?.Task ?? Task.FromResult(Index());
            case nameof(IReaderServiceClient.GetBlocksAsync):
                var ordinal = (int)args![1]! + 1;
                LastBlockToken = (CancellationToken)args[3]!;
                BlockStarts.Add(ordinal);
                if (BlockFailure is not null) return Task.FromException<BlockPage>(BlockFailure);
                if (RevisionAfterPage) FreshRevision++;
                return ordinal == GateOrdinal && BlockGate is not null ? BlockGate.Task : Task.FromResult(Page(ordinal));
            default:
                Writes++;
                throw new InvalidOperationException($"Unexpected API during paged navigation: {method?.Name}");
        }
    }
}
