using System.Net.Http.Headers;
using System.Net.Http.Json;
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
