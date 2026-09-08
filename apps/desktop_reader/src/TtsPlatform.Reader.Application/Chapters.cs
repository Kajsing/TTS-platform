using System.Text.Json;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record ReaderChapter(string Id, string Title, int Start, int End)
{
    public override string ToString() => Title;
    public ChapterSlice Slice => new(Start, End);
}

public readonly record struct ChapterSlice(int Start, int End)
{
    public int Length => End - Start;
    public string Text(string fullText) => fullText[Start..End];
    public string Expand(string visibleText, string originalFullText) =>
        string.Concat(originalFullText.AsSpan(0, Start), visibleText, originalFullText.AsSpan(End));
    public (int Start, int Length) Clip(int start, int length)
    {
        var first = Math.Max(Start, start);
        var last = Math.Min(End, start + length);
        return last > first ? (first - Start, last - first) : (-1, 0);
    }
}

public static class ReaderChapters
{
    public static IReadOnlyList<ReaderChapter> Build(ReaderDocument document, ContinuousDocumentText text)
    {
        IReadOnlyList<ReaderChapter> fallback = [new("root", "Chapter 1", 0, text.Text.Length)];
        if (document.Metadata.ValueKind != JsonValueKind.Object ||
            !document.Metadata.TryGetProperty("chapter_markers_v1", out var array)) return fallback;
        try
        {
            if (array.ValueKind != JsonValueKind.Array || array.GetArrayLength() is < 1 or > 1024) return fallback;
            var blocks = text.Blocks.ToDictionary(block => block.Id);
            var starts = new List<(string Id, string Title, int Offset)>();
            foreach (var item in array.EnumerateArray())
            {
                var id = item.GetProperty("id").GetString();
                var title = item.GetProperty("title").GetString();
                var blockId = item.GetProperty("block_id").GetString();
                var codepoints = item.GetProperty("codepoint_offset").GetInt32();
                if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(title) ||
                    blockId is null || !blocks.TryGetValue(blockId, out var block)) return fallback;
                var offset = Utf16Offset(block.Text, codepoints);
                if (offset < 0 || !text.TryGetCharacterOffset(new ReaderCursor(document.Id, block.Id,
                    block.Ordinal, offset, document.ContentRevision), out var global)) return fallback;
                starts.Add((id, title, global));
            }
            if (starts[0].Offset != 0 || starts.Select(item => item.Id).Distinct().Count() != starts.Count ||
                starts.Zip(starts.Skip(1)).Any(pair => pair.First.Offset >= pair.Second.Offset)) return fallback;
            return starts.Select((item, index) => new ReaderChapter(item.Id, item.Title, item.Offset,
                index + 1 < starts.Count ? starts[index + 1].Offset : text.Text.Length)).ToArray();
        }
        catch (Exception error) when (error is KeyNotFoundException or InvalidOperationException or FormatException or OverflowException)
        { return fallback; }
    }

    public static ReaderChapter At(IReadOnlyList<ReaderChapter> chapters, int offset) =>
        chapters.LastOrDefault(chapter => chapter.Start <= offset) ?? chapters[0];

    private static int Utf16Offset(string text, int codepoints)
    {
        if (codepoints < 0) return -1;
        var offset = 0;
        for (var count = 0; count < codepoints; count++)
        {
            if (offset >= text.Length) return -1;
            offset += char.IsSurrogatePair(text, offset) ? 2 : 1;
        }
        return offset;
    }
}
