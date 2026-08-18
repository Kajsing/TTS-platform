using System.Text.RegularExpressions;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record WordHighlightMatch(
    string TermId,
    int Start,
    int Length,
    string Color)
{
    public int End => Start + Length;
}

public sealed record WordHighlightResult(
    IReadOnlyList<WordHighlightMatch> Matches,
    IReadOnlyDictionary<string, int> Counts,
    bool Truncated = false,
    bool TimedOut = false)
{
    public static WordHighlightResult Empty { get; } = new(
        [],
        new Dictionary<string, int>(StringComparer.Ordinal));
}

public static class WordHighlighterEngine
{
    public const int MaxTerms = 200;
    public const int MaxTermCharacters = 200;
    public const int MaxMatches = 250_000;
    private static readonly TimeSpan MatchTimeout = TimeSpan.FromSeconds(2);

    public static WordHighlightResult Search(
        string text,
        IReadOnlyList<ReaderHighlighterTerm> terms)
    {
        ArgumentNullException.ThrowIfNull(text);
        ArgumentNullException.ThrowIfNull(terms);
        if (terms.Count > MaxTerms)
        {
            throw new ArgumentOutOfRangeException(nameof(terms));
        }

        var active = terms
            .Where(term => term.Active && !string.IsNullOrWhiteSpace(term.Term))
            .OrderByDescending(term => term.Term.Length)
            .ThenBy(term => term.Ordinal)
            .ToArray();
        if (text.Length == 0 || active.Length == 0)
        {
            return WordHighlightResult.Empty;
        }
        if (active.Any(term => term.Term.Length > MaxTermCharacters))
        {
            throw new ArgumentOutOfRangeException(nameof(terms));
        }

        var pattern =
            $"(?<![\\p{{L}}\\p{{M}}\\p{{N}}_])(?:{string.Join('|', active.Select(term => Regex.Escape(term.Term)))})" +
            "(?![\\p{L}\\p{M}\\p{N}_])";
        var regex = new Regex(
            pattern,
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant,
            MatchTimeout);
        var counts = active.ToDictionary(
            term => term.Id,
            _ => 0,
            StringComparer.Ordinal);
        var termsByText = active.ToDictionary(
            term => term.Term,
            StringComparer.InvariantCultureIgnoreCase);
        var matches = new List<WordHighlightMatch>();
        try
        {
            foreach (Match match in regex.Matches(text))
            {
                var term = termsByText[match.Value];
                counts[term.Id]++;
                if (matches.Count == MaxMatches)
                {
                    return new WordHighlightResult(matches, counts, Truncated: true);
                }
                matches.Add(new WordHighlightMatch(
                    term.Id,
                    match.Index,
                    match.Length,
                    term.Color));
            }
        }
        catch (RegexMatchTimeoutException)
        {
            return new WordHighlightResult([], counts, TimedOut: true);
        }
        return new WordHighlightResult(matches, counts);
    }
}

public static class WordHighlighterNavigator
{
    public static int Move(
        IReadOnlyList<WordHighlightMatch> matches,
        string termId,
        int currentGlobalIndex)
    {
        ArgumentNullException.ThrowIfNull(matches);
        ArgumentException.ThrowIfNullOrWhiteSpace(termId);
        var indexes = matches
            .Select((match, index) => (match, index))
            .Where(item => string.Equals(item.match.TermId, termId, StringComparison.Ordinal))
            .Select(item => item.index)
            .ToArray();
        if (indexes.Length == 0)
        {
            return -1;
        }
        var currentPosition = Array.IndexOf(indexes, currentGlobalIndex);
        return indexes[(currentPosition + 1) % indexes.Length];
    }
}
