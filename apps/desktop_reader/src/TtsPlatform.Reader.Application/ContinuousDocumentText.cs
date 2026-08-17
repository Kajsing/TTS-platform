using System.Text;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record ContinuousBlockEdit(ReaderBlock Block, string ReplacementText);

public sealed class ContinuousDocumentText
{
    public const string BlockSeparator = "\r\n\r\n";

    private readonly IReadOnlyList<BlockSpan> _spans;

    public ContinuousDocumentText(IReadOnlyList<ReaderBlock> blocks)
    {
        ArgumentNullException.ThrowIfNull(blocks);
        Blocks = blocks.ToArray();

        var text = new StringBuilder();
        var spans = new List<BlockSpan>(Blocks.Count);
        foreach (var block in Blocks)
        {
            if (text.Length > 0)
            {
                text.Append(BlockSeparator);
            }
            spans.Add(new BlockSpan(block, text.Length, block.Text.Length));
            text.Append(block.Text);
        }
        Text = text.ToString();
        _spans = spans;
    }

    public IReadOnlyList<ReaderBlock> Blocks { get; }
    public string Text { get; }

    public ReaderCursor CursorAt(string documentId, int contentRevision, int characterOffset)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        if (_spans.Count == 0)
        {
            throw new InvalidOperationException("An empty document does not have a playback cursor.");
        }

        var offset = Math.Clamp(characterOffset, 0, Text.Length);
        for (var index = 0; index < _spans.Count; index++)
        {
            var span = _spans[index];
            if (offset <= span.End)
            {
                return ToCursor(documentId, contentRevision, span, offset - span.Start);
            }
            if (index + 1 < _spans.Count && offset < _spans[index + 1].Start)
            {
                var next = _spans[index + 1];
                return ToCursor(documentId, contentRevision, next, 0);
            }
        }

        var last = _spans[^1];
        return ToCursor(documentId, contentRevision, last, last.Length);
    }

    public bool TryGetCharacterOffset(ReaderCursor cursor, out int characterOffset)
    {
        ArgumentNullException.ThrowIfNull(cursor);
        var span = _spans.FirstOrDefault(candidate =>
            string.Equals(candidate.Block.Id, cursor.BlockId, StringComparison.Ordinal) &&
            string.Equals(candidate.Block.DocumentId, cursor.DocumentId, StringComparison.Ordinal));
        if (span is null)
        {
            characterOffset = 0;
            return false;
        }

        characterOffset = span.Start + Math.Clamp(cursor.CharacterOffset, 0, span.Length);
        return true;
    }

    public bool TryMapSingleBlockEdit(string editedText, out ContinuousBlockEdit? edit)
    {
        ArgumentNullException.ThrowIfNull(editedText);
        edit = null;
        if (string.Equals(editedText, Text, StringComparison.Ordinal))
        {
            return false;
        }

        var prefixLength = CommonPrefixLength(Text, editedText);
        var suffixLength = CommonSuffixLength(Text, editedText, prefixLength);
        var originalEnd = Text.Length - suffixLength;
        var editedEnd = editedText.Length - suffixLength;
        var span = _spans.FirstOrDefault(candidate =>
            prefixLength >= candidate.Start &&
            prefixLength <= candidate.End &&
            originalEnd >= candidate.Start &&
            originalEnd <= candidate.End);
        if (span is null)
        {
            return false;
        }

        var localStart = prefixLength - span.Start;
        var localEnd = originalEnd - span.Start;
        var replacement = string.Concat(
            span.Block.Text.AsSpan(0, localStart),
            editedText.AsSpan(prefixLength, editedEnd - prefixLength),
            span.Block.Text.AsSpan(localEnd));
        edit = new ContinuousBlockEdit(span.Block, replacement);
        return true;
    }

    public ContinuousDocumentText ReplaceBlock(ReaderBlock replacement)
    {
        ArgumentNullException.ThrowIfNull(replacement);
        var found = false;
        var blocks = Blocks.Select(block =>
        {
            if (!string.Equals(block.Id, replacement.Id, StringComparison.Ordinal))
            {
                return block;
            }
            found = true;
            return replacement;
        }).ToArray();
        if (!found)
        {
            throw new ArgumentException("The replacement block is not part of this document.", nameof(replacement));
        }
        return new ContinuousDocumentText(blocks);
    }

    private static ReaderCursor ToCursor(
        string documentId,
        int contentRevision,
        BlockSpan span,
        int characterOffset) => new(
            documentId,
            span.Block.Id,
            span.Block.Ordinal,
            Math.Clamp(characterOffset, 0, span.Length),
            contentRevision);

    private static int CommonPrefixLength(string left, string right)
    {
        var limit = Math.Min(left.Length, right.Length);
        var index = 0;
        while (index < limit && left[index] == right[index])
        {
            index++;
        }
        return index;
    }

    private static int CommonSuffixLength(string left, string right, int prefixLength)
    {
        var limit = Math.Min(left.Length, right.Length) - prefixLength;
        var count = 0;
        while (count < limit && left[^(count + 1)] == right[^(count + 1)])
        {
            count++;
        }
        return count;
    }

    private sealed record BlockSpan(ReaderBlock Block, int Start, int Length)
    {
        public int End => Start + Length;
    }
}
