namespace TtsPlatform.Reader.Client;

public sealed record ReaderChapterAnchor(string Id, string Title, string BlockId,
    int BlockOrdinal, int CodepointOffset)
{
    public override string ToString() => Title;
}

public sealed record ReaderChapterIndex(string DocumentId, int ContentRevision,
    IReadOnlyList<ReaderChapterAnchor> Chapters);
