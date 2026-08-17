using System.Buffers;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record ArticleFindOptions(
    bool CaseSensitive = false,
    bool WholeWord = false,
    bool UseRegex = false,
    int MaxResults = ArticleFindEngine.DefaultMaxResults,
    int RegexTimeoutMilliseconds = ArticleFindEngine.DefaultRegexTimeoutMilliseconds);

public enum ArticleFindFailure
{
    None,
    PatternTooLong,
    DocumentTooLarge,
    InvalidRegex,
    RegexTimedOut,
}

public sealed record ArticleFindMatch(int Start, int Length)
{
    public int End => Start + Length;
}

public sealed record ArticleFindResult(
    IReadOnlyList<ArticleFindMatch> Matches,
    bool Truncated = false,
    ArticleFindFailure Failure = ArticleFindFailure.None)
{
    public static ArticleFindResult Empty { get; } = new([]);
    public bool Succeeded => Failure == ArticleFindFailure.None;
}

public static class ArticleFindEngine
{
    public const int MaxPatternCharacters = 1_024;
    public const int MaxDocumentCharacters = 32_000_000;
    public const int DefaultMaxResults = 10_000;
    public const int DefaultRegexTimeoutMilliseconds = 200;

    public static ArticleFindResult Search(
        string text,
        string pattern,
        ArticleFindOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(text);
        ArgumentNullException.ThrowIfNull(pattern);
        options ??= new ArticleFindOptions();
        ValidateOptions(options);

        if (pattern.Length == 0)
        {
            return ArticleFindResult.Empty;
        }
        if (pattern.Length > MaxPatternCharacters)
        {
            return new ArticleFindResult([], Failure: ArticleFindFailure.PatternTooLong);
        }
        if (text.Length > MaxDocumentCharacters)
        {
            return new ArticleFindResult([], Failure: ArticleFindFailure.DocumentTooLarge);
        }

        return options.UseRegex
            ? SearchRegex(text, pattern, options)
            : SearchLiteral(text, pattern, options);
    }

    private static ArticleFindResult SearchLiteral(
        string text,
        string pattern,
        ArticleFindOptions options)
    {
        var comparison = options.CaseSensitive
            ? StringComparison.Ordinal
            : StringComparison.OrdinalIgnoreCase;
        var matches = new List<ArticleFindMatch>(Math.Min(options.MaxResults, 256));
        var searchAt = 0;
        while (searchAt <= text.Length - pattern.Length)
        {
            var foundAt = text.IndexOf(pattern, searchAt, comparison);
            if (foundAt < 0)
            {
                break;
            }

            if (!options.WholeWord || IsWholeWord(text, foundAt, pattern.Length))
            {
                if (matches.Count == options.MaxResults)
                {
                    return new ArticleFindResult(matches, Truncated: true);
                }
                matches.Add(new ArticleFindMatch(foundAt, pattern.Length));
            }
            searchAt = foundAt + Math.Max(1, pattern.Length);
        }
        return new ArticleFindResult(matches);
    }

    private static ArticleFindResult SearchRegex(
        string text,
        string pattern,
        ArticleFindOptions options)
    {
        var effectivePattern = options.WholeWord
            ? $"(?<![\\p{{L}}\\p{{M}}\\p{{N}}_])(?:{pattern})(?![\\p{{L}}\\p{{M}}\\p{{N}}_])"
            : pattern;
        var regexOptions = RegexOptions.CultureInvariant | RegexOptions.Multiline;
        if (!options.CaseSensitive)
        {
            regexOptions |= RegexOptions.IgnoreCase;
        }

        try
        {
            var regex = new Regex(
                effectivePattern,
                regexOptions,
                TimeSpan.FromMilliseconds(options.RegexTimeoutMilliseconds));
            var matches = new List<ArticleFindMatch>(Math.Min(options.MaxResults, 256));
            for (var match = regex.Match(text); match.Success; match = match.NextMatch())
            {
                if (match.Length == 0)
                {
                    continue;
                }
                if (matches.Count == options.MaxResults)
                {
                    return new ArticleFindResult(matches, Truncated: true);
                }
                matches.Add(new ArticleFindMatch(match.Index, match.Length));
            }
            return new ArticleFindResult(matches);
        }
        catch (ArgumentException)
        {
            return new ArticleFindResult([], Failure: ArticleFindFailure.InvalidRegex);
        }
        catch (RegexMatchTimeoutException)
        {
            return new ArticleFindResult([], Failure: ArticleFindFailure.RegexTimedOut);
        }
    }

    private static bool IsWholeWord(string text, int start, int length) =>
        !IsWordCharacterBefore(text, start) &&
        !IsWordCharacterAt(text, start + length);

    private static bool IsWordCharacterBefore(string text, int index)
    {
        if (index <= 0)
        {
            return false;
        }
        var status = Rune.DecodeLastFromUtf16(text.AsSpan(0, index), out var rune, out _);
        return status == OperationStatus.Done && IsWordRune(rune);
    }

    private static bool IsWordCharacterAt(string text, int index)
    {
        if (index >= text.Length)
        {
            return false;
        }
        var status = Rune.DecodeFromUtf16(text.AsSpan(index), out var rune, out _);
        return status == OperationStatus.Done && IsWordRune(rune);
    }

    private static bool IsWordRune(Rune rune)
    {
        var category = Rune.GetUnicodeCategory(rune);
        return Rune.IsLetterOrDigit(rune) ||
            category is UnicodeCategory.NonSpacingMark or
                UnicodeCategory.SpacingCombiningMark or
                UnicodeCategory.EnclosingMark ||
            rune.Value == '_';
    }

    private static void ValidateOptions(ArticleFindOptions options)
    {
        if (options.MaxResults <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(options), "Find result limit must be positive.");
        }
        if (options.RegexTimeoutMilliseconds <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(options), "Regex timeout must be positive.");
        }
    }
}

public sealed record ArticleFindLocation(
    ArticleFindMatch Match,
    ReaderCursor StartCursor,
    ReaderCursor EndCursor);

public sealed class ArticleFindDocument
{
    private readonly ContinuousDocumentText _content;

    public ArticleFindDocument(ReaderDocument document, IReadOnlyList<ReaderBlock> blocks)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(blocks);
        Document = document;
        _content = new ContinuousDocumentText(blocks);
    }

    public ReaderDocument Document { get; }
    public IReadOnlyList<ReaderBlock> Blocks => _content.Blocks;
    public string Text => _content.Text;

    public ArticleFindLocation Locate(ArticleFindMatch match)
    {
        ArgumentNullException.ThrowIfNull(match);
        if (match.Start < 0 || match.End > Text.Length || match.Length <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(match));
        }
        return new ArticleFindLocation(
            match,
            _content.CursorAt(Document.Id, Document.ContentRevision, match.Start),
            _content.CursorAt(Document.Id, Document.ContentRevision, match.End));
    }
}

public sealed class ArticleFindDocumentLoader(IReaderServiceClient client, int pageSize = 500)
{
    private string? _cachedDocumentId;
    private int _cachedContentRevision;
    private ArticleFindDocument? _cachedDocument;

    public async Task<ArticleFindDocument> LoadAsync(
        ReaderDocument document,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (pageSize <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(pageSize));
        }
        if (string.Equals(_cachedDocumentId, document.Id, StringComparison.Ordinal) &&
            _cachedContentRevision == document.ContentRevision &&
            _cachedDocument is not null)
        {
            return _cachedDocument;
        }

        var blocks = new List<ReaderBlock>(Math.Max(0, document.TotalBlocks));
        var afterOrdinal = -1;
        while (true)
        {
            var page = await client.GetBlocksAsync(
                document.Id,
                afterOrdinal,
                pageSize,
                cancellationToken).ConfigureAwait(false);
            blocks.AddRange(page.Blocks);
            if (page.NextAfterOrdinal is not int nextAfterOrdinal)
            {
                break;
            }
            if (nextAfterOrdinal <= afterOrdinal)
            {
                throw new ReaderApiException(
                    "reader_invalid_page",
                    "The service returned a non-advancing document page.",
                    502);
            }
            afterOrdinal = nextAfterOrdinal;
        }

        var loaded = new ArticleFindDocument(document, blocks);
        _cachedDocumentId = document.Id;
        _cachedContentRevision = document.ContentRevision;
        _cachedDocument = loaded;
        return loaded;
    }

    public void Invalidate(string? documentId = null)
    {
        if (documentId is not null &&
            !string.Equals(documentId, _cachedDocumentId, StringComparison.Ordinal))
        {
            return;
        }
        _cachedDocumentId = null;
        _cachedContentRevision = 0;
        _cachedDocument = null;
    }
}

public static class ArticleFindNavigator
{
    public static int Move(int currentIndex, int matchCount, int delta)
    {
        if (matchCount <= 0)
        {
            return -1;
        }
        if (currentIndex < 0)
        {
            return delta < 0 ? matchCount - 1 : 0;
        }
        var normalizedCurrent = currentIndex % matchCount;
        return ((normalizedCurrent + delta) % matchCount + matchCount) % matchCount;
    }
}
