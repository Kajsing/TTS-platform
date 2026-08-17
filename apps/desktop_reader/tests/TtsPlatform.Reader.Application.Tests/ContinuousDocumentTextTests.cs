using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ContinuousDocumentTextTests
{
    [Fact]
    public void Joins_blocks_without_exposing_editor_boundaries()
    {
        var document = new ContinuousDocumentText([
            Block("first", 0),
            Block("second", 1),
            Block("third", 2),
        ]);

        Assert.Equal("first\r\n\r\nsecond\r\n\r\nthird", document.Text);
    }

    [Fact]
    public void Maps_document_caret_to_block_utf16_offset()
    {
        var document = new ContinuousDocumentText([
            Block("first", 0),
            Block("second", 1),
        ]);

        var withinSecond = document.CursorAt("doc", 7, document.Text.IndexOf("cond", StringComparison.Ordinal));
        var betweenBlocks = document.CursorAt("doc", 7, "first\r".Length);

        Assert.Equal("block-1", withinSecond.BlockId);
        Assert.Equal(2, withinSecond.CharacterOffset);
        Assert.Equal("block-1", betweenBlocks.BlockId);
        Assert.Equal(0, betweenBlocks.CharacterOffset);
        Assert.Equal(7, withinSecond.ContentRevision);
    }

    [Fact]
    public void Maps_playback_cursor_back_to_document_caret()
    {
        var document = new ContinuousDocumentText([
            Block("first", 0),
            Block("second", 1),
        ]);
        var cursor = new ReaderCursor("doc", "block-1", 1, 3, 7, null);

        var mapped = document.TryGetCharacterOffset(cursor, out var characterOffset);

        Assert.True(mapped);
        Assert.Equal(document.Text.IndexOf("ond", StringComparison.Ordinal), characterOffset);
    }

    [Fact]
    public void Rejects_playback_cursor_from_another_document()
    {
        var document = new ContinuousDocumentText([Block("first", 0)]);
        var cursor = new ReaderCursor("other", "block-0", 0, 2, 1, null);

        var mapped = document.TryGetCharacterOffset(cursor, out var characterOffset);

        Assert.False(mapped);
        Assert.Equal(0, characterOffset);
    }

    [Fact]
    public void Maps_an_edit_inside_one_block_back_to_that_block()
    {
        var document = new ContinuousDocumentText([
            Block("first", 0),
            Block("second", 1),
        ]);

        var mapped = document.TryMapSingleBlockEdit(
            "first\r\n\r\nsecXYond",
            out var edit);

        Assert.True(mapped);
        Assert.NotNull(edit);
        Assert.Equal("block-1", edit.Block.Id);
        Assert.Equal("secXYond", edit.ReplacementText);
    }

    [Fact]
    public void Rejects_an_edit_that_crosses_a_block_separator()
    {
        var document = new ContinuousDocumentText([
            Block("first", 0),
            Block("second", 1),
        ]);

        var mapped = document.TryMapSingleBlockEdit("first and second", out var edit);

        Assert.False(mapped);
        Assert.Null(edit);
    }

    [Fact]
    public void Maps_and_applies_a_deletion_across_hidden_block_boundaries()
    {
        var document = new ContinuousDocumentText([
            Block("first", 0),
            Block("second", 1),
            Block("third", 2),
            Block("fourth", 3),
        ]);
        var start = document.Text.IndexOf("rst", StringComparison.Ordinal);
        var end = document.Text.IndexOf("ird", StringComparison.Ordinal);
        var editedText = document.Text.Remove(start, end - start);

        var mapped = document.TryMapCrossBlockDeletion(editedText, out var deletion);
        var changed = document.ApplyRangeDeletion(deletion!);

        Assert.True(mapped);
        Assert.NotNull(deletion);
        Assert.Equal("block-0", deletion.StartBlock.Id);
        Assert.Equal(2, deletion.StartOffset);
        Assert.Equal("block-2", deletion.EndBlock.Id);
        Assert.Equal(2, deletion.EndOffset);
        Assert.Equal("fiird", deletion.ResultingStartBlockText);
        Assert.Equal(["fiird", "fourth"], changed.Blocks.Select(block => block.Text));
        Assert.Equal([0, 1], changed.Blocks.Select(block => block.Ordinal));
        Assert.Equal("fiird\r\n\r\nfourth", changed.Text);
    }

    private static ReaderBlock Block(string text, int ordinal) => new(
        $"block-{ordinal}",
        "doc",
        null,
        ordinal,
        "paragraph",
        text,
        text.Length,
        "hash",
        1,
        JsonDocument.Parse("{}").RootElement.Clone());
}
