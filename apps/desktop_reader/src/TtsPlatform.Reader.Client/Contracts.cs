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
    Task<ReaderImportPreview> PreviewImportAsync(
        ImportDocumentRequest request,
        Stream content,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderDocument> ImportDocumentAsync(
        ImportDocumentRequest request,
        Stream content,
        bool allowDuplicate = false,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderDocument> CommitImportAsync(
        string previewId,
        bool allowDuplicate = false,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task CancelImportAsync(
        string previewId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderDocument> DuplicateAsEditableTextAsync(
        string documentId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRuleSetPage> GetRuleSetsAsync(
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRuleSet> CreateRuleSetAsync(
        CreateRuleSetRequest request,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRuleSet> UpdateRuleSetAsync(
        string ruleSetId,
        CreateRuleSetRequest request,
        bool enabled,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task DeleteRuleSetAsync(
        string ruleSetId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRulePage> GetRulesAsync(
        string ruleSetId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRule> CreateRuleAsync(
        string ruleSetId,
        SaveRuleRequest request,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRule> UpdateRuleAsync(
        string ruleId,
        SaveRuleRequest request,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task DeleteRuleAsync(
        string ruleId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRulePreview> PreviewRulesAsync(
        RulePreviewRequest request,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderRuleImportReport> ImportRulesAsync(
        string targetRuleSetId,
        string content,
        bool commit,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<byte[]> ExportRuleSetAsync(
        string ruleSetId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<DocumentPage> GetDocumentsAsync(
        int limit = 50,
        string? cursor = null,
        string? query = null,
        string? state = null,
        CancellationToken cancellationToken = default);
    Task<ReaderDocument> GetDocumentAsync(
        string documentId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderDocument> UpdateDocumentAsync(
        string documentId,
        UpdateDocumentRequest request,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderDocument> DeleteDocumentAsync(
        string documentId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
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
    Task<ReaderBookmarkPage> GetBookmarksAsync(
        string documentId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderBookmark> CreateBookmarkAsync(
        string documentId,
        CreateBookmarkRequest request,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task DeleteBookmarkAsync(
        string bookmarkId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderQueuePage> GetQueueAsync(CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();
    Task<ReaderQueueItem> AddQueueItemAsync(
        string documentId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderQueuePage> ReorderQueueAsync(
        IReadOnlyList<string> itemIds,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderQueueItem> ActivateQueueItemAsync(
        string itemId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderQueueItem?> AdvanceQueueAsync(
        string documentId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderDesktopOpenRequest?> GetNextDesktopOpenRequestAsync(
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task AcknowledgeDesktopOpenRequestAsync(
        string requestId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task RemoveQueueItemAsync(
        string itemId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderExportJobPage> GetExportsAsync(CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();
    Task<ReaderExportJob> CreateExportAsync(
        CreateExportRequest request,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderExportJob> GetExportAsync(
        string jobId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
    Task<ReaderExportJob> CancelExportAsync(
        string jobId,
        CancellationToken cancellationToken = default) => throw new NotSupportedException();
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
    ReaderPlaybackCapability Playback,
    ReaderImportCapability? Imports = null,
    ReaderRuleCapability? Rules = null,
    ReaderExportCapability? Exports = null);

public sealed record ReaderDatabaseCapability(bool Ready, int SchemaVersion, bool SearchAvailable);

public sealed record ReaderPlaybackCapability(
    int StreamProtocolVersion,
    string SourceOffsetEncoding,
    int MaxBlocksPerWindow,
    int MaxSourceCharsPerWindow);

public sealed record ReaderImportCapability(
    IReadOnlyList<string> Formats,
    int MaxFileBytes,
    bool OcrAvailable);

public sealed record ReaderRuleCapability(
    IReadOnlyList<string> Types,
    bool RegexTimeoutSupported);

public sealed record ReaderExportCapability(IReadOnlyList<string> Formats);

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

public sealed record UpdateDocumentRequest(
    [property: JsonPropertyName("expected_row_version")] int ExpectedRowVersion,
    string? Title = null,
    string? State = null);

public sealed record ImportDocumentRequest(
    string FileName,
    string? ContentType = null,
    string? Title = null,
    string? LanguageHint = null,
    bool? CopySourceFile = null);

public sealed record ReaderImportWarning(string Code, string Message, int Count);

public sealed record ReaderImportSectionPreview(
    int Ordinal,
    int Level,
    string? Heading,
    int FirstBlockOrdinal);

public sealed record ReaderImportBlockPreview(
    int Ordinal,
    string Kind,
    string Text,
    int SectionOrdinal);

public sealed record ReaderImportPreview(
    string PreviewId,
    string Title,
    string SourceType,
    string SourceName,
    int TotalSections,
    int TotalBlocks,
    int TotalCharacters,
    IReadOnlyList<ReaderImportWarning> Warnings,
    IReadOnlyList<ReaderImportSectionPreview> Sections,
    IReadOnlyList<ReaderImportBlockPreview> SampleBlocks,
    bool PreviewTruncated,
    string? DuplicateDocumentId,
    int ExpiresInSeconds);

public sealed record ReaderRuleSetPage(
    [property: JsonPropertyName("rule_sets")] IReadOnlyList<ReaderRuleSet> RuleSets,
    [property: JsonPropertyName("rules_version")] int RulesVersion);

public sealed record ReaderRuleSet(
    string Id,
    string Name,
    string Description,
    bool Enabled,
    string Scope,
    int Version,
    int RowVersion,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

public sealed record CreateRuleSetRequest(
    string Name,
    string Description = "",
    string Scope = "global");

public sealed record ReaderRulePage(IReadOnlyList<ReaderRule> Rules);

public sealed record ReaderRule(
    string Id,
    string RuleSetId,
    string Name,
    bool Enabled,
    string Stage,
    string RuleType,
    string Pattern,
    string Replacement,
    bool CaseSensitive,
    bool WholeWord,
    string? LanguageFilter,
    string? EngineFilter,
    string? VoiceFilter,
    string? DocumentFilter,
    int Priority,
    int RegexTimeoutMs,
    int RowVersion,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    JsonElement RawImportMetadata);

public sealed record SaveRuleRequest(
    string Name,
    string Stage,
    string RuleType,
    string Pattern,
    string Replacement,
    bool Enabled = true,
    bool CaseSensitive = false,
    bool WholeWord = false,
    string? LanguageFilter = null,
    string? EngineFilter = null,
    string? VoiceFilter = null,
    string? DocumentFilter = null,
    int Priority = 100,
    int? RegexTimeoutMs = null);

public sealed record RulePreviewRequest(
    string Text,
    [property: JsonPropertyName("rule_set_ids")] IReadOnlyList<string> RuleSetIds,
    string? Language = null,
    string? Engine = null,
    string? Voice = null,
    string? DocumentId = null);

public sealed record ReaderRulePreviewSpan(int StartOffset, int EndOffset);
public sealed record ReaderRuleTrace(
    string RuleId,
    string RuleType,
    int StartOffset,
    int EndOffset,
    int ReplacementLength);
public sealed record ReaderRuleWarning(string Code, string Message, string? RuleId);
public sealed record ReaderRulePreview(
    string OriginalText,
    string SpokenText,
    IReadOnlyList<ReaderRulePreviewSpan> SourceSpans,
    IReadOnlyList<ReaderRuleTrace> Trace,
    IReadOnlyList<ReaderRuleWarning> Warnings,
    double ElapsedMs,
    int PipelineVersion,
    int RulesVersion);

public sealed record ReaderRuleImportReport(
    string SourceSha256,
    int Imported,
    int Disabled,
    int Duplicate,
    int Invalid,
    int Unsupported,
    bool Committed,
    bool Idempotent);

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

public sealed record CreateBookmarkRequest(ReaderCursor Cursor, string Label = "", string Note = "");

public sealed record ReaderBookmark(
    string Id,
    string DocumentId,
    ReaderCursor Cursor,
    string Label,
    string Note,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    int RowVersion);

public sealed record ReaderBookmarkPage(IReadOnlyList<ReaderBookmark> Bookmarks);

public sealed record ReaderQueueItem(
    string Id,
    string DocumentId,
    int Ordinal,
    string Status,
    DateTimeOffset AddedAt,
    DateTimeOffset UpdatedAt,
    int RowVersion);

public sealed record ReaderQueuePage(IReadOnlyList<ReaderQueueItem> Items);

public sealed record ReaderDesktopOpenRequest(
    string Id,
    string DocumentId,
    DateTimeOffset CreatedAt);

public sealed record CreateExportRequest(
    [property: JsonPropertyName("document_ids")] IReadOnlyList<string>? DocumentIds = null,
    [property: JsonPropertyName("queue_item_ids")] IReadOnlyList<string>? QueueItemIds = null,
    [property: JsonPropertyName("section_ids")] IReadOnlyList<string>? SectionIds = null,
    [property: JsonPropertyName("voice_id")] string? VoiceId = null,
    [property: JsonPropertyName("output_basename")] string? OutputBasename = null,
    [property: JsonPropertyName("overwrite_existing")] bool OverwriteExisting = false);

public sealed record ReaderExportJob(
    string Id,
    string Status,
    IReadOnlyList<string> DocumentIds,
    IReadOnlyList<string> SectionIds,
    string? VoiceId,
    string? OutputBasename,
    bool OverwriteExisting,
    int TotalDocuments,
    int CompletedDocuments,
    string? CurrentDocumentId,
    IReadOnlyList<string> OutputFiles,
    string? ErrorType,
    string? ErrorMessage,
    bool CancelRequested,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    DateTimeOffset? CompletedAt,
    int RowVersion);

public sealed record ReaderExportJobPage(IReadOnlyList<ReaderExportJob> Jobs);

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

public sealed record ReaderStreamWarning(
    string StreamId,
    string WarningType,
    string Message,
    string? RuleId) : ReaderStreamEvent(StreamId);

public sealed record ReaderStreamError(
    string StreamId,
    string ErrorType,
    string Message) : ReaderStreamEvent(StreamId);
