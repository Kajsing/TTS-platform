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
    private readonly object _sync = new();
    private string? _loadedDocumentId;
    private IReadOnlyList<ReaderBlock>? _loadedBlocks;
    private ReadingWindowPage _current = new([], 0, null);
    private PendingPage? _pending;
    private int _generation;

    public ReadingWindowPage Current { get { lock (_sync) return _current; } }

    public void CancelPendingLoads()
    {
        lock (_sync) InvalidatePending();
    }

    public ReadingWindowPage UsePage(ReadingWindowPage page)
    {
        lock (_sync)
        {
            InvalidatePending();
            _loadedDocumentId = null;
            _loadedBlocks = null;
            _current = page;
            return _current;
        }
    }

    public ReadingWindowPage UseLoadedDocument(
        string documentId,
        IReadOnlyList<ReaderBlock> blocks,
        int startOrdinal = 0)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        ArgumentNullException.ThrowIfNull(blocks);
        lock (_sync)
        {
            InvalidatePending();
            _loadedDocumentId = documentId;
            _loadedBlocks = blocks.ToArray();
            _current = CreateLoadedPage(startOrdinal);
            return _current;
        }
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

        cancellationToken.ThrowIfCancellationRequested();
        PendingPage pending;
        lock (_sync)
        {
            if (string.Equals(documentId, _loadedDocumentId, StringComparison.Ordinal) &&
                _loadedBlocks is not null)
            {
                InvalidatePending();
                _current = CreateLoadedPage(startOrdinal);
                return _current;
            }
            if (_pending is { Cancelled: false } existing && existing.DocumentId == documentId && existing.StartOrdinal == startOrdinal)
                pending = existing;
            else
            {
                InvalidatePending();
                pending = new PendingPage(documentId, startOrdinal, _generation);
                _pending = pending;
                pending.Task = LoadPageAsync(pending);
            }
            pending.Waiters++;
        }
        try { return await pending.Task.WaitAsync(cancellationToken).ConfigureAwait(false); }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && pending.Cancelled)
        {
            return Current;
        }
        finally
        {
            lock (_sync)
            {
                pending.Waiters--;
                if (pending.Waiters == 0 && !pending.Task.IsCompleted) pending.Cancel();
            }
        }
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

        ReadingWindowPage current;
        lock (_sync)
        {
            current = _current;
            if (_pending is { Cancelled: false } pending && pending.DocumentId == documentId &&
                blockOrdinal >= pending.StartOrdinal && blockOrdinal < (long)pending.StartOrdinal + pageSize)
                return LoadAsync(documentId, pending.StartOrdinal, cancellationToken);
        }
        var blockIndex = -1;
        for (var index = 0; index < current.Blocks.Count; index++)
        {
            if (current.Blocks[index].Ordinal == blockOrdinal)
            {
                blockIndex = index;
                break;
            }
        }
        var needsAnotherWindow = blockIndex < 0 ||
            (current.HasNext && blockIndex >= current.Blocks.Count - prefetchThreshold);
        var startOrdinal = Math.Max(0, blockOrdinal - contextBlocks);
        if (!needsAnotherWindow || startOrdinal == current.StartOrdinal)
        {
            return Task.FromResult(current);
        }

        return LoadAsync(documentId, startOrdinal, cancellationToken);
    }

    private async Task<ReadingWindowPage> LoadPageAsync(PendingPage pending)
    {
        try
        {
            var page = await client.GetBlocksAsync(pending.DocumentId, pending.StartOrdinal - 1, pageSize,
                pending.Cancellation.Token).ConfigureAwait(false);
            pending.Cancellation.Token.ThrowIfCancellationRequested();
            lock (_sync)
            {
                if (pending.Generation != _generation)
                    throw new OperationCanceledException("The reading window was superseded.");
                _current = new ReadingWindowPage(page.Blocks, pending.StartOrdinal, page.NextAfterOrdinal);
                return _current;
            }
        }
        finally
        {
            lock (_sync)
            {
                if (ReferenceEquals(_pending, pending)) _pending = null;
                pending.Cancellation.Dispose();
            }
        }
    }

    private void InvalidatePending()
    {
        _generation++;
        _pending?.Cancel();
        _pending = null;
    }

    private sealed class PendingPage(string documentId, int startOrdinal, int generation)
    {
        public string DocumentId { get; } = documentId;
        public int StartOrdinal { get; } = startOrdinal;
        public int Generation { get; } = generation;
        public CancellationTokenSource Cancellation { get; } = new();
        public Task<ReadingWindowPage> Task { get; set; } = null!;
        public int Waiters { get; set; }
        public bool Cancelled { get; private set; }
        public void Cancel()
        {
            Cancelled = true;
            try { Cancellation.Cancel(); }
            catch (ObjectDisposedException) { }
        }
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
