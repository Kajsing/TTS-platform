using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ReaderDocumentVersionsTests
{
    [Fact]
    public void External_playback_refresh_preserves_edits_and_newer_selections_during_await()
    {
        var requested = Document("doc", rowVersion: 4, contentRevision: 3);
        Assert.True(ReaderDocumentVersions.CanApplyPlaybackRefresh(requested, requested, false));
        Assert.False(ReaderDocumentVersions.CanApplyPlaybackRefresh(requested, requested, true));
        Assert.False(ReaderDocumentVersions.CanApplyPlaybackRefresh(null, requested, false));
        Assert.False(ReaderDocumentVersions.CanApplyPlaybackRefresh(requested with { Id = "other" }, requested, false));
        Assert.False(ReaderDocumentVersions.CanApplyPlaybackRefresh(requested with { RowVersion = 5 }, requested, false));
    }

    [Fact]
    public void Same_version_requires_matching_document_and_both_versions()
    {
        var document = Document("doc", rowVersion: 4, contentRevision: 3);

        Assert.True(ReaderDocumentVersions.AreSame(document, document with { Title = "Renamed" }));
        Assert.False(ReaderDocumentVersions.AreSame(document, document with { RowVersion = 5 }));
        Assert.False(ReaderDocumentVersions.AreSame(document, document with { ContentRevision = 4 }));
        Assert.False(ReaderDocumentVersions.AreSame(document, document with { Id = "other" }));
    }

    [Fact]
    public void Newer_row_version_wins_for_the_same_document()
    {
        var current = Document("doc", rowVersion: 3, contentRevision: 3);
        var candidate = Document("doc", rowVersion: 4, contentRevision: 4);

        Assert.Same(candidate, ReaderDocumentVersions.PreferNewest(current, candidate));
        Assert.Same(candidate, ReaderDocumentVersions.PreferNewest(candidate, current));
    }

    [Fact]
    public void Content_revision_breaks_equal_row_version_ties()
    {
        var current = Document("doc", rowVersion: 4, contentRevision: 3);
        var candidate = Document("doc", rowVersion: 4, contentRevision: 4);

        Assert.Same(candidate, ReaderDocumentVersions.PreferNewest(current, candidate));
    }

    [Fact]
    public void Candidate_wins_when_selecting_a_different_document()
    {
        var current = Document("first", rowVersion: 9, contentRevision: 9);
        var candidate = Document("second", rowVersion: 1, contentRevision: 1);

        Assert.Same(candidate, ReaderDocumentVersions.PreferNewest(current, candidate));
    }

    private static ReaderDocument Document(
        string id,
        int rowVersion,
        int contentRevision) => new(
            id,
            "Title",
            "clipboard",
            null,
            null,
            null,
            null,
            "inbox",
            DateTimeOffset.UnixEpoch,
            DateTimeOffset.UnixEpoch,
            DateTimeOffset.UnixEpoch,
            null,
            contentRevision,
            rowVersion,
            1,
            1,
            10,
            JsonDocument.Parse("{}").RootElement.Clone());
}
