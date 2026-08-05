using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace TtsPlatform.Reader.Client;

public sealed class ReaderServiceClient : IReaderServiceClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly HttpClient _httpClient;
    private readonly ITokenProvider _tokenProvider;

    public ReaderServiceClient(HttpClient httpClient, string serviceBaseUrl, ITokenProvider tokenProvider)
    {
        _httpClient = httpClient;
        _httpClient.BaseAddress = ServiceBaseUrl.Parse(serviceBaseUrl);
        _tokenProvider = tokenProvider;
    }

    public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) =>
        SendAsync<HealthResponse>(HttpMethod.Get, "v1/health", false, null, cancellationToken);

    public Task<ReaderCapabilities> GetCapabilitiesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<ReaderCapabilities>(HttpMethod.Get, "v1/reader/capabilities", true, null, cancellationToken);

    public Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<VoicePage>(HttpMethod.Get, "v1/voices", true, null, cancellationToken);

    public Task<ReaderDocument> CreateDocumentAsync(
        CreateDocumentRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderDocument>(
            HttpMethod.Post,
            "v1/reader/documents",
            true,
            request,
            cancellationToken);

    public Task<ReaderImportPreview> PreviewImportAsync(
        ImportDocumentRequest request,
        Stream content,
        CancellationToken cancellationToken = default) =>
        SendMultipartAsync<ReaderImportPreview>(
            "v1/reader/imports/preview",
            request,
            content,
            allowDuplicate: null,
            cancellationToken);

    public Task<ReaderDocument> ImportDocumentAsync(
        ImportDocumentRequest request,
        Stream content,
        bool allowDuplicate = false,
        CancellationToken cancellationToken = default) =>
        SendMultipartAsync<ReaderDocument>(
            "v1/reader/imports",
            request,
            content,
            allowDuplicate,
            cancellationToken);

    public Task<ReaderDocument> CommitImportAsync(
        string previewId,
        bool allowDuplicate = false,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(previewId);
        return SendAsync<ReaderDocument>(
            HttpMethod.Post,
            $"v1/reader/imports/{Uri.EscapeDataString(previewId)}/commit",
            true,
            new { allow_duplicate = allowDuplicate },
            cancellationToken);
    }

    public Task CancelImportAsync(
        string previewId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(previewId);
        return SendNoContentAsync(
            HttpMethod.Delete,
            $"v1/reader/imports/{Uri.EscapeDataString(previewId)}",
            cancellationToken);
    }

    public Task<ReaderDocument> DuplicateAsEditableTextAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return SendAsync<ReaderDocument>(
            HttpMethod.Post,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/duplicate-as-editable",
            true,
            null,
            cancellationToken);
    }

    public Task<ReaderRuleSetPage> GetRuleSetsAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderRuleSetPage>(
            HttpMethod.Get,
            "v1/reader/rule-sets",
            true,
            null,
            cancellationToken);

    public Task<ReaderRuleSet> CreateRuleSetAsync(
        CreateRuleSetRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderRuleSet>(
            HttpMethod.Post,
            "v1/reader/rule-sets",
            true,
            request,
            cancellationToken);

    public Task<ReaderRuleSet> UpdateRuleSetAsync(
        string ruleSetId,
        CreateRuleSetRequest request,
        bool enabled,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderRuleSet>(
            HttpMethod.Patch,
            $"v1/reader/rule-sets/{Uri.EscapeDataString(ruleSetId)}",
            true,
            new
            {
                expected_row_version = expectedRowVersion,
                request.Name,
                request.Description,
                request.Scope,
                enabled,
            },
            cancellationToken);

    public Task DeleteRuleSetAsync(
        string ruleSetId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) =>
        SendNoContentAsync(
            HttpMethod.Delete,
            $"v1/reader/rule-sets/{Uri.EscapeDataString(ruleSetId)}?expected_row_version={expectedRowVersion}",
            cancellationToken);

    public Task<ReaderRulePage> GetRulesAsync(
        string ruleSetId,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderRulePage>(
            HttpMethod.Get,
            $"v1/reader/rule-sets/{Uri.EscapeDataString(ruleSetId)}/rules",
            true,
            null,
            cancellationToken);

    public Task<ReaderRule> CreateRuleAsync(
        string ruleSetId,
        SaveRuleRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderRule>(
            HttpMethod.Post,
            $"v1/reader/rule-sets/{Uri.EscapeDataString(ruleSetId)}/rules",
            true,
            request,
            cancellationToken);

    public Task<ReaderRule> UpdateRuleAsync(
        string ruleId,
        SaveRuleRequest request,
        int expectedRowVersion,
        CancellationToken cancellationToken = default)
    {
        var body = new
        {
            expected_row_version = expectedRowVersion,
            request.Name,
            request.Enabled,
            request.Stage,
            request.RuleType,
            request.Pattern,
            request.Replacement,
            request.CaseSensitive,
            request.WholeWord,
            request.LanguageFilter,
            request.EngineFilter,
            request.VoiceFilter,
            request.DocumentFilter,
            request.Priority,
            request.RegexTimeoutMs,
        };
        return SendAsync<ReaderRule>(
            HttpMethod.Patch,
            $"v1/reader/rules/{Uri.EscapeDataString(ruleId)}",
            true,
            body,
            cancellationToken);
    }

    public Task DeleteRuleAsync(
        string ruleId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default) =>
        SendNoContentAsync(
            HttpMethod.Delete,
            $"v1/reader/rules/{Uri.EscapeDataString(ruleId)}?expected_row_version={expectedRowVersion}",
            cancellationToken);

    public Task<ReaderRulePreview> PreviewRulesAsync(
        RulePreviewRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderRulePreview>(
            HttpMethod.Post,
            "v1/reader/rules/preview",
            true,
            request,
            cancellationToken);

    public Task<ReaderRuleImportReport> ImportRulesAsync(
        string targetRuleSetId,
        string content,
        bool commit,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderRuleImportReport>(
            HttpMethod.Post,
            "v1/reader/rule-imports",
            true,
            new
            {
                target_rule_set_id = targetRuleSetId,
                content,
                commit,
            },
            cancellationToken);

    public async Task<byte[]> ExportRuleSetAsync(
        string ruleSetId,
        CancellationToken cancellationToken = default)
    {
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            $"v1/reader/rule-sets/{Uri.EscapeDataString(ruleSetId)}/export");
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        await AttachBearerAsync(request, cancellationToken).ConfigureAwait(false);
        using var response = await SendHttpAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }
        const int maximumBytes = 1_048_576;
        if (response.Content.Headers.ContentLength > maximumBytes)
        {
            throw new ReaderServiceUnavailableException("The exported rule set is too large.");
        }
        var content = await response.Content.ReadAsByteArrayAsync(cancellationToken)
            .ConfigureAwait(false);
        return content.Length <= maximumBytes
            ? content
            : throw new ReaderServiceUnavailableException("The exported rule set is too large.");
    }

    public Task<DocumentPage> GetDocumentsAsync(
        int limit = 50,
        string? cursor = null,
        string? query = null,
        string? state = null,
        CancellationToken cancellationToken = default)
    {
        if (limit <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(limit));
        }

        var values = new List<string> { $"limit={limit}" };
        AddQueryValue(values, "cursor", cursor);
        AddQueryValue(values, "query", query);
        AddQueryValue(values, "state", state);
        return SendAsync<DocumentPage>(
            HttpMethod.Get,
            $"v1/reader/documents?{string.Join('&', values)}",
            true,
            null,
            cancellationToken);
    }

    public Task<ReaderDocument> GetDocumentAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return SendAsync<ReaderDocument>(
            HttpMethod.Get,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}",
            true,
            null,
            cancellationToken);
    }

    public Task<ReaderDocument> UpdateDocumentAsync(
        string documentId,
        UpdateDocumentRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return SendAsync<ReaderDocument>(
            HttpMethod.Patch,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}",
            true,
            request,
            cancellationToken);
    }

    public Task<ReaderDocument> DeleteDocumentAsync(
        string documentId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        if (expectedRowVersion <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(expectedRowVersion));
        }
        return SendAsync<ReaderDocument>(
            HttpMethod.Delete,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}?expected_row_version={expectedRowVersion}",
            true,
            null,
            cancellationToken);
    }

    public Task<BlockPage> GetBlocksAsync(
        string documentId,
        int afterOrdinal = -1,
        int limit = 200,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        if (afterOrdinal < -1 || limit <= 0)
        {
            throw new ArgumentOutOfRangeException(afterOrdinal < -1 ? nameof(afterOrdinal) : nameof(limit));
        }

        return SendAsync<BlockPage>(
            HttpMethod.Get,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/blocks?after_ordinal={afterOrdinal}&limit={limit}",
            true,
            null,
            cancellationToken);
    }

    public Task<MutationResponse> ReplaceContentAsync(
        string documentId,
        ReplaceContentRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<MutationResponse>(
            HttpMethod.Patch,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/content",
            true,
            request,
            cancellationToken);

    public Task<MutationResponse> AppendContentAsync(
        string documentId,
        AppendContentRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<MutationResponse>(
            HttpMethod.Post,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/append",
            true,
            request,
            cancellationToken);

    public Task<MutationResponse> UndoAsync(
        string documentId,
        ExpectedVersionRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<MutationResponse>(
            HttpMethod.Post,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/undo",
            true,
            request,
            cancellationToken);

    public Task<MutationResponse> RedoAsync(
        string documentId,
        ExpectedVersionRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<MutationResponse>(
            HttpMethod.Post,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/redo",
            true,
            request,
            cancellationToken);

    public async Task<ReaderPosition?> GetPositionAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        var envelope = await SendAsync<ReaderPositionEnvelope>(
            HttpMethod.Get,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/position",
            true,
            null,
            cancellationToken).ConfigureAwait(false);
        return envelope.Position;
    }

    public Task<ReaderPosition> SavePositionAsync(
        string documentId,
        SavePositionRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        if (!string.Equals(request.Cursor.DocumentId, documentId, StringComparison.Ordinal))
        {
            throw new ArgumentException("The position cursor must belong to the document.", nameof(request));
        }
        var body = new
        {
            cursor = new
            {
                block_id = request.Cursor.BlockId,
                block_ordinal = request.Cursor.BlockOrdinal,
                character_offset = request.Cursor.CharacterOffset,
                content_revision = request.Cursor.ContentRevision,
                segment_index = request.Cursor.SegmentIndex,
            },
            voice_profile_id = request.VoiceProfileId,
            pipeline_version = request.PipelineVersion,
            rules_version = request.RulesVersion,
            completed = request.Completed,
            expected_row_version = request.ExpectedRowVersion,
        };
        return SendAsync<ReaderPosition>(
            HttpMethod.Put,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/position",
            true,
            body,
            cancellationToken);
    }

    public Task<ReaderBookmarkPage> GetBookmarksAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return SendAsync<ReaderBookmarkPage>(
            HttpMethod.Get,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/bookmarks",
            true,
            null,
            cancellationToken);
    }

    public Task<ReaderBookmark> CreateBookmarkAsync(
        string documentId,
        CreateBookmarkRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return SendAsync<ReaderBookmark>(
            HttpMethod.Post,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/bookmarks",
            true,
            request,
            cancellationToken);
    }

    public Task DeleteBookmarkAsync(
        string bookmarkId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(bookmarkId);
        return SendNoContentAsync(
            HttpMethod.Delete,
            $"v1/reader/bookmarks/{Uri.EscapeDataString(bookmarkId)}?expected_row_version={expectedRowVersion}",
            cancellationToken);
    }

    public Task<ReaderQueuePage> GetQueueAsync(CancellationToken cancellationToken = default) =>
        SendAsync<ReaderQueuePage>(
            HttpMethod.Get,
            "v1/reader/queue",
            true,
            null,
            cancellationToken);

    public Task<ReaderQueueItem> AddQueueItemAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return SendAsync<ReaderQueueItem>(
            HttpMethod.Post,
            "v1/reader/queue/items",
            true,
            new { document_id = documentId, status = "queued" },
            cancellationToken);
    }

    public Task<ReaderQueuePage> ReorderQueueAsync(
        IReadOnlyList<string> itemIds,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderQueuePage>(
            HttpMethod.Post,
            "v1/reader/queue/reorder",
            true,
            new { item_ids = itemIds },
            cancellationToken);

    public Task<ReaderQueueItem> ActivateQueueItemAsync(
        string itemId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(itemId);
        return SendAsync<ReaderQueueItem>(
            HttpMethod.Post,
            $"v1/reader/queue/items/{Uri.EscapeDataString(itemId)}/activate",
            true,
            null,
            cancellationToken);
    }

    public Task<ReaderQueueItem?> AdvanceQueueAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        return SendOptionalAsync<ReaderQueueItem>(
            HttpMethod.Post,
            $"v1/reader/queue/advance/{Uri.EscapeDataString(documentId)}",
            true,
            null,
            cancellationToken);
    }

    public Task<ReaderDesktopOpenRequest?> GetNextDesktopOpenRequestAsync(
        CancellationToken cancellationToken = default) =>
        SendOptionalAsync<ReaderDesktopOpenRequest>(
            HttpMethod.Get,
            "v1/reader/desktop/open-requests/next",
            true,
            null,
            cancellationToken);

    public Task AcknowledgeDesktopOpenRequestAsync(
        string requestId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(requestId);
        return SendNoContentAsync(
            HttpMethod.Delete,
            $"v1/reader/desktop/open-requests/{Uri.EscapeDataString(requestId)}",
            cancellationToken);
    }

    public Task RemoveQueueItemAsync(
        string itemId,
        int expectedRowVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(itemId);
        return SendNoContentAsync(
            HttpMethod.Delete,
            $"v1/reader/queue/items/{Uri.EscapeDataString(itemId)}?expected_row_version={expectedRowVersion}",
            cancellationToken);
    }

    public Task<ReaderExportJobPage> GetExportsAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderExportJobPage>(
            HttpMethod.Get,
            "v1/reader/exports",
            true,
            null,
            cancellationToken);

    public Task<ReaderExportJob> CreateExportAsync(
        CreateExportRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<ReaderExportJob>(
            HttpMethod.Post,
            "v1/reader/exports",
            true,
            request,
            cancellationToken);

    public Task<ReaderExportJob> GetExportAsync(
        string jobId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        return SendAsync<ReaderExportJob>(
            HttpMethod.Get,
            $"v1/reader/exports/{Uri.EscapeDataString(jobId)}",
            true,
            null,
            cancellationToken);
    }

    public Task<ReaderExportJob> CancelExportAsync(
        string jobId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        return SendAsync<ReaderExportJob>(
            HttpMethod.Delete,
            $"v1/reader/exports/{Uri.EscapeDataString(jobId)}",
            true,
            null,
            cancellationToken);
    }

    public async Task<byte[]> SynthesizeAsync(
        EphemeralSynthesisRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (string.IsNullOrWhiteSpace(request.Text))
        {
            throw new ArgumentException("Immediate speech text must not be empty.", nameof(request));
        }

        using var message = new HttpRequestMessage(HttpMethod.Post, "v1/tts");
        message.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("audio/wav"));
        await AttachBearerAsync(message, cancellationToken).ConfigureAwait(false);
        message.Content = JsonContent.Create(request, options: JsonOptions);

        HttpResponseMessage response;
        try
        {
            response = await _httpClient.SendAsync(
                message,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw new ReaderServiceUnavailableException(
                "The local TTS service could not be reached. Start the service and try again.",
                exception);
        }
        catch (TaskCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new ReaderServiceUnavailableException(
                "The local TTS service did not respond in time. Check the service and try again.",
                exception);
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
            }
            const int maximumAudioBytes = 64 * 1024 * 1024;
            if (response.Content.Headers.ContentLength > maximumAudioBytes)
            {
                throw new ReaderServiceUnavailableException(
                    "The local TTS service returned an oversized audio response.");
            }
            var audio = await response.Content.ReadAsByteArrayAsync(cancellationToken)
                .ConfigureAwait(false);
            if (audio.Length is 0 or > maximumAudioBytes)
            {
                throw new ReaderServiceUnavailableException(
                    "The local TTS service returned invalid audio data.");
            }
            return audio;
        }
    }

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string relativeUrl,
        bool authenticated,
        object? body,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, relativeUrl);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        if (authenticated)
        {
            await AttachBearerAsync(request, cancellationToken).ConfigureAwait(false);
        }

        if (body is not null)
        {
            request.Content = JsonContent.Create(body, options: JsonOptions);
        }

        HttpResponseMessage response;
        try
        {
            response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw new ReaderServiceUnavailableException(
                "The local TTS service could not be reached. Start the service and try again.",
                exception);
        }
        catch (TaskCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new ReaderServiceUnavailableException(
                "The local TTS service did not respond in time. Check the service and try again.",
                exception);
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
            }

            var result = await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken)
                .ConfigureAwait(false);
            return result ?? throw new ReaderServiceUnavailableException(
                "The local TTS service returned an empty response.");
        }
    }

    private async Task<T?> SendOptionalAsync<T>(
        HttpMethod method,
        string relativeUrl,
        bool authenticated,
        object? body,
        CancellationToken cancellationToken)
        where T : class
    {
        using var request = new HttpRequestMessage(method, relativeUrl);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        if (authenticated)
        {
            await AttachBearerAsync(request, cancellationToken).ConfigureAwait(false);
        }
        if (body is not null)
        {
            request.Content = JsonContent.Create(body, options: JsonOptions);
        }
        using var response = await SendHttpAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }
        return await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken)
            .ConfigureAwait(false);
    }

    private async Task<T> SendMultipartAsync<T>(
        string relativeUrl,
        ImportDocumentRequest import,
        Stream content,
        bool? allowDuplicate,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(import);
        ArgumentNullException.ThrowIfNull(content);
        ArgumentException.ThrowIfNullOrWhiteSpace(import.FileName);

        using var request = new HttpRequestMessage(HttpMethod.Post, relativeUrl);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        await AttachBearerAsync(request, cancellationToken).ConfigureAwait(false);
        var multipart = new MultipartFormDataContent();
        var fileContent = new StreamContent(content);
        fileContent.Headers.ContentType = MediaTypeHeaderValue.TryParse(
            import.ContentType,
            out var mediaType)
            ? mediaType
            : new MediaTypeHeaderValue("application/octet-stream");
        multipart.Add(fileContent, "file", import.FileName);
        AddFormValue(multipart, "title", import.Title);
        AddFormValue(multipart, "language_hint", import.LanguageHint);
        if (import.CopySourceFile is not null)
        {
            AddFormValue(multipart, "copy_source_file", import.CopySourceFile.Value ? "true" : "false");
        }
        if (allowDuplicate is not null)
        {
            AddFormValue(multipart, "allow_duplicate", allowDuplicate.Value ? "true" : "false");
        }
        request.Content = multipart;

        using var response = await SendHttpAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }
        var result = await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken)
            .ConfigureAwait(false);
        return result ?? throw new ReaderServiceUnavailableException(
            "The local TTS service returned an empty response.");
    }

    private async Task SendNoContentAsync(
        HttpMethod method,
        string relativeUrl,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, relativeUrl);
        await AttachBearerAsync(request, cancellationToken).ConfigureAwait(false);
        using var response = await SendHttpAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<HttpResponseMessage> SendHttpAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        try
        {
            return await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw new ReaderServiceUnavailableException(
                "The local TTS service could not be reached. Start the service and try again.",
                exception);
        }
        catch (TaskCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new ReaderServiceUnavailableException(
                "The local TTS service did not respond in time. Check the service and try again.",
                exception);
        }
    }

    private static void AddFormValue(MultipartFormDataContent multipart, string name, string? value)
    {
        if (!string.IsNullOrWhiteSpace(value))
        {
            multipart.Add(new StringContent(value, Encoding.UTF8), name);
        }
    }

    private async Task AttachBearerAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var token = (await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false))?.Trim();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ReaderTokenUnavailableException(
                "Choose the service token file before connecting to protected Reader operations.");
        }

        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
    }

    private static async Task ThrowApiExceptionAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
            using var payload = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken)
                .ConfigureAwait(false);
            var error = payload.RootElement.GetProperty("error");
            var type = error.GetProperty("type").GetString() ?? "reader_error";
            var message = error.GetProperty("message").GetString() ?? "The Reader operation failed.";
            var requestId = error.TryGetProperty("request_id", out var requestIdElement)
                ? requestIdElement.GetString()
                : null;
            var details = new Dictionary<string, object?>();
            if (error.TryGetProperty("details", out var detailsElement))
            {
                foreach (var item in detailsElement.EnumerateObject())
                {
                    details[item.Name] = ConvertJsonValue(item.Value);
                }
            }

            throw new ReaderApiException(type, message, (int)response.StatusCode, requestId, details);
        }
        catch (ReaderApiException)
        {
            throw;
        }
        catch (Exception exception) when (
            exception is JsonException or KeyNotFoundException or InvalidOperationException)
        {
            throw new ReaderApiException(
                "reader_http_error",
                $"The local TTS service returned HTTP {(int)response.StatusCode}.",
                (int)response.StatusCode);
        }
    }

    private static object? ConvertJsonValue(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString(),
        JsonValueKind.Number when value.TryGetInt64(out var integer) => integer,
        JsonValueKind.Number => value.GetDouble(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        JsonValueKind.Null => null,
        _ => value.Clone(),
    };

    private static void AddQueryValue(ICollection<string> values, string name, string? value)
    {
        if (!string.IsNullOrWhiteSpace(value))
        {
            values.Add($"{name}={Uri.EscapeDataString(value)}");
        }
    }

    private sealed record ReaderPositionEnvelope(ReaderPosition? Position);
}
