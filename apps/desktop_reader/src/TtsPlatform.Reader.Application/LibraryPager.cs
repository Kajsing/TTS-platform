using System.Collections.ObjectModel;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed class LibraryPager(IReaderServiceClient client, int pageSize = 50)
{
    private string? _nextCursor;
    private string? _query;
    private string? _state;

    public ObservableCollection<ReaderDocument> Documents { get; } = [];
    public bool HasMore => _nextCursor is not null;
    public bool IsLoading { get; private set; }
    public string? LastError { get; private set; }

    public bool ReplaceDocument(ReaderDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        for (var index = 0; index < Documents.Count; index++)
        {
            if (!string.Equals(Documents[index].Id, document.Id, StringComparison.Ordinal))
            {
                continue;
            }
            Documents[index] = document;
            return true;
        }
        return false;
    }

    public async Task RefreshAsync(
        string? query = null,
        string? state = null,
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
            var page = await client.GetDocumentsAsync(pageSize, null, query, state, cancellationToken);
            Documents.Clear();
            foreach (var document in page.Documents)
            {
                Documents.Add(document);
            }

            _query = query;
            _state = state;
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
            var page = await client.GetDocumentsAsync(pageSize, _nextCursor, _query, _state, cancellationToken);
            foreach (var document in page.Documents)
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
