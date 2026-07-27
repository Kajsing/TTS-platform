using System.Net;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ApplicationTests
{
    [Fact]
    public async Task Onboarding_reports_service_unavailable_as_actionable()
    {
        var client = new StubClient
        {
            HealthException = new ReaderServiceUnavailableException("Start the service."),
        };

        var result = await new OnboardingCoordinator(client).CheckAsync();

        Assert.Equal(ConnectionState.ServiceUnavailable, result.State);
        Assert.Equal(SuggestedAction.StartService, result.Action);
    }

    [Fact]
    public async Task Onboarding_reports_missing_token_as_actionable()
    {
        var client = new StubClient
        {
            Health = Healthy(),
            CapabilitiesException = new ReaderTokenUnavailableException("Choose token."),
        };

        var result = await new OnboardingCoordinator(client).CheckAsync();

        Assert.Equal(ConnectionState.TokenMissing, result.State);
        Assert.Equal(SuggestedAction.ChooseTokenFile, result.Action);
    }

    [Fact]
    public async Task Onboarding_distinguishes_backend_degraded_from_reader_storage()
    {
        var client = new StubClient
        {
            Health = Healthy(backendReady: false),
            Capabilities = Capabilities(),
            Voices = new VoicePage([], null),
        };

        var result = await new OnboardingCoordinator(client).CheckAsync();

        Assert.Equal(ConnectionState.BackendDegraded, result.State);
        Assert.Equal(SuggestedAction.CheckVoiceModels, result.Action);
    }

    [Fact]
    public async Task Onboarding_reports_reader_disabled_before_requesting_a_token()
    {
        var health = Healthy() with { Reader = new ReaderHealth(false, false, 0, null) };
        var client = new StubClient
        {
            Health = health,
            CapabilitiesException = new ReaderTokenUnavailableException("Should not be reached."),
        };

        var result = await new OnboardingCoordinator(client).CheckAsync();

        Assert.Equal(ConnectionState.ReaderDisabled, result.State);
        Assert.Equal(SuggestedAction.EnableReader, result.Action);
    }

    [Fact]
    public async Task Onboarding_reports_rejected_token_without_exposing_service_details()
    {
        var client = new StubClient
        {
            Health = Healthy(),
            CapabilitiesException = new ReaderApiException("unauthorized", "secret detail", 401),
        };

        var result = await new OnboardingCoordinator(client).CheckAsync();

        Assert.Equal(ConnectionState.TokenInvalid, result.State);
        Assert.Equal(SuggestedAction.ChooseTokenFile, result.Action);
        Assert.DoesNotContain("secret detail", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Library_uses_opaque_next_cursor_for_paging()
    {
        var client = new StubClient
        {
            DocumentPages = new Queue<DocumentPage>(
            [
                new DocumentPage([Document("one", 1)], "opaque cursor/+"),
                new DocumentPage([Document("two", 1)], null),
            ]),
        };
        var pager = new LibraryPager(client, 1);

        await pager.RefreshAsync("title words");
        await pager.LoadMoreAsync();

        Assert.Equal(["one", "two"], pager.Documents.Select(item => item.Id));
        Assert.Equal([null, "opaque cursor/+"], client.ReceivedCursors);
        Assert.False(pager.HasMore);
    }

    [Fact]
    public async Task Editor_preserves_unsaved_text_when_row_version_conflicts()
    {
        var client = new StubClient
        {
            Blocks = new BlockPage([Block("old text")], null),
            ReplaceException = new ReaderApiException(
                "reader_revision_conflict",
                "changed",
                (int)HttpStatusCode.Conflict),
        };
        var editor = new DocumentEditor(client);
        await editor.LoadAsync(Document("doc", 4));
        editor.SetWorkingText("my carefully edited text");

        var result = await editor.SaveAsync();

        Assert.True(result.Conflict);
        Assert.Equal("my carefully edited text", editor.WorkingText);
        Assert.Equal("old text", editor.OriginalText);
        Assert.Equal(4, client.LastReplaceRequest?.ExpectedRowVersion);
    }

    [Fact]
    public async Task Structured_document_is_read_only()
    {
        var client = new StubClient { Blocks = new BlockPage([Block("book")], null) };
        var editor = new DocumentEditor(client);
        await editor.LoadAsync(Document("book", 2, "epub"));

        editor.SetWorkingText("changed");
        var result = await editor.SaveAsync();

        Assert.False(editor.IsEditable);
        Assert.False(result.Saved);
        Assert.Equal("book", editor.WorkingText);
        Assert.Null(client.LastReplaceRequest);
    }

    private static HealthResponse Healthy(bool backendReady = true) => new(
        "ok",
        "0.1",
        new Dictionary<string, bool>
        {
            ["backend_ready"] = backendReady,
            ["default_voice_loaded"] = backendReady,
        },
        null,
        true,
        new ReaderHealth(true, true, 1, null));

    private static ReaderCapabilities Capabilities() => new(
        1,
        true,
        new ReaderDatabaseCapability(true, 1, false),
        new ReaderPlaybackCapability(0, "utf-16", 64, 32000));

    private static ReaderDocument Document(string id, int rowVersion, string sourceType = "plain_text") => new(
        id,
        id,
        sourceType,
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
        1,
        8,
        EmptyMetadata());

    private static ReaderBlock Block(string text) => new(
        "block",
        "doc",
        null,
        0,
        "paragraph",
        text,
        text.Length,
        "hash",
        1,
        EmptyMetadata());

    private static JsonElement EmptyMetadata() => JsonDocument.Parse("{}").RootElement.Clone();

    private sealed class StubClient : IReaderServiceClient
    {
        public HealthResponse Health { get; init; } = Healthy();
        public Exception? HealthException { get; init; }
        public ReaderCapabilities Capabilities { get; init; } = ApplicationTests.Capabilities();
        public VoicePage Voices { get; init; } = new(
            [new VoiceDescriptor("voice", "Voice", "test", "en", 22050, "test", "test", null, "test", "test")],
            "voice");
        public Exception? CapabilitiesException { get; init; }
        public Queue<DocumentPage> DocumentPages { get; init; } = new();
        public BlockPage Blocks { get; init; } = new([], null);
        public ReaderApiException? ReplaceException { get; init; }
        public ReplaceContentRequest? LastReplaceRequest { get; private set; }
        public List<string?> ReceivedCursors { get; } = [];

        public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) =>
            HealthException is null
                ? Task.FromResult(Health)
                : Task.FromException<HealthResponse>(HealthException);

        public Task<ReaderCapabilities> GetCapabilitiesAsync(CancellationToken cancellationToken = default) =>
            CapabilitiesException is null
                ? Task.FromResult(Capabilities)
                : Task.FromException<ReaderCapabilities>(CapabilitiesException);

        public Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(Voices);

        public Task<ReaderDocument> CreateDocumentAsync(
            CreateDocumentRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<DocumentPage> GetDocumentsAsync(
            int limit = 50,
            string? cursor = null,
            string? query = null,
            string? state = null,
            CancellationToken cancellationToken = default)
        {
            ReceivedCursors.Add(cursor);
            return Task.FromResult(DocumentPages.Dequeue());
        }

        public Task<BlockPage> GetBlocksAsync(
            string documentId,
            int afterOrdinal = -1,
            int limit = 200,
            CancellationToken cancellationToken = default) => Task.FromResult(Blocks);

        public Task<MutationResponse> ReplaceContentAsync(
            string documentId,
            ReplaceContentRequest request,
            CancellationToken cancellationToken = default)
        {
            LastReplaceRequest = request;
            return ReplaceException is null
                ? Task.FromResult(new MutationResponse(Document(documentId, request.ExpectedRowVersion + 1), null))
                : Task.FromException<MutationResponse>(ReplaceException);
        }

        public Task<MutationResponse> AppendContentAsync(
            string documentId,
            AppendContentRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<MutationResponse> UndoAsync(
            string documentId,
            ExpectedVersionRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<MutationResponse> RedoAsync(
            string documentId,
            ExpectedVersionRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<ReaderPosition?> GetPositionAsync(
            string documentId,
            CancellationToken cancellationToken = default) => Task.FromResult<ReaderPosition?>(null);

        public Task<ReaderPosition> SavePositionAsync(
            string documentId,
            SavePositionRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<byte[]> SynthesizeAsync(
            EphemeralSynthesisRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}
