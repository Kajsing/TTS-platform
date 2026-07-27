using System.Text.Json;
using System.Text.Json.Serialization;

namespace TtsPlatform.Reader.Client;

public interface ITokenProvider
{
    ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default);
}

public interface IReaderServiceClient
{
    Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default);
    Task<ReaderCapabilities> GetCapabilitiesAsync(CancellationToken cancellationToken = default);
    Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default);
    Task<ReaderDocument> CreateDocumentAsync(
        CreateDocumentRequest request,
        CancellationToken cancellationToken = default);
    Task<DocumentPage> GetDocumentsAsync(
        int limit = 50,
        string? cursor = null,
        string? query = null,
        string? state = null,
        CancellationToken cancellationToken = default);
    Task<BlockPage> GetBlocksAsync(
        string documentId,
        int afterOrdinal = -1,
        int limit = 200,
        CancellationToken cancellationToken = default);
    Task<MutationResponse> ReplaceContentAsync(
        string documentId,
        ReplaceContentRequest request,
        CancellationToken cancellationToken = default);
    Task<MutationResponse> AppendContentAsync(
        string documentId,
        AppendContentRequest request,
        CancellationToken cancellationToken = default);
    Task<MutationResponse> UndoAsync(
        string documentId,
        ExpectedVersionRequest request,
        CancellationToken cancellationToken = default);
    Task<MutationResponse> RedoAsync(
        string documentId,
        ExpectedVersionRequest request,
        CancellationToken cancellationToken = default);
    Task<ReaderPosition?> GetPositionAsync(
        string documentId,
        CancellationToken cancellationToken = default);
    Task<ReaderPosition> SavePositionAsync(
        string documentId,
        SavePositionRequest request,
        CancellationToken cancellationToken = default);
    Task<byte[]> SynthesizeAsync(
        EphemeralSynthesisRequest request,
        CancellationToken cancellationToken = default);
}

public interface IReaderStreamClient
{
    Task<IReaderStreamSession> OpenAsync(
        ReaderStreamStartRequest request,
        CancellationToken cancellationToken = default);
}

public interface IReaderStreamSession : IAsyncDisposable
{
    IAsyncEnumerable<ReaderStreamEvent> ReadEventsAsync(
        CancellationToken cancellationToken = default);
    Task CancelAsync(CancellationToken cancellationToken = default);
    Task ReleaseAsync(CancellationToken cancellationToken = default);
}

public sealed record HealthResponse(
    string Status,
    string Version,
    IReadOnlyDictionary<string, bool> Checks,
    string? StartupError,
    bool AuthEnabled,
    ReaderHealth Reader);

public sealed record ReaderHealth(
    bool Enabled,
    bool DatabaseReady,
    int SchemaVersion,
    string? StartupError);

public sealed record ReaderCapabilities(
    int ContractVersion,
    bool Enabled,
    ReaderDatabaseCapability Database,
    ReaderPlaybackCapability Playback);

public sealed record ReaderDatabaseCapability(bool Ready, int SchemaVersion, bool SearchAvailable);

public sealed record ReaderPlaybackCapability(
    int StreamProtocolVersion,
    string SourceOffsetEncoding,
    int MaxBlocksPerWindow,
    int MaxSourceCharsPerWindow);

public sealed record VoicePage(IReadOnlyList<VoiceDescriptor> Voices, string? DefaultVoice);

public sealed record VoiceDescriptor(
    string Id,
    string Name,
    string Engine,
    string Language,
    int SampleRateHz,
    string License,
    string Source,
    string? GenderStyleHint,
    string QualityTier,
    string LatencyTier);

public sealed record DocumentPage(IReadOnlyList<ReaderDocument> Documents, string? NextCursor);

public sealed record CreateDocumentRequest(
    string Title,
    [property: JsonPropertyName("source_type")] string SourceType,
    string Text,
    [property: JsonPropertyName("language_hint")] string? LanguageHint = null,
    [property: JsonPropertyName("allow_duplicate")] bool AllowDuplicate = false);

public sealed record ReaderDocument(
    string Id,
    string Title,
    string SourceType,
    string? SourceName,
    string? SourceUri,
    string? SourceSha256,
    string? LanguageHint,
    string State,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    DateTimeOffset ImportedAt,
    DateTimeOffset? DeletedAt,
    int ContentRevision,
    int RowVersion,
    int TotalSections,
    int TotalBlocks,
    int TotalCharacters,
    JsonElement Metadata)
{
    public bool IsEditable => SourceType is "plain_text" or "clipboard" or "selection" or "text_file";
}

public sealed record BlockPage(IReadOnlyList<ReaderBlock> Blocks, int? NextAfterOrdinal);

public sealed record ReaderBlock(
    string Id,
    string DocumentId,
    string? SectionId,
    int Ordinal,
    string Kind,
    string Text,
    int CharacterCount,
    string ContentSha256,
    int RowVersion,
    JsonElement Metadata);

public sealed record ReplaceContentRequest(
    [property: JsonPropertyName("expected_row_version")] int ExpectedRowVersion,
    [property: JsonPropertyName("block_id")] string BlockId,
    [property: JsonPropertyName("start_offset")] int StartOffset,
    [property: JsonPropertyName("end_offset")] int EndOffset,
    [property: JsonPropertyName("replacement_text")] string ReplacementText);

public sealed record AppendContentRequest(
    [property: JsonPropertyName("expected_row_version")] int ExpectedRowVersion,
    string Text);

public sealed record ExpectedVersionRequest(
    [property: JsonPropertyName("expected_row_version")] int ExpectedRowVersion);

public sealed record MutationResponse(ReaderDocument Document, ReaderEdit? Edit);

public sealed record ReaderEdit(
    string Id,
    string DocumentId,
    int Sequence,
    int BaseContentRevision,
    int ResultContentRevision,
    string BlockId,
    int StartOffset,
    int EndOffset,
    string OperationType,
    DateTimeOffset CreatedAt);

public sealed record ReaderCursor(
    string DocumentId,
    string BlockId,
    int BlockOrdinal,
    int CharacterOffset,
    int ContentRevision,
    int? SegmentIndex = null);

public sealed record ReaderPosition(
    string DocumentId,
    ReaderCursor Cursor,
    string? VoiceProfileId,
    int PipelineVersion,
    int RulesVersion,
    DateTimeOffset UpdatedAt,
    bool Completed,
    int RowVersion);

public sealed record SavePositionRequest(
    ReaderCursor Cursor,
    [property: JsonPropertyName("voice_profile_id")] string? VoiceProfileId = null,
    [property: JsonPropertyName("pipeline_version")] int PipelineVersion = 1,
    [property: JsonPropertyName("rules_version")] int RulesVersion = 1,
    bool Completed = false,
    [property: JsonPropertyName("expected_row_version")] int? ExpectedRowVersion = null);

public sealed record EphemeralSynthesisRequest(
    string Text,
    string? Voice = null,
    string Format = "wav",
    [property: JsonPropertyName("language_hint")] string? LanguageHint = null);

public sealed record ReaderProsody(
    double Rate = 1.0,
    double Volume = 1.0,
    double Pitch = 0.0,
    [property: JsonPropertyName("pause_strategy")] string PauseStrategy = "natural",
    [property: JsonPropertyName("sentence_pause_ms")] int? SentencePauseMs = null,
    [property: JsonPropertyName("comma_pause_ms")] int? CommaPauseMs = null,
    IReadOnlyList<string>? Emphasis = null);

public sealed record ReaderStreamWindow(
    [property: JsonPropertyName("max_blocks")] int MaxBlocks = 32,
    [property: JsonPropertyName("max_source_characters")] int MaxSourceCharacters = 16_000);

public sealed record ReaderStreamStartRequest(
    [property: JsonPropertyName("document_id")] string DocumentId,
    ReaderCursor Cursor,
    string? Voice = null,
    [property: JsonPropertyName("language_hint")] string? LanguageHint = null,
    ReaderProsody? Prosody = null,
    ReaderStreamWindow? Window = null);

public abstract record ReaderStreamEvent(string StreamId);

public sealed record ReaderStreamStarted(
    string StreamId,
    string DocumentId,
    int SampleRateHz,
    int Channels,
    string SampleFormat,
    int PipelineVersion,
    int RulesVersion,
    ReaderCursor Cursor) : ReaderStreamEvent(StreamId);

public sealed record ReaderSourceSpan(
    string BlockId,
    int BlockOrdinal,
    int StartOffset,
    int EndOffset);

public sealed record ReaderAudioPacket(
    string StreamId,
    string DocumentId,
    int ChunkIndex,
    int DurationMs,
    ReaderCursor CursorStart,
    ReaderCursor CursorEnd,
    IReadOnlyList<ReaderSourceSpan> SourceSpans,
    string? SectionId,
    bool IsLast,
    ReadOnlyMemory<byte> PcmBytes) : ReaderStreamEvent(StreamId);

public sealed record ReaderStreamDone(
    string StreamId,
    ReaderCursor Cursor,
    bool DocumentComplete,
    bool NextWindowAvailable) : ReaderStreamEvent(StreamId);

public sealed record ReaderStreamCancelled(
    string StreamId,
    ReaderCursor GeneratedCursor) : ReaderStreamEvent(StreamId);

public sealed record ReaderStreamError(
    string StreamId,
    string ErrorType,
    string Message) : ReaderStreamEvent(StreamId);
