using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private async Task ChangeReadingPageAsync(bool next)
    {
        CancelPagedChapterNavigation();
        var chapterGeneration = _pagedChapterNavigationGeneration;
        if (_readingWindow is not { } pager || _editor?.Document is not { } document) return;
        if (_editor.HasUnsavedChanges)
        {
            FooterText.Text = "Save or revert changes before changing page.";
            return;
        }
        var generation = _documentLoadGeneration;
        var page = pager.Current;
        try
        {
            var cancellation = _documentLoadCancellation?.Token ?? CancellationToken.None;
            var destination = next
                ? await pager.LoadNextAsync(document.Id, cancellation)
                : await pager.LoadPreviousAsync(document.Id, cancellation);
            if (!_closed && chapterGeneration == _pagedChapterNavigationGeneration &&
                generation == _documentLoadGeneration && ReferenceEquals(pager, _readingWindow))
                await ShowReadingPageAsync(destination);
        }
        catch (OperationCanceledException) { }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException or ReaderTokenUnavailableException)
        {
            if (!_closed && chapterGeneration == _pagedChapterNavigationGeneration &&
                generation == _documentLoadGeneration && ReferenceEquals(pager, _readingWindow) &&
                ReferenceEquals(page, pager.Current))
                FooterText.Text = $"Reading page unavailable: {DescribeReadingNavigationFailure(exception)}";
        }
    }

    private static string DescribeReadingNavigationFailure(Exception exception) =>
        exception is ReaderApiException { ErrorType: "reader_block_too_large" }
            ? "This source block is too large to display safely. Split it into smaller blocks in the source, then import it again."
            : exception.Message;

    private static async Task<ReadingWindowPage> LoadSearchDestinationAsync(ReadingWindowPager pager,
        string documentId, int ordinal, CancellationToken cancellationToken)
    {
        var page = await pager.LoadAsync(documentId, Math.Max(0, ordinal - 8), cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        if (!page.Blocks.Any(block => block.Ordinal == ordinal))
        {
            // A byte-bounded context page may end before the destination. Starting
            // at the destination either shows it whole or returns explicit 413.
            page = await pager.LoadAsync(documentId, ordinal, cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
        }
        if (!page.Blocks.Any(block => block.Ordinal == ordinal))
            throw new ReaderApiException("reader_search_destination_unavailable", "The search destination changed. Run the search again.", 409);
        return page;
    }

    private async Task RefreshRemoteWordWindowAsync(CancellationToken cancellationToken = default)
    {
        _remoteWordWindowCancellation?.Cancel();
        if (_continuousDocument is not null || _remoteWordSearch is not { } summary ||
            _editor?.Document is not { } document || _readingWindow is not { } pager ||
            _highlighterConfiguration is not { } configuration) return;
        var client = GetClient();
        var page = pager.Current;
        var generation = _wordHighlightGeneration;
        var documentGeneration = _documentLoadGeneration;
        using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _remoteWordWindowCancellation = cancellation;
        bool OwnsWindow() => !_closed && !cancellation.IsCancellationRequested &&
            generation == _wordHighlightGeneration && documentGeneration == _documentLoadGeneration &&
            ReferenceEquals(client, _client) && ReferenceEquals(summary, _remoteWordSearch) &&
            ReferenceEquals(pager, _readingWindow) && ReferenceEquals(page, pager.Current) &&
            ReferenceEquals(_remoteWordWindowCancellation, cancellation) &&
            _editor?.Document?.Id == document.Id && _editor.Document.ContentRevision == document.ContentRevision &&
            _highlighterConfiguration?.RowVersion == configuration.RowVersion;
        try
        {
            var results = await RemoteArticleSearch.WindowAsync(client, document, summary, page.Blocks, cancellation.Token);
            cancellation.Token.ThrowIfCancellationRequested();
            if (!OwnsWindow()) return;
            _wordHighlightsByBlockOrdinal = RemoteArticleSearch.MapHighlights(page.Blocks, results.Matches, configuration.Terms)
                .ToDictionary(item => item.Key, item => (IReadOnlyList<ReaderTextHighlight>)item.Value
                    .Select(range => new ReaderTextHighlight(range.Start, range.Length, range.Color, range.TermId)).ToArray());
            ApplyWordHighlightsToReadingBlocks();
            if (results.Truncated)
                FooterText.Text = "Visible Word Highlighter overlays are limited to 2,000 matches; full-article counts are retained.";
            else if (summary.Truncated)
                FooterText.Text = $"Word Highlighter search is limited to {WordHighlighterEngine.MaxMatches:N0} matches for this article.";
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException or ReaderTokenUnavailableException)
        {
            if (OwnsWindow())
            {
                ClearWordHighlights();
                FooterText.Text = $"Word Highlighter: {exception.Message}";
            }
        }
        finally
        {
            if (ReferenceEquals(_remoteWordWindowCancellation, cancellation)) _remoteWordWindowCancellation = null;
        }
    }
}
