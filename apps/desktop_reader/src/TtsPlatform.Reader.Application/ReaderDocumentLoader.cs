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
    public async Task<LoadedReaderDocument> LoadAsync(
        string documentId, CancellationToken cancellationToken = default)
    {
        for (var attempt = 0; attempt < 2; attempt++)
        {
            var document = await client.GetDocumentAsync(documentId, cancellationToken).ConfigureAwait(false);
            RequireAvailable(document);
            var continuous = document.IsEditable && document.TotalCharacters <= maxCharacters &&
                document.TotalBlocks <= maxBlocks;
            var blocks = new List<ReaderBlock>();
            var after = -1;
            BlockPage page;
            do
            {
                page = await client.GetBlocksAsync(documentId, after, continuous ? 500 : 64, cancellationToken)
                    .ConfigureAwait(false);
                blocks.AddRange(page.Blocks);
                if (continuous && (blocks.Count > maxBlocks || blocks.Sum(block => (long)block.CharacterCount) > maxCharacters))
                    throw new ReaderApiException("reader_revision_conflict", "The article grew while loading. Open it again.", 409);
                if (page.NextAfterOrdinal is not int next || !continuous) break;
                if (next <= after)
                    throw new ReaderApiException("reader_invalid_page", "The service returned a non-advancing document page.", 502);
                after = next;
            } while (true);

            var current = await client.GetDocumentAsync(documentId, cancellationToken).ConfigureAwait(false);
            RequireAvailable(current);
            if (!ReaderDocumentVersions.AreSame(document, current)) continue;
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
