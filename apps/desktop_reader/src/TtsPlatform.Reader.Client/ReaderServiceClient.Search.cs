namespace TtsPlatform.Reader.Client;

public sealed partial class ReaderServiceClient
{
    public Task<ReaderSearchSummary> CreateSearchAsync(string documentId, ReaderSearchRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<ReaderSearchSummary>(HttpMethod.Post, SearchPath(documentId), true, request, cancellationToken);

    public Task<ReaderSearchSummary> CreateHighlightSearchAsync(string documentId, ReaderHighlightSearchRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<ReaderSearchSummary>(HttpMethod.Post, $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/highlights", true, request, cancellationToken);

    public Task<ReaderSearchPage> GetSearchResultsAsync(string documentId, string searchId, ReaderSearchPageRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<ReaderSearchPage>(HttpMethod.Post, SearchPath(documentId, searchId) + "/results", true, request, cancellationToken);

    public Task<ReaderSearchPage> GetSearchWindowAsync(string documentId, string searchId, ReaderSearchWindowRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<ReaderSearchPage>(HttpMethod.Post, SearchPath(documentId, searchId) + "/window", true, request, cancellationToken);

    public Task<ReaderSearchNext> GetNextSearchMatchAsync(string documentId, string searchId, ReaderSearchNextRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<ReaderSearchNext>(HttpMethod.Post, SearchPath(documentId, searchId) + "/next", true, request, cancellationToken);

    private static string SearchPath(string documentId, string? searchId = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/search" +
            (searchId is null ? "" : "/" + Uri.EscapeDataString(searchId));
    }
}
