using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record PagedChapterDestination(ReadingWindowPage Page, ReaderCursor Cursor);

public static class PagedChapterNavigation
{
    public const int MaxChapters = 1024;
    private const int PageSize = 64;

    public static void ValidateIndex(ReaderDocument document, ReaderChapterIndex index)
    {
        ArgumentNullException.ThrowIfNull(document);
        ValidateStructure(index);
        if (index.DocumentId != document.Id) throw Invalid();
        if (document.DeletedAt is not null || index.ContentRevision != document.ContentRevision) throw Changed();
        if (document.TotalBlocks < 0 || (document.TotalBlocks == 0) != (index.Chapters.Count == 0) ||
            index.Chapters.Any(chapter => chapter.BlockOrdinal >= document.TotalBlocks)) throw Invalid();
    }

    public static ReaderCursor ResolveCursor(ReaderDocument document, ReaderChapterAnchor chapter,
        IReadOnlyList<ReaderBlock> blocks)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (document.DeletedAt is not null) throw Changed();
        ValidateAnchor(chapter);
        ValidateBlocks(blocks, document.Id);
        if (chapter.BlockOrdinal >= document.TotalBlocks) throw Invalid();
        var block = blocks.SingleOrDefault(block => block.Ordinal == chapter.BlockOrdinal);
        if (block is null || block.Id != chapter.BlockId) throw Invalid();
        return new(document.Id, block.Id, block.Ordinal, Utf16Offset(block.Text, chapter.CodepointOffset), document.ContentRevision);
    }

    public static ReaderChapterAnchor? AtCursor(ReaderChapterIndex index, ReaderCursor cursor,
        IReadOnlyList<ReaderBlock> blocks)
    {
        ValidateStructure(index);
        if (cursor is null || cursor.DocumentId != index.DocumentId || string.IsNullOrWhiteSpace(cursor.BlockId) ||
            cursor.BlockOrdinal < 0 || cursor.CharacterOffset < 0) throw Invalid();
        if (cursor.ContentRevision != index.ContentRevision) throw Changed();
        ValidateBlocks(blocks, index.DocumentId);
        var block = blocks.SingleOrDefault(block => block.Ordinal == cursor.BlockOrdinal);
        if (block is not null && (block.Id != cursor.BlockId || cursor.CharacterOffset > block.Text.Length ||
            SplitsSurrogatePair(block.Text, cursor.CharacterOffset))) throw Invalid();

        ReaderChapterAnchor? current = null;
        var mappedCodepoints = 0;
        var mappedUtf16 = 0;
        foreach (var chapter in index.Chapters)
        {
            if (chapter.BlockOrdinal > cursor.BlockOrdinal) break;
            if (chapter.BlockOrdinal < cursor.BlockOrdinal)
            {
                current = chapter;
                continue;
            }
            if (chapter.BlockId != cursor.BlockId) throw Invalid();
            // Codepoint and UTF-16 offsets are different units. Without this
            // block's text, only its zero-offset anchor can be selected safely.
            if (block is null)
            {
                if (chapter.CodepointOffset == 0) current = chapter;
            }
            else
            {
                // Anchors are ordered. Advance through this block once rather
                // than rescanning a large block for every chapter marker.
                AdvanceUtf16Offset(block.Text, chapter.CodepointOffset, ref mappedCodepoints, ref mappedUtf16);
                if (mappedUtf16 <= cursor.CharacterOffset) current = chapter;
            }
        }
        return current;
    }

    public static async Task<PagedChapterDestination> StageNavigationAsync(IReaderServiceClient client,
        ReaderDocument document, ReaderChapterIndex index, ReaderChapterAnchor chapter,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        ValidateIndex(document, index);
        if (chapter is null || !index.Chapters.Contains(chapter)) throw Invalid();
        cancellationToken.ThrowIfCancellationRequested();
        var before = await client.GetDocumentFreshAsync(document.Id, cancellationToken).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        RequireRevision(document, before);

        // This pager is private to the staged jump. A failed page, stale fence,
        // or cancellation cannot change the visible Reader's current page.
        var pager = new ReadingWindowPager(client, PageSize);
        var page = await pager.LoadAsync(document.Id, chapter.BlockOrdinal, cancellationToken).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        var cursor = ResolveCursor(document, chapter, page.Blocks);
        var after = await client.GetDocumentFreshAsync(document.Id, cancellationToken).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        RequireRevision(document, after);
        if (!ReaderDocumentVersions.AreSame(before, after)) throw Changed();
        return new(page, cursor);
    }

    private static void ValidateStructure(ReaderChapterIndex index)
    {
        if (index is null || string.IsNullOrWhiteSpace(index.DocumentId) || index.ContentRevision < 1 ||
            index.Chapters is null || index.Chapters.Count > MaxChapters) throw Invalid();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var blockOrdinals = new Dictionary<string, int>(StringComparer.Ordinal);
        ReaderChapterAnchor? prior = null;
        foreach (var chapter in index.Chapters)
        {
            ValidateAnchor(chapter);
            if (!ids.Add(chapter.Id) ||
                (prior is null && (chapter.BlockOrdinal != 0 || chapter.CodepointOffset != 0)) ||
                (prior is not null && (chapter.BlockOrdinal < prior.BlockOrdinal ||
                    (chapter.BlockOrdinal == prior.BlockOrdinal &&
                        (chapter.CodepointOffset <= prior.CodepointOffset || chapter.BlockId != prior.BlockId)))) ||
                (blockOrdinals.TryGetValue(chapter.BlockId, out var ordinal) && ordinal != chapter.BlockOrdinal)) throw Invalid();
            blockOrdinals[chapter.BlockId] = chapter.BlockOrdinal;
            prior = chapter;
        }
    }

    private static void ValidateAnchor(ReaderChapterAnchor chapter)
    {
        if (chapter is null || string.IsNullOrWhiteSpace(chapter.Id) || string.IsNullOrWhiteSpace(chapter.Title) ||
            string.IsNullOrWhiteSpace(chapter.BlockId) || chapter.BlockOrdinal < 0 || chapter.CodepointOffset < 0) throw Invalid();
    }

    private static void ValidateBlocks(IReadOnlyList<ReaderBlock> blocks, string documentId)
    {
        if (blocks is null || blocks.Count > PageSize) throw Invalid();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var previousOrdinal = -1;
        foreach (var block in blocks)
        {
            if (block is null || block.DocumentId != documentId || string.IsNullOrWhiteSpace(block.Id) ||
                block.Text is null || block.Ordinal <= previousOrdinal || !ids.Add(block.Id)) throw Invalid();
            previousOrdinal = block.Ordinal;
        }
    }

    private static int Utf16Offset(string text, int codepoints)
    {
        var offset = 0;
        var count = 0;
        AdvanceUtf16Offset(text, codepoints, ref count, ref offset);
        return offset;
    }

    private static void AdvanceUtf16Offset(string text, int codepoints, ref int count, ref int offset)
    {
        while (count < codepoints)
        {
            if (offset >= text.Length) throw Invalid();
            // Match existing chapter metadata/Python codepoint semantics:
            // valid pairs count once, and isolated surrogates count once.
            offset += char.IsSurrogatePair(text, offset) ? 2 : 1;
            count++;
        }
    }

    private static bool SplitsSurrogatePair(string text, int offset) =>
        offset > 0 && offset < text.Length && char.IsHighSurrogate(text[offset - 1]) && char.IsLowSurrogate(text[offset]);

    private static void RequireRevision(ReaderDocument expected, ReaderDocument current)
    {
        if (current is null || current.Id != expected.Id) throw Invalid();
        if (current.DeletedAt is not null || current.ContentRevision != expected.ContentRevision ||
            current.FolderId != expected.FolderId) throw Changed();
    }

    private static ReaderApiException Invalid() => new("reader_chapter_index_invalid_response",
        "The service returned inconsistent chapter navigation data. Reopen the article to refresh it.", 502);

    private static ReaderApiException Changed() => new("reader_revision_conflict",
        "The article changed while preparing the chapter. Your current page has been kept; reopen the article and try again.", 409);
}
