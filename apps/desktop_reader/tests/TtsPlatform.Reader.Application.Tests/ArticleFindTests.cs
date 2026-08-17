using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ArticleFindTests
{
    [Fact]
    public void Literal_phrase_search_is_case_insensitive_by_default()
    {
        var result = ArticleFindEngine.Search(
            "First useful phrase. USEFUL PHRASE again.",
            "useful phrase");

        Assert.True(result.Succeeded);
        Assert.Equal([6, 21], result.Matches.Select(match => match.Start));
    }

    [Fact]
    public void Case_and_unicode_whole_word_options_are_deterministic()
    {
        const string text = "Ål ålX ÅL _Ål Ål_ Ål";

        var insensitive = ArticleFindEngine.Search(
            text,
            "ål",
            new ArticleFindOptions(WholeWord: true));
        var sensitive = ArticleFindEngine.Search(
            text,
            "Ål",
            new ArticleFindOptions(CaseSensitive: true, WholeWord: true));

        Assert.Equal([0, 7, 18], insensitive.Matches.Select(match => match.Start));
        Assert.Equal([0, 18], sensitive.Matches.Select(match => match.Start));
    }

    [Fact]
    public void Whole_word_keeps_combining_marks_attached_to_their_word()
    {
        const string text = "a a\u030A a";

        var result = ArticleFindEngine.Search(
            text,
            "a",
            new ArticleFindOptions(WholeWord: true));

        Assert.Equal([0, 5], result.Matches.Select(match => match.Start));
    }

    [Fact]
    public void Regex_search_supports_multiline_and_reports_invalid_patterns()
    {
        var valid = ArticleFindEngine.Search(
            "Chapter 1\nbody\nChapter 22",
            "^chapter\\s+\\d+$",
            new ArticleFindOptions(UseRegex: true));
        var invalid = ArticleFindEngine.Search(
            "text",
            "(",
            new ArticleFindOptions(UseRegex: true));

        Assert.Equal([0, 15], valid.Matches.Select(match => match.Start));
        Assert.Equal(ArticleFindFailure.InvalidRegex, invalid.Failure);
    }

    [Fact]
    public void Pathological_regex_times_out_without_throwing()
    {
        var result = ArticleFindEngine.Search(
            $"{new string('a', 200_000)}!",
            "^(a+)+$",
            new ArticleFindOptions(UseRegex: true, RegexTimeoutMilliseconds: 1));

        Assert.Equal(ArticleFindFailure.RegexTimedOut, result.Failure);
    }

    [Fact]
    public void Result_count_is_bounded_and_reports_truncation()
    {
        var result = ArticleFindEngine.Search(
            "one one one one",
            "one",
            new ArticleFindOptions(MaxResults: 3));

        Assert.Equal(3, result.Matches.Count);
        Assert.True(result.Truncated);
    }

    [Fact]
    public void Match_spanning_blocks_maps_back_to_both_reader_cursors()
    {
        var document = Document(totalBlocks: 2, totalCharacters: 9);
        var findDocument = new ArticleFindDocument(
            document,
            [Block("one", 0), Block("two", 1)]);
        var result = ArticleFindEngine.Search(
            findDocument.Text,
            $"one{ContinuousDocumentText.BlockSeparator}two");

        var location = findDocument.Locate(Assert.Single(result.Matches));

        Assert.Equal("block-0", location.StartCursor.BlockId);
        Assert.Equal(0, location.StartCursor.CharacterOffset);
        Assert.Equal("block-1", location.EndCursor.BlockId);
        Assert.Equal(3, location.EndCursor.CharacterOffset);
    }

    [Theory]
    [InlineData(0, 3, 1, 1)]
    [InlineData(2, 3, 1, 0)]
    [InlineData(0, 3, -1, 2)]
    [InlineData(-1, 3, 1, 0)]
    [InlineData(-1, 3, -1, 2)]
    [InlineData(0, 0, 1, -1)]
    public void Navigator_wraps_predictably(
        int current,
        int count,
        int delta,
        int expected) =>
        Assert.Equal(expected, ArticleFindNavigator.Move(current, count, delta));

    private static ReaderDocument Document(int totalBlocks, int totalCharacters) => new(
        "doc",
        "Article",
        "html",
        null,
        null,
        null,
        null,
        "inbox",
        DateTimeOffset.Parse("2026-08-17T12:00:00Z"),
        DateTimeOffset.Parse("2026-08-17T12:00:00Z"),
        DateTimeOffset.Parse("2026-08-17T12:00:00Z"),
        null,
        4,
        2,
        0,
        totalBlocks,
        totalCharacters,
        EmptyMetadata());

    private static ReaderBlock Block(string text, int ordinal) => new(
        $"block-{ordinal}",
        "doc",
        null,
        ordinal,
        "paragraph",
        text,
        text.Length,
        $"hash-{ordinal}",
        1,
        EmptyMetadata());

    private static JsonElement EmptyMetadata() => JsonDocument.Parse("{}").RootElement.Clone();
}
