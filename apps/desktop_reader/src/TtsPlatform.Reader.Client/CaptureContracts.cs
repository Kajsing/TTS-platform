using System.Text.Json.Serialization;

namespace TtsPlatform.Reader.Client;

public sealed record CaptureRequest(
    string Action, string Text, string Title = "Clipboard article",
    [property: JsonPropertyName("document_id")] string? DocumentId = null,
    [property: JsonPropertyName("target_operation_id")] string? TargetOperationId = null,
    [property: JsonPropertyName("folder_id")] string? FolderId = null,
    [property: JsonPropertyName("new_chapter")] bool NewChapter = true,
    [property: JsonPropertyName("allow_duplicate")] bool AllowDuplicate = false);

public sealed record CaptureReceipt(string OperationId, string DocumentId, string Outcome);
