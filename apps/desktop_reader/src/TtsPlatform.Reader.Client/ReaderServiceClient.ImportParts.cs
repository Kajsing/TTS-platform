namespace TtsPlatform.Reader.Client;

public sealed record ReaderImportPartPreview(
    int Number, string Title, int FirstChapter, int LastChapter,
    string ChapterStartTitle, string ChapterEndTitle,
    int Codepoints, int Utf16Units, int Blocks, string TextSha256);

public sealed record ReaderImportPartsPreview(
    string PreviewId, string PlanKey, int MaxCharacters, int HeadingLevel,
    int ChapterCount, IReadOnlyList<ReaderImportPartPreview> Parts,
    bool CanCommit, IReadOnlyList<string> Issues);

public sealed record ReaderImportPartsResult(IReadOnlyList<ReaderDocument> Documents);

public sealed partial class ReaderServiceClient
{
    public Task<ReaderImportPartsPreview> PreviewImportPartsAsync(
        string previewId, int maxCharacters = 900000, int headingLevel = 1,
        CancellationToken cancellationToken = default)
    {
        ValidateImportParts(previewId, maxCharacters, headingLevel);
        return SendPartsAsync<ReaderImportPartsPreview>(
            $"v1/reader/imports/{Uri.EscapeDataString(previewId)}/parts-preview",
            new { max_characters = maxCharacters, heading_level = headingLevel }, cancellationToken);
    }

    public Task<ReaderImportPartsResult> CommitImportPartsAsync(
        string previewId, string planKey, int maxCharacters = 900000, int headingLevel = 1,
        bool allowDuplicate = false, string? folderId = null,
        CancellationToken cancellationToken = default)
    {
        ValidateImportParts(previewId, maxCharacters, headingLevel);
        ArgumentException.ThrowIfNullOrWhiteSpace(planKey);
        return SendPartsAsync<ReaderImportPartsResult>(
            $"v1/reader/imports/{Uri.EscapeDataString(previewId)}/parts-commit",
            new
            {
                plan_key = planKey,
                max_characters = maxCharacters,
                heading_level = headingLevel,
                allow_duplicate = allowDuplicate,
                folder_id = folderId
            }, cancellationToken);
    }

    private async Task<T> SendPartsAsync<T>(string route, object payload, CancellationToken cancellationToken)
    {
        try { return await SendAsync<T>(HttpMethod.Post, route, true, payload, cancellationToken); }
        catch (Exception exception) when (exception is System.Text.Json.JsonException or IOException or HttpRequestException)
        {
            throw new ReaderServiceUnavailableException(
                "The import response could not be verified. Refresh the library before retrying an uncertain save.", exception);
        }
    }

    private static void ValidateImportParts(string previewId, int maxCharacters, int headingLevel)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(previewId);
        if (maxCharacters is < 1 or > 1000000) throw new ArgumentOutOfRangeException(nameof(maxCharacters));
        if (headingLevel is < 1 or > 9) throw new ArgumentOutOfRangeException(nameof(headingLevel));
    }
}
