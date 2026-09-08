using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ChapterTests
{
    [Fact]
    public void Chapter_slice_is_a_projection_and_edits_preserve_hidden_text()
    {
        var whole = "Before 😀 middle after";
        var slice = new ChapterSlice(10, 16);
        Assert.Equal("middle", slice.Text(whole));
        Assert.Equal("Before 😀 revised after", slice.Expand("revised", whole));
        Assert.Equal((0, 3), slice.Clip(8, 5));
        Assert.Equal((-1, 0), slice.Clip(0, 3));
        Assert.Equal((0, 6), slice.Clip(0, whole.Length));
    }

    [Fact]
    public void Metadata_codepoint_boundaries_become_utf16_cursor_offsets_without_splitting_text()
    {
        var metadata = JsonSerializer.SerializeToElement(new
        {
            chapter_markers_v1 = new[] {
            new { id = "root", title = "First", block_id = "b", codepoint_offset = 0 },
            new { id = "two", title = "Second", block_id = "b", codepoint_offset = 2 } }
        });
        var doc = Document(metadata);
        var block = new ReaderBlock("b", "doc", null, 0, "paragraph", "A😀BCD", 5, "hash", 1, metadata);
        var text = new ContinuousDocumentText([block]);
        var chapters = ReaderChapters.Build(doc, text);
        Assert.Equal(2, chapters.Count);
        Assert.Equal(3, chapters[1].Start);
        Assert.Equal("A😀", chapters[0].Slice.Text(text.Text));
        Assert.Equal("BCD", chapters[1].Slice.Text(text.Text));
        Assert.Equal("two", ReaderChapters.At(chapters, 3).Id);
        Assert.Equal("two", ReaderChapters.At(chapters, text.Text.Length).Id);
    }

    [Fact]
    public void Legacy_or_invalid_metadata_falls_back_to_one_chapter()
    {
        foreach (var metadata in new[] { JsonSerializer.SerializeToElement(new { }),
            JsonSerializer.SerializeToElement(new { chapter_markers_v1 = "invalid" }) })
        {
            var text = new ContinuousDocumentText([new ReaderBlock("b", "doc", null, 0, "paragraph", "Text", 4, "hash", 1, metadata)]);
            var chapter = Assert.Single(ReaderChapters.Build(Document(metadata), text));
            Assert.Equal("Text", chapter.Slice.Text(text.Text));
        }
    }

    private static ReaderDocument Document(JsonElement metadata) => new("doc", "Synthetic", "clipboard",
        null, null, null, null, "inbox", DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch,
        DateTimeOffset.UnixEpoch, null, 1, 1, 1, 1, 5, metadata);
}
