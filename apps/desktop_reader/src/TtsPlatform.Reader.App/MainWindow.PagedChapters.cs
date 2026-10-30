using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private ReaderChapterIndex? _pagedChapterIndex;
    private CancellationTokenSource? _pagedChapterNavigationCancellation;
    private int _pagedChapterNavigationGeneration;

    private void CancelPagedChapterNavigation()
    {
        ++_pagedChapterNavigationGeneration;
        _pagedChapterNavigationCancellation?.Cancel();
    }

    private async Task RefreshPagedChapterCatalogAsync(IReaderServiceClient client,
        ReaderDocument document, int loadGeneration, CancellationToken cancellationToken)
    {
        if (_continuousDocument is not null) return;
        bool OwnsCatalog() => !_closed && !cancellationToken.IsCancellationRequested &&
            loadGeneration == _documentLoadGeneration && ReferenceEquals(client, _client) &&
            _editor?.Document?.Id == document.Id && _editor.Document.ContentRevision == document.ContentRevision &&
            IsFolderOpen(document.FolderId) && _continuousDocument is null;
        try
        {
            var index = await client.GetChapterIndexAsync(document.Id, document.ContentRevision, cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            PagedChapterNavigation.ValidateIndex(document, index);
            if (!OwnsCatalog()) return;
            _pagedChapterIndex = index;
            RebuildChapterCatalog();
            SyncPagedChapterWithPage();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (Exception error) when (error is ReaderApiException or ReaderServiceUnavailableException or
            ReaderTokenUnavailableException or NotSupportedException)
        {
            if (OwnsCatalog()) FooterText.Text = $"Chapter navigation unavailable: {error.Message}";
        }
    }

    private void RestoreChapterSelection()
    {
        _updatingChapters = true;
        ChapterComboBox.SelectedItem = _continuousDocument is not null
            ? _chapters.FirstOrDefault(item => item.Id == _selectedChapterId)
            : _pagedChapterIndex?.Chapters.FirstOrDefault(item => item.Id == _selectedChapterId);
        _updatingChapters = false;
    }

    private void SyncPagedChapterWithPage()
    {
        if (_continuousDocument is null && _editor?.Document is { } document &&
            _readingWindow?.Current.Blocks.FirstOrDefault() is { } block)
            SyncPagedChapterWithCursor(new(document.Id, block.Id, block.Ordinal, 0, document.ContentRevision));
    }

    private void SyncPagedChapterWithCursor(ReaderCursor cursor)
    {
        if (_continuousDocument is not null || _pagedChapterIndex is not { } index ||
            _readingWindow is not { } pager) return;
        try
        {
            var chapter = PagedChapterNavigation.AtCursor(index, cursor, pager.Current.Blocks);
            if (chapter is null) return;
            _selectedChapterId = chapter.Id;
            RestoreChapterSelection();
            UpdatePlaybackControls();
        }
        catch (ReaderApiException error)
        {
            _pagedChapterIndex = null;
            RebuildChapterCatalog();
            FooterText.Text = $"Chapter navigation unavailable: {error.Message}";
        }
    }

    private async Task NavigatePagedChapterAsync(ReaderChapterAnchor chapter)
    {
        if (_continuousDocument is not null || _pagedChapterIndex is not { } index ||
            _editor?.Document is not { } document || _readingWindow is not { } pager ||
            !CanChangeChapterView()) return;
        CancelPagedChapterNavigation();
        // A chapter choice owns the viewport over older Find/term jumps, while
        // retained results remain available for the next explicit Find action.
        ++_findGeneration;
        _findCancellation?.Cancel();
        _findCancellation?.Dispose();
        _findCancellation = new CancellationTokenSource();
        if (_findSearchPending) FindStatusText.Text = "Search interrupted by chapter navigation. Press Enter to search again.";
        _findSearchPending = false;
        _remoteWordNavigationCancellation?.Cancel();
        pager.CancelPendingLoads();
        var navigationGeneration = _pagedChapterNavigationGeneration;
        var loadGeneration = _documentLoadGeneration;
        var priorPage = pager.Current;
        var client = GetClient();
        using var cancellation = new CancellationTokenSource();
        _pagedChapterNavigationCancellation = cancellation;
        bool OwnsNavigation() => !_closed && !cancellation.IsCancellationRequested &&
            navigationGeneration == _pagedChapterNavigationGeneration && loadGeneration == _documentLoadGeneration &&
            ReferenceEquals(client, _client) && ReferenceEquals(pager, _readingWindow) &&
            ReferenceEquals(index, _pagedChapterIndex) && _editor?.Document?.Id == document.Id &&
            _editor.Document.ContentRevision == document.ContentRevision && IsFolderOpen(document.FolderId) &&
            !_documentReloadInProgress && !_documentMutationInProgress;
        try
        {
            var destination = await PagedChapterNavigation.StageNavigationAsync(client, document, index, chapter, cancellation.Token);
            cancellation.Token.ThrowIfCancellationRequested();
            if (!OwnsNavigation() || !ReferenceEquals(priorPage, pager.Current)) return;
            var page = pager.UsePage(destination.Page);
            await ShowReadingPageAsync(page, chapterNavigation: true);
            if (!OwnsNavigation() || !ReferenceEquals(page, pager.Current)) return;
            _selectedChapterId = chapter.Id;
            RestoreChapterSelection();
            UpdatePlaybackControls();
            BringChapterAnchorIntoView(destination.Cursor);
            FooterText.Text = $"Chapter: {chapter.Title}. Navigation only; playback position is unchanged.";
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        catch (Exception error) when (error is ReaderApiException or ReaderServiceUnavailableException or
            ReaderTokenUnavailableException or NotSupportedException)
        {
            if (OwnsNavigation() && ReferenceEquals(priorPage, pager.Current))
            {
                RestoreChapterSelection();
                FooterText.Text = $"Chapter navigation: {DescribeReadingNavigationFailure(error)}";
            }
        }
        finally
        {
            if (ReferenceEquals(_pagedChapterNavigationCancellation, cancellation))
                _pagedChapterNavigationCancellation = null;
        }
    }

    private void BringChapterAnchorIntoView(ReaderCursor cursor)
    {
        var block = _readingBlocks.FirstOrDefault(item => item.Id == cursor.BlockId && item.Ordinal == cursor.BlockOrdinal);
        if (block is null) return;
        ReadingBlocksList.SelectedItem = block;
        ReadingBlocksList.ScrollIntoView(block);
        ReadingBlocksList.UpdateLayout();
        if (ReadingBlocksList.ItemContainerGenerator.ContainerFromItem(block) is DependencyObject container &&
            FindVisualChild<SourceHighlightTextBlock>(container) is { } textBlock)
            textBlock.BringSourceOffsetIntoView(cursor.CharacterOffset);
    }
}
