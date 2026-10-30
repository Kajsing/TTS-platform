using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record RemoteArticleFind(ReaderSearchSummary Summary, IReadOnlyList<ReaderSearchHit> Hits,
    ArticleFindResult Result);
public sealed record RemoteBlockHighlight(int Start, int Length, string Color, string TermId);

public static class RemoteArticleSearch
{
    public static async Task<RemoteArticleFind> FindAsync(IReaderServiceClient client, ReaderDocument document,
        string query, ArticleFindOptions options, CancellationToken cancellationToken = default)
    {
        var summary = await ReadAsync(() => client.CreateSearchAsync(document.Id,
            new(document.ContentRevision, query, options.CaseSensitive, options.WholeWord, options.UseRegex, options.MaxResults),
            cancellationToken), cancellationToken).ConfigureAwait(false);
        ValidateSummary(summary, document, "find", options.MaxResults);
        var failure = Failure(summary.Failure);
        if (failure != ArticleFindFailure.None)
            return new(summary, [], new([], summary.Truncated, failure));
        var hits = new List<ReaderSearchHit>(Math.Min(summary.TotalMatches, 1000));
        var offset = 0;
        while (offset < summary.TotalMatches)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var page = await ReadAsync(() => client.GetSearchResultsAsync(document.Id, summary.SearchId,
                new(offset), cancellationToken), cancellationToken).ConfigureAwait(false);
            ValidatePage(page, document, summary.TotalMatches, 1000);
            if (page.Matches.Count == 0 || page.Matches[0].Index != offset ||
                page.Matches.Where((hit, index) => hit.Index != offset + index).Any()) throw Invalid();
            var previousEnd = hits.Count == 0 ? 0 : hits[^1].Start + hits[^1].Length;
            foreach (var hit in page.Matches)
            {
                if (hit.Start < previousEnd) throw Invalid();
                previousEnd = hit.Start + hit.Length;
            }
            hits.AddRange(page.Matches);
            if (hits.Count > summary.TotalMatches) throw Invalid();
            if (page.NextOffset is not int next)
            {
                if (hits.Count != summary.TotalMatches) throw Invalid();
                break;
            }
            if (next != hits.Count || next <= offset || next >= summary.TotalMatches) throw Invalid();
            offset = next;
        }
        return new(summary, hits, new(hits.Select(hit => new ArticleFindMatch(hit.Start, hit.Length)).ToArray(), summary.Truncated));
    }

    public static async Task<ReaderSearchSummary> HighlightsAsync(IReaderServiceClient client, ReaderDocument document,
        ReaderHighlighterConfiguration configuration, CancellationToken cancellationToken = default)
    {
        var summary = await ReadAsync(() => client.CreateHighlightSearchAsync(document.Id,
            new(document.ContentRevision, configuration.RowVersion), cancellationToken), cancellationToken).ConfigureAwait(false);
        ValidateSummary(summary, document, "highlighter", WordHighlighterEngine.MaxMatches);
        if (summary.Failure is not null) throw new ReaderApiException("reader_search_failed", DescribeFailure(summary.Failure), 422);
        if (summary.Counts.Count > WordHighlighterEngine.MaxTerms || summary.Counts.Values.Any(count => count < 0)) throw Invalid();
        return summary;
    }

    public static async Task<ReaderSearchPage> WindowAsync(IReaderServiceClient client, ReaderDocument document,
        ReaderSearchSummary summary, IReadOnlyList<ReaderBlock> blocks, CancellationToken cancellationToken = default)
    {
        if (blocks.Count == 0) return new(document.Id, document.ContentRevision, [], null, summary.TotalMatches, false);
        var page = await ReadAsync(() => client.GetSearchWindowAsync(document.Id, summary.SearchId,
            new(blocks.Min(block => block.Ordinal), blocks.Max(block => block.Ordinal)), cancellationToken), cancellationToken).ConfigureAwait(false);
        ValidatePage(page, document, summary.TotalMatches, 2000);
        if (page.NextOffset is not null) throw Invalid();
        return page;
    }

    public static async Task<ReaderSearchHit?> NextAsync(IReaderServiceClient client, ReaderDocument document,
        ReaderSearchSummary summary, string termId, int afterIndex, CancellationToken cancellationToken = default)
    {
        var next = await ReadAsync(() => client.GetNextSearchMatchAsync(document.Id, summary.SearchId,
            new(termId, afterIndex), cancellationToken), cancellationToken).ConfigureAwait(false);
        if (next.Match is { } hit)
        {
            ValidateHit(hit, document, summary.TotalMatches);
            if (hit.TermId != termId) throw Invalid();
        }
        return next.Match;
    }

    public static async Task<ReaderSearchHit> FindHitAsync(IReaderServiceClient client, ReaderDocument document,
        RemoteArticleFind find, int index, CancellationToken cancellationToken = default)
    {
        if (index < 0 || index >= find.Hits.Count) throw new ArgumentOutOfRangeException(nameof(index));
        var page = await ReadAsync(() => client.GetSearchResultsAsync(document.Id, find.Summary.SearchId,
            new(index, 1), cancellationToken), cancellationToken).ConfigureAwait(false);
        ValidatePage(page, document, find.Summary.TotalMatches, 1);
        if (page.Matches.Count != 1 || page.Matches[0] != find.Hits[index]) throw Invalid();
        return page.Matches[0];
    }

    public static ArticleFindLocation Locate(ReaderSearchHit hit) =>
        new(new(hit.Start, hit.Length), hit.StartCursor, hit.EndCursor);

    public static IReadOnlyDictionary<int, IReadOnlyList<RemoteBlockHighlight>> MapHighlights(
        IReadOnlyList<ReaderBlock> blocks, IReadOnlyList<ReaderSearchHit> hits,
        IReadOnlyList<ReaderHighlighterTerm> terms)
    {
        var colors = terms.ToDictionary(term => term.Id, term => term.Color, StringComparer.Ordinal);
        var result = new Dictionary<int, IReadOnlyList<RemoteBlockHighlight>>();
        foreach (var block in blocks)
        {
            var ranges = new List<RemoteBlockHighlight>();
            foreach (var hit in hits.Where(hit => hit.StartCursor.BlockOrdinal <= block.Ordinal && hit.EndCursor.BlockOrdinal >= block.Ordinal))
            {
                if ((block.Ordinal == hit.StartCursor.BlockOrdinal && block.Id != hit.StartCursor.BlockId) ||
                    (block.Ordinal == hit.EndCursor.BlockOrdinal && block.Id != hit.EndCursor.BlockId)) throw Invalid();
                if (hit.TermId is null || !colors.TryGetValue(hit.TermId, out var color)) continue;
                var start = block.Ordinal == hit.StartCursor.BlockOrdinal ? hit.StartCursor.CharacterOffset : 0;
                var end = block.Ordinal == hit.EndCursor.BlockOrdinal ? hit.EndCursor.CharacterOffset : block.Text.Length;
                start = Math.Clamp(start, 0, block.Text.Length);
                end = Math.Clamp(end, start, block.Text.Length);
                if (end > start) ranges.Add(new(start, end - start, color, hit.TermId));
            }
            result[block.Ordinal] = ranges;
        }
        return result;
    }

    private static async Task<T> ReadAsync<T>(Func<Task<T>> read, CancellationToken cancellationToken)
    {
        // These POST routes are read-only. Retry only explicit pre-admission 429,
        // never a lost response or an ordinary mutation.
        for (var attempt = 0; ; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var result = await read().ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();
                return result;
            }
            catch (ReaderApiException exception) when (exception.StatusCode == 429 && attempt < 2)
            {
                await Task.Delay(ReaderRetryDelay.ForError(exception, TimeSpan.FromSeconds(61)), cancellationToken).ConfigureAwait(false);
            }
            catch (ReaderApiException exception) when (exception.StatusCode == 404)
            {
                throw new ReaderApiException("reader_search_unavailable", "Update the Reader service to search paged articles without downloading their source.", 404);
            }
        }
    }

    private static void ValidateSummary(ReaderSearchSummary summary, ReaderDocument document, string kind, int limit)
    {
        if (summary is null || string.IsNullOrWhiteSpace(summary.SearchId) || summary.DocumentId != document.Id ||
            summary.ContentRevision != document.ContentRevision || summary.Kind != kind ||
            summary.Counts is null || summary.TotalMatches < 0 || summary.TotalMatches > limit) throw Invalid();
    }

    private static void ValidatePage(ReaderSearchPage page, ReaderDocument document, int total, int limit)
    {
        if (page is null || page.DocumentId != document.Id || page.ContentRevision != document.ContentRevision ||
            page.TotalMatches != total || page.Matches is null || page.Matches.Count > limit) throw Invalid();
        foreach (var hit in page.Matches) ValidateHit(hit, document, total);
    }

    private static void ValidateHit(ReaderSearchHit hit, ReaderDocument document, int total)
    {
        if (hit is null || hit.StartCursor is null || hit.EndCursor is null ||
            hit.Index < 0 || hit.Index >= total || hit.Start < 0 || hit.Length <= 0 ||
            (long)hit.Start + hit.Length > ArticleFindEngine.MaxDocumentCharacters ||
            hit.StartCursor.DocumentId != document.Id || hit.EndCursor.DocumentId != document.Id ||
            string.IsNullOrWhiteSpace(hit.StartCursor.BlockId) || string.IsNullOrWhiteSpace(hit.EndCursor.BlockId) ||
            hit.StartCursor.ContentRevision != document.ContentRevision || hit.EndCursor.ContentRevision != document.ContentRevision ||
            hit.StartCursor.BlockOrdinal < 0 || hit.EndCursor.BlockOrdinal < hit.StartCursor.BlockOrdinal ||
            hit.StartCursor.BlockOrdinal >= document.TotalBlocks || hit.EndCursor.BlockOrdinal >= document.TotalBlocks ||
            hit.StartCursor.CharacterOffset < 0 || hit.EndCursor.CharacterOffset < 0 ||
            (hit.StartCursor.BlockOrdinal == hit.EndCursor.BlockOrdinal && hit.EndCursor.CharacterOffset < hit.StartCursor.CharacterOffset)) throw Invalid();
    }

    private static ArticleFindFailure Failure(string? failure) => failure switch
    {
        null => ArticleFindFailure.None,
        "pattern_too_long" => ArticleFindFailure.PatternTooLong,
        "document_too_large" => ArticleFindFailure.DocumentTooLarge,
        "invalid_regex" => ArticleFindFailure.InvalidRegex,
        "regex_timed_out" => ArticleFindFailure.RegexTimedOut,
        "unsupported_regex" => ArticleFindFailure.UnsupportedRegex,
        "search_timed_out" => ArticleFindFailure.SearchTimedOut,
        _ => throw new ReaderApiException("reader_search_failed", DescribeFailure(failure), 422),
    };

    private static string DescribeFailure(string failure) => failure switch
    {
        "document_too_large" => "The article exceeds the service search size limit.",
        "regex_timed_out" => "Search took too long and was stopped.",
        "invalid_regex" => "The pattern is not supported by the service regex dialect.",
        "unsupported_regex" => "The pattern uses a construct that is not supported by the service regex-v0 dialect.",
        "search_timed_out" => "Search exceeded the service work limit and was stopped.",
        "cancelled" => "Search was cancelled. Run it again.",
        _ => "The service could not complete this search. Try again.",
    };

    private static ReaderApiException Invalid() => new("reader_search_invalid_response", "The service returned inconsistent search results.", 502);
}
