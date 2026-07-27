using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ClipboardCaptureTests
{
    [Fact]
    public async Task Repeated_appends_are_individual_operations_with_current_row_versions()
    {
        var client = new CaptureClient();
        var capture = new ClipboardDocumentCapture(client);
        var document = Document(rowVersion: 1);

        foreach (var text in new[] { "First selection", "Second selection", "Third selection" })
        {
            var result = await capture.AppendAsync(text, document);
            Assert.True(result.Succeeded);
            document = result.Document!;
        }

        Assert.Equal(["First selection", "Second selection", "Third selection"], client.AppendedText);
        Assert.Equal([1, 2, 3], client.AppendRowVersions);
    }

    [Fact]
    public async Task Locked_append_returns_a_pause_or_stop_action()
    {
        var client = new CaptureClient { AppendLocked = true };
        var capture = new ClipboardDocumentCapture(client);

        var result = await capture.AppendAsync("Private text", Document(1));

        Assert.False(result.Succeeded);
        Assert.Contains("Pause or stop", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Create_uses_editable_clipboard_source_and_only_opens_when_requested()
    {
        var client = new CaptureClient();
        var capture = new ClipboardDocumentCapture(client);

        var create = await capture.CreateAsync("Saved text", openDocument: true);
        var inbox = await capture.CreateAsync("Inbox text", openDocument: false);

        Assert.True(create.OpenDocument);
        Assert.False(inbox.OpenDocument);
        Assert.All(client.Created, request => Assert.Equal("clipboard", request.SourceType));
        Assert.All(client.Created, request => Assert.False(request.AllowDuplicate));
    }

    [Fact]
    public async Task Duplicate_create_returns_existing_id_and_requires_explicit_retry()
    {
        var client = new CaptureClient { DuplicateDocumentId = "existing-doc" };
        var capture = new ClipboardDocumentCapture(client);

        var duplicate = await capture.CreateAsync("Saved text", openDocument: true);

        Assert.False(duplicate.Succeeded);
        Assert.Equal("existing-doc", duplicate.DuplicateDocumentId);
        Assert.Single(client.Created);
        Assert.False(client.Created[0].AllowDuplicate);

        var created = await capture.CreateAsync(
            "Saved text",
            openDocument: true,
            allowDuplicate: true);

        Assert.True(created.Succeeded);
        Assert.Equal(2, client.Created.Count);
        Assert.True(client.Created[1].AllowDuplicate);
    }

    [Fact]
    public async Task Duplicate_document_can_be_opened_without_creating_another_copy()
    {
        var client = new CaptureClient();
        var capture = new ClipboardDocumentCapture(client);

        var result = await capture.OpenExistingAsync("existing-doc");

        Assert.True(result.Succeeded);
        Assert.True(result.OpenDocument);
        Assert.Equal("existing-doc", result.Document?.Id);
        Assert.Equal(["existing-doc"], client.OpenedDocumentIds);
        Assert.Empty(client.Created);
    }

    [Fact]
    public void Ephemeral_chunker_is_bounded_and_does_not_persist_text()
    {
        var text = string.Join(' ', Enumerable.Repeat("selection", 1_200));

        var chunks = EphemeralTextChunker.Chunk(text);

        Assert.True(chunks.Count > 1);
        Assert.All(chunks, chunk => Assert.InRange(chunk.Length, 1, 4_000));
        Assert.Equal(text, string.Join(' ', chunks));
        Assert.Empty(EphemeralTextChunker.Chunk("   "));
    }

    private static ReaderDocument Document(int rowVersion, string id = "doc") => new(
        id,
        "Document",
        "plain_text",
        null,
        null,
        null,
        null,
        "inbox",
        DateTimeOffset.Parse("2026-07-27T12:00:00Z"),
        DateTimeOffset.Parse("2026-07-27T12:00:00Z"),
        DateTimeOffset.Parse("2026-07-27T12:00:00Z"),
        null,
        1,
        rowVersion,
        1,
        rowVersion,
        10,
        JsonDocument.Parse("{}").RootElement.Clone());

    private sealed class CaptureClient : IReaderServiceClient
    {
        public bool AppendLocked { get; init; }
        public string? DuplicateDocumentId { get; init; }
        public List<string> AppendedText { get; } = [];
        public List<int> AppendRowVersions { get; } = [];
        public List<CreateDocumentRequest> Created { get; } = [];
        public List<string> OpenedDocumentIds { get; } = [];

        public Task<ReaderDocument> CreateDocumentAsync(
            CreateDocumentRequest request,
            CancellationToken cancellationToken = default)
        {
            Created.Add(request);
            if (!request.AllowDuplicate && DuplicateDocumentId is not null)
            {
                return Task.FromException<ReaderDocument>(
                    new ReaderApiException(
                        "reader_duplicate_document",
                        "duplicate",
                        409,
                        details: new Dictionary<string, object?>
                        {
                            ["document_id"] = DuplicateDocumentId,
                        }));
            }
            return Task.FromResult(Document(Created.Count));
        }

        public Task<ReaderDocument> GetDocumentAsync(
            string documentId,
            CancellationToken cancellationToken = default)
        {
            OpenedDocumentIds.Add(documentId);
            return Task.FromResult(Document(1, documentId));
        }

        public Task<MutationResponse> AppendContentAsync(
            string documentId,
            AppendContentRequest request,
            CancellationToken cancellationToken = default)
        {
            if (AppendLocked)
            {
                return Task.FromException<MutationResponse>(
                    new ReaderApiException("reader_document_locked", "locked", 409));
            }
            AppendedText.Add(request.Text);
            AppendRowVersions.Add(request.ExpectedRowVersion);
            return Task.FromResult(new MutationResponse(
                Document(request.ExpectedRowVersion + 1),
                null));
        }

        public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderCapabilities> GetCapabilitiesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DocumentPage> GetDocumentsAsync(int limit = 50, string? cursor = null, string? query = null, string? state = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<BlockPage> GetBlocksAsync(string documentId, int afterOrdinal = -1, int limit = 200, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> ReplaceContentAsync(string documentId, ReplaceContentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> UndoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> RedoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition?> GetPositionAsync(string documentId, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition> SavePositionAsync(string documentId, SavePositionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<byte[]> SynthesizeAsync(EphemeralSynthesisRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}
