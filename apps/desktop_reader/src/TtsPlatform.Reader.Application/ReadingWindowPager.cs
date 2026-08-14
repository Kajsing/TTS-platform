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
    private string? _loadedDocumentId;
    private IReadOnlyList<ReaderBlock>? _loadedBlocks;

    public ReadingWindowPage Current { get; private set; } = new([], 0, null);

    public ReadingWindowPage UseLoadedDocument(
        string documentId,
        IReadOnlyList<ReaderBlock> blocks,
        int startOrdinal = 0)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        ArgumentNullException.ThrowIfNull(blocks);
        _loadedDocumentId = documentId;
        _loadedBlocks = blocks.ToArray();
        Current = CreateLoadedPage(startOrdinal);
        return Current;
    }

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

        if (string.Equals(documentId, _loadedDocumentId, StringComparison.Ordinal) &&
            _loadedBlocks is not null)
        {
            Current = CreateLoadedPage(startOrdinal);
            return Current;
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

    public Task<ReadingWindowPage> FollowPlaybackAsync(
        string documentId,
        int blockOrdinal,
        int contextBlocks = 16,
        int prefetchThreshold = 8,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        if (blockOrdinal < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(blockOrdinal));
        }
        if (contextBlocks < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(contextBlocks));
        }
        if (prefetchThreshold < 1 || prefetchThreshold >= pageSize)
        {
            throw new ArgumentOutOfRangeException(nameof(prefetchThreshold));
        }

        var blockIndex = -1;
        for (var index = 0; index < Current.Blocks.Count; index++)
        {
            if (Current.Blocks[index].Ordinal == blockOrdinal)
            {
                blockIndex = index;
                break;
            }
        }
        var needsAnotherWindow = blockIndex < 0 ||
            (Current.HasNext && blockIndex >= Current.Blocks.Count - prefetchThreshold);
        var startOrdinal = Math.Max(0, blockOrdinal - contextBlocks);
        if (!needsAnotherWindow || startOrdinal == Current.StartOrdinal)
        {
            return Task.FromResult(Current);
        }

        return LoadAsync(documentId, startOrdinal, cancellationToken);
    }

    private ReadingWindowPage CreateLoadedPage(int startOrdinal)
    {
        if (startOrdinal < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(startOrdinal));
        }
        var loadedBlocks = _loadedBlocks!;
        var blocks = loadedBlocks
            .Where(block => block.Ordinal >= startOrdinal)
            .Take(pageSize)
            .ToArray();
        var hasNext = blocks.Length > 0 &&
            loadedBlocks.Any(block => block.Ordinal > blocks[^1].Ordinal);
        return new ReadingWindowPage(
            blocks,
            startOrdinal,
            hasNext ? blocks[^1].Ordinal : null);
    }
}
