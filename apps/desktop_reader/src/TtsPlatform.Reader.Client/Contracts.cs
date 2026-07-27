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
