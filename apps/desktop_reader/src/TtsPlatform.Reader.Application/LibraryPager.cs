using System.Collections.ObjectModel;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed class LibraryPager(IReaderServiceClient client, int pageSize = 50)
{
    private string? _nextCursor;
    private string? _query;
    private string? _state;
    private string? _folderId;
    private HashSet<string> _closedFolderIds = new(StringComparer.Ordinal);

    public ObservableCollection<ReaderDocument> Documents { get; } = [];
    public bool HasMore => _nextCursor is not null;
    public bool IsLoading { get; private set; }
    public string? LastError { get; private set; }

    public void SetClosedFolders(IEnumerable<string> folderIds)
    {
        _closedFolderIds = new HashSet<string>(folderIds, StringComparer.Ordinal);
        for (var index = Documents.Count - 1; index >= 0; index--)
        {
            if (!IsVisible(Documents[index]))
            {
                Documents.RemoveAt(index);
            }
        }
    }

    private bool IsVisible(ReaderDocument document) =>
        document.FolderId is null || !_closedFolderIds.Contains(document.FolderId);

    private async Task<DocumentPage> ReadVisiblePageAsync(
        string? cursor, string? query, string? state, string? folderId,
        CancellationToken cancellationToken)
    {
        // Skip hidden-only pages without an unbounded burst of service requests.
        for (var attempt = 0; ; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var page = await client.GetDocumentsByFolderAsync(
                pageSize, cursor, query, state, folderId, cancellationToken);
            var visible = page.Documents.Where(IsVisible).ToArray();
            if (visible.Length > 0 || page.NextCursor is null || attempt == 4)
            {
                return new DocumentPage(visible, page.NextCursor);
            }
            if (page.NextCursor == cursor)
            {
                throw new ReaderApiException("reader_invalid_page", "The library cursor did not advance.", 502);
            }
            cursor = page.NextCursor;
        }
    }

    public bool ReplaceDocument(ReaderDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        for (var index = 0; index < Documents.Count; index++)
        {
            if (!string.Equals(Documents[index].Id, document.Id, StringComparison.Ordinal))
            {
                continue;
            }
            if (IsVisible(document))
            {
                Documents[index] = document;
            }
            else
            {
                Documents.RemoveAt(index);
            }
            return true;
        }
        return false;
    }

    public async Task RefreshAsync(
        string? query = null,
        string? state = null,
        string? folderId = null,
        CancellationToken cancellationToken = default)
    {
        if (IsLoading)
        {
            return;
        }

        IsLoading = true;
        LastError = null;
        try
        {
            var page = await ReadVisiblePageAsync(
                null,
                query,
                state,
                folderId,
                cancellationToken);
            Documents.Clear();
            foreach (var document in page.Documents.Where(IsVisible))
            {
                Documents.Add(document);
            }

            _query = query;
            _state = state;
            _folderId = folderId;
            _nextCursor = page.NextCursor;
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            LastError = exception.Message;
            throw;
        }
        finally
        {
            IsLoading = false;
        }
    }

    public async Task LoadMoreAsync(CancellationToken cancellationToken = default)
    {
        if (IsLoading || _nextCursor is null)
        {
            return;
        }

        IsLoading = true;
        LastError = null;
        try
        {
            var page = await ReadVisiblePageAsync(
                _nextCursor,
                _query,
                _state,
                _folderId,
                cancellationToken);
            foreach (var document in page.Documents.Where(IsVisible))
            {
                Documents.Add(document);
            }

            _nextCursor = page.NextCursor;
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            LastError = exception.Message;
            throw;
        }
        finally
        {
            IsLoading = false;
        }
    }
}
