using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class WordHighlighterTests
{
    [Fact]
    public void Longer_phrases_win_and_counts_cover_all_non_overlapping_matches()
    {
        var terms = new[]
        {
            Term("identity", 0, "#F9DCC4"),
            Term("identity resolution", 1, "#BFE8D5"),
        };

        var result = WordHighlighterEngine.Search(
            "Identity resolution failed. Identity remains unknown.",
            terms);

        Assert.Equal(2, result.Matches.Count);
        Assert.Equal("term-1", result.Matches[0].TermId);
        Assert.Equal("term-0", result.Matches[1].TermId);
        Assert.Equal(1, result.Counts["term-0"]);
        Assert.Equal(1, result.Counts["term-1"]);
    }

    [Fact]
    public void Matching_is_unicode_word_aware_case_insensitive_and_ignores_inactive_terms()
    {
        var result = WordHighlighterEngine.Search(
            "Ål ålX ÅL Mara",
            [Term("ål", 0, "#F9DCC4"), Term("Mara", 1, "#BFE8D5", active: false)]);

        Assert.Equal([0, 7], result.Matches.Select(match => match.Start));
        Assert.DoesNotContain(result.Matches, match => match.TermId == "term-1");
    }

    [Fact]
    public void Next_navigation_wraps_for_the_selected_term()
    {
        var matches = new[]
        {
            new WordHighlightMatch("a", 0, 1, "#FFFFFF"),
            new WordHighlightMatch("b", 2, 1, "#FFFFFF"),
            new WordHighlightMatch("a", 4, 1, "#FFFFFF"),
        };

        Assert.Equal(0, WordHighlighterNavigator.Move(matches, "a", -1));
        Assert.Equal(2, WordHighlighterNavigator.Move(matches, "a", 0));
        Assert.Equal(0, WordHighlighterNavigator.Move(matches, "a", 2));
        Assert.Equal(-1, WordHighlighterNavigator.Move(matches, "missing", -1));
    }

    private static ReaderHighlighterTerm Term(
        string value,
        int ordinal,
        string color,
        bool active = true) => new(
            $"term-{ordinal}",
            value,
            value.ToLowerInvariant(),
            active,
            color,
            ordinal,
            DateTimeOffset.Parse("2026-08-18T12:00:00Z"),
            DateTimeOffset.Parse("2026-08-18T12:00:00Z"));
}
