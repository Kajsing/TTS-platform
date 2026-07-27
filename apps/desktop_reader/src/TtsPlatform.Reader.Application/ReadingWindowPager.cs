using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record ReadingWindowPage(
    IReadOnlyList<ReaderBlock> Blocks,
    int StartOrdinal,
    int? NextAfterOrdinal)
{
    public bool HasPrevious => StartOrdinal > 0;
    public bool HasNext => NextAfterOrdinal is not null;
}

public sealed class ReadingWindowPager(IReaderServiceClient client, int pageSize = 64)
{
    public ReadingWindowPage Current { get; private set; } = new([], 0, null);

    public async Task<ReadingWindowPage> LoadAsync(
        string documentId,
        int startOrdinal,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        if (startOrdinal < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(startOrdinal));
        }

        var page = await client.GetBlocksAsync(
            documentId,
            afterOrdinal: startOrdinal - 1,
            limit: pageSize,
            cancellationToken: cancellationToken).ConfigureAwait(false);
        Current = new ReadingWindowPage(page.Blocks, startOrdinal, page.NextAfterOrdinal);
        return Current;
    }

    public Task<ReadingWindowPage> LoadNextAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        var startOrdinal = Current.NextAfterOrdinal is int after ? after + 1 : Current.StartOrdinal;
        return LoadAsync(documentId, startOrdinal, cancellationToken);
    }

    public Task<ReadingWindowPage> LoadPreviousAsync(
        string documentId,
        CancellationToken cancellationToken = default) =>
        LoadAsync(documentId, Math.Max(0, Current.StartOrdinal - pageSize), cancellationToken);
}
