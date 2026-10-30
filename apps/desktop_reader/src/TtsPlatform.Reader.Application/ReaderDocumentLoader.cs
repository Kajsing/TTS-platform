using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record LoadedReaderDocument(
    ReaderDocument Document,
    ContinuousDocumentText? ContinuousText,
    ReadingWindowPager ReadingWindow,
    ReadingWindowPage Page);

// Stage a consistent snapshot before replacing anything in the visible editor.
public sealed class ReaderDocumentLoader(
    IReaderServiceClient client, int maxCharacters = 1_000_000, int maxBlocks = 20_000)
{
    public Task<LoadedReaderDocument> LoadAsync(
        string documentId, CancellationToken cancellationToken = default) =>
        LoadCoreAsync(documentId, null, cancellationToken);

    public Task<LoadedReaderDocument> LoadAsync(
        ReaderDocument initialDocument, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(initialDocument);
        return LoadCoreAsync(initialDocument.Id, initialDocument, cancellationToken);
    }

    private async Task<LoadedReaderDocument> LoadCoreAsync(
        string documentId, ReaderDocument? initialDocument, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var document = initialDocument ?? await client.GetDocumentAsync(documentId, cancellationToken).ConfigureAwait(false);
        for (var attempt = 0; attempt < 2; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            RequireAvailable(document);
            var continuous = document.IsEditable && document.TotalCharacters <= maxCharacters &&
                document.TotalBlocks <= maxBlocks;
            var blocks = new List<ReaderBlock>();
            long characters = 0;
            var exceededEditorBounds = false;
            var after = -1;
            BlockPage page;
            do
            {
                cancellationToken.ThrowIfCancellationRequested();
                page = await client.GetBlocksAsync(documentId, after, continuous ? 500 : 64, cancellationToken)
                    .ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();
                blocks.AddRange(page.Blocks);
                characters += page.Blocks.Sum(block => (long)block.CharacterCount);
                if (continuous && (blocks.Count > maxBlocks || characters > maxCharacters))
                {
                    exceededEditorBounds = true;
                    break;
                }
                if (page.NextAfterOrdinal is not int next || !continuous) break;
                if (next <= after)
                    throw new ReaderApiException("reader_invalid_page", "The service returned a non-advancing document page.", 502);
                after = next;
            } while (true);

            cancellationToken.ThrowIfCancellationRequested();
            var current = await client.GetDocumentFreshAsync(documentId, cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            RequireAvailable(current);
            if (!ReaderDocumentVersions.AreSame(document, current))
            {
                document = current;
                continue;
            }
            if (exceededEditorBounds)
                throw new ReaderApiException("reader_revision_conflict", "The article grew while loading. Open it again.", 409);
            var pager = new ReadingWindowPager(client);
            var text = continuous ? new ContinuousDocumentText(blocks) : null;
            var readingPage = text is not null
                ? pager.UseLoadedDocument(document.Id, blocks)
                : pager.UsePage(new ReadingWindowPage(blocks, 0, page.NextAfterOrdinal));
            return new LoadedReaderDocument(current, text, pager, readingPage);
        }
        throw new ReaderApiException("reader_revision_conflict",
            "The article is still changing. Your current text has been kept; select the article again to retry.", 409);
    }

    private static void RequireAvailable(ReaderDocument document)
    {
        if (document.DeletedAt is not null)
            throw new ReaderApiException("reader_not_found", "This article has been deleted from the library.", 404);
    }
}
