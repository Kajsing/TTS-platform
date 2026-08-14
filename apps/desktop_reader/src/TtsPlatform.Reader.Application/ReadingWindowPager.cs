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
    private const int SectionSearchPageSize = 256;
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

    public async Task<ReaderBlock?> FindNextSectionAsync(
        string documentId,
        int currentOrdinal,
        CancellationToken cancellationToken = default)
    {
        ValidateNavigationArguments(documentId, currentOrdinal);
        if (TryGetLoadedBlocks(documentId, out var loadedBlocks))
        {
            var currentIndex = FindBlockIndex(loadedBlocks, currentOrdinal);
            if (currentIndex < 0)
            {
                return null;
            }

            var loadedCurrentSectionId = loadedBlocks[currentIndex].SectionId;
            return loadedBlocks
                .Skip(currentIndex + 1)
                .FirstOrDefault(block => !SameSection(block.SectionId, loadedCurrentSectionId));
        }

        var afterOrdinal = currentOrdinal - 1;
        string? currentSectionId = null;
        var foundCurrent = false;
        while (true)
        {
            var page = await client.GetBlocksAsync(
                documentId,
                afterOrdinal,
                SectionSearchPageSize,
                cancellationToken).ConfigureAwait(false);
            if (!foundCurrent)
            {
                var current = page.Blocks.FirstOrDefault(block => block.Ordinal == currentOrdinal);
                if (current is null)
                {
                    return null;
                }
                currentSectionId = current.SectionId;
                foundCurrent = true;
            }

            var target = page.Blocks.FirstOrDefault(block =>
                block.Ordinal > currentOrdinal &&
                !SameSection(block.SectionId, currentSectionId));
            if (target is not null)
            {
                return target;
            }
            if (page.NextAfterOrdinal is not int nextAfterOrdinal ||
                nextAfterOrdinal <= afterOrdinal)
            {
                return null;
            }
            afterOrdinal = nextAfterOrdinal;
        }
    }

    public async Task<ReaderBlock?> FindPreviousSectionAsync(
        string documentId,
        int currentOrdinal,
        CancellationToken cancellationToken = default)
    {
        ValidateNavigationArguments(documentId, currentOrdinal);
        if (TryGetLoadedBlocks(documentId, out var loadedBlocks))
        {
            var currentIndex = FindBlockIndex(loadedBlocks, currentOrdinal);
            if (currentIndex < 0)
            {
                return null;
            }

            var currentSectionId = loadedBlocks[currentIndex].SectionId;
            var prior = loadedBlocks
                .Take(currentIndex)
                .LastOrDefault(block => !SameSection(block.SectionId, currentSectionId));
            if (prior is null)
            {
                return null;
            }
            return loadedBlocks
                .Take(currentIndex)
                .First(block => SameSection(block.SectionId, prior.SectionId));
        }

        var currentPage = await client.GetBlocksAsync(
            documentId,
            currentOrdinal - 1,
            1,
            cancellationToken).ConfigureAwait(false);
        var current = currentPage.Blocks.FirstOrDefault(block => block.Ordinal == currentOrdinal);
        if (current is null)
        {
            return null;
        }

        var searchEndOrdinal = currentOrdinal - 1;
        var foundPriorSection = false;
        string? priorSectionId = null;
        ReaderBlock? candidate = null;
        while (searchEndOrdinal >= 0)
        {
            var startOrdinal = Math.Max(0, searchEndOrdinal - SectionSearchPageSize + 1);
            var page = await client.GetBlocksAsync(
                documentId,
                startOrdinal - 1,
                searchEndOrdinal - startOrdinal + 1,
                cancellationToken).ConfigureAwait(false);
            foreach (var block in page.Blocks
                .Where(block => block.Ordinal <= searchEndOrdinal)
                .OrderByDescending(block => block.Ordinal))
            {
                if (!foundPriorSection)
                {
                    if (SameSection(block.SectionId, current.SectionId))
                    {
                        continue;
                    }
                    foundPriorSection = true;
                    priorSectionId = block.SectionId;
                    candidate = block;
                    continue;
                }
                if (!SameSection(block.SectionId, priorSectionId))
                {
                    return candidate;
                }
                candidate = block;
            }

            if (startOrdinal == 0 || page.Blocks.Count == 0)
            {
                return candidate;
            }
            searchEndOrdinal = startOrdinal - 1;
        }
        return candidate;
    }

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

    private bool TryGetLoadedBlocks(
        string documentId,
        out IReadOnlyList<ReaderBlock> loadedBlocks)
    {
        if (string.Equals(documentId, _loadedDocumentId, StringComparison.Ordinal) &&
            _loadedBlocks is not null)
        {
            loadedBlocks = _loadedBlocks;
            return true;
        }
        loadedBlocks = [];
        return false;
    }

    private static int FindBlockIndex(IReadOnlyList<ReaderBlock> blocks, int ordinal)
    {
        for (var index = 0; index < blocks.Count; index++)
        {
            if (blocks[index].Ordinal == ordinal)
            {
                return index;
            }
        }
        return -1;
    }

    private static bool SameSection(string? left, string? right) =>
        string.Equals(left, right, StringComparison.Ordinal);

    private static void ValidateNavigationArguments(string documentId, int currentOrdinal)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        if (currentOrdinal < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(currentOrdinal));
        }
    }
}
