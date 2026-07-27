using System.Net;
using System.Text;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class ReaderServiceClientTests
{
    [Fact]
    public async Task Health_is_public_and_capabilities_use_bearer_token()
    {
        var handler = new RecordingHandler(request => request.RequestUri!.AbsolutePath switch
        {
            "/v1/health" => Json(HttpStatusCode.OK, HealthJson),
            "/v1/reader/capabilities" => Json(HttpStatusCode.OK, CapabilitiesJson),
            _ => Json(HttpStatusCode.NotFound, "{}"),
        });
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://127.0.0.1:8000/",
            new StaticTokenProvider("local-secret"));

        var health = await client.GetHealthAsync();
        var capabilities = await client.GetCapabilitiesAsync();

        Assert.Equal("ok", health.Status);
        Assert.True(capabilities.Database.Ready);
        Assert.Null(handler.Requests[0].Authorization);
        Assert.Equal("Bearer local-secret", handler.Requests[1].Authorization);
    }

    [Fact]
    public async Task Protected_calls_fail_before_http_when_token_is_missing()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.OK, CapabilitiesJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider(null));

        await Assert.ThrowsAsync<ReaderTokenUnavailableException>(() => client.GetCapabilitiesAsync());
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task Replace_content_serializes_integer_row_version()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.OK, MutationJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        await client.ReplaceContentAsync(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            new ReplaceContentRequest(7, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", 0, 3, "new"));

        Assert.Contains("\"expected_row_version\":7", handler.Requests.Single().Body, StringComparison.Ordinal);
        Assert.DoesNotContain("\"expected_row_version\":\"7\"", handler.Requests.Single().Body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Clipboard_document_and_immediate_speech_use_distinct_protected_routes()
    {
        var wave = new byte[] { 82, 73, 70, 70, 1, 2, 3, 4 };
        var handler = new RecordingHandler(request => request.RequestUri!.AbsolutePath switch
        {
            "/v1/reader/documents" => Json(HttpStatusCode.Created, DocumentJson),
            "/v1/tts" => new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(wave),
            },
            _ => Json(HttpStatusCode.NotFound, "{}"),
        });
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        var document = await client.CreateDocumentAsync(
            new CreateDocumentRequest("Clipboard", "clipboard", "Saved", AllowDuplicate: true));
        var audio = await client.SynthesizeAsync(new EphemeralSynthesisRequest("Read only"));

        Assert.Equal("clipboard", document.SourceType);
        Assert.Equal(wave, audio);
        Assert.Equal(["/v1/reader/documents", "/v1/tts"],
            handler.Requests.Select(item => item.Uri.AbsolutePath));
        Assert.All(handler.Requests, request => Assert.Equal("Bearer token", request.Authorization));
        Assert.Contains("\"source_type\":\"clipboard\"", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("\"allow_duplicate\":true", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("\"text\":\"Read only\"", handler.Requests[1].Body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Typed_api_error_preserves_conflict_details()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.Conflict, ErrorJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        var exception = await Assert.ThrowsAsync<ReaderApiException>(() =>
            client.UndoAsync("doc", new ExpectedVersionRequest(1)));

        Assert.Equal("reader_revision_conflict", exception.ErrorType);
        Assert.Equal(409, exception.StatusCode);
        Assert.Equal(2L, exception.Details["actual_row_version"]);
        Assert.Equal("request-1", exception.RequestId);
    }

    [Fact]
    public async Task Position_round_trip_uses_protected_document_route()
    {
        var handler = new RecordingHandler(request => request.Method == HttpMethod.Get
            ? Json(HttpStatusCode.OK, $"{{\"position\":{PositionJson}}}")
            : Json(HttpStatusCode.OK, PositionJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));
        var cursor = new ReaderCursor("doc", "block", 0, 3, 1);

        var loaded = await client.GetPositionAsync("doc");
        var saved = await client.SavePositionAsync("doc", new SavePositionRequest(cursor, ExpectedRowVersion: 2));

        Assert.Equal(3, loaded?.Cursor.CharacterOffset);
        Assert.Equal(3, saved.Cursor.CharacterOffset);
        Assert.All(handler.Requests, request => Assert.Equal("Bearer token", request.Authorization));
        Assert.Contains("\"expected_row_version\":2", handler.Requests[1].Body, StringComparison.Ordinal);
        Assert.DoesNotContain("document_id", handler.Requests[1].Body, StringComparison.Ordinal);
    }

    private static HttpResponseMessage Json(HttpStatusCode status, string body) => new(status)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };

    private sealed class StaticTokenProvider(string? token) : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(token);
    }

    private sealed class RecordingHandler(Func<HttpRequestMessage, HttpResponseMessage> responseFactory)
        : HttpMessageHandler
    {
        public List<RecordedRequest> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken);
            Requests.Add(new RecordedRequest(
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                body));
            return responseFactory(request);
        }
    }

    private sealed record RecordedRequest(Uri Uri, string? Authorization, string Body);

    private const string HealthJson = """
        {
          "status":"ok","version":"0.1","checks":{"backend_ready":true,"default_voice_loaded":true},
          "startup_error":null,"auth_enabled":true,
          "reader":{"enabled":true,"database_ready":true,"schema_version":1,"startup_error":null}
        }
        """;

    private const string CapabilitiesJson = """
        {
          "contract_version":1,"enabled":true,
          "database":{"ready":true,"schema_version":1,"search_available":false},
          "playback":{"stream_protocol_version":1,"source_offset_encoding":"utf-16","max_blocks_per_window":64,"max_source_chars_per_window":32000}
        }
        """;

    private const string MutationJson = """
        {
          "document":{
            "id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","title":"Document","source_type":"plain_text",
            "source_name":null,"source_uri":null,"source_sha256":null,"language_hint":null,"state":"inbox",
            "created_at":"2026-07-27T12:00:00Z","updated_at":"2026-07-27T12:01:00Z","imported_at":"2026-07-27T12:00:00Z",
            "deleted_at":null,"content_revision":2,"row_version":8,"total_sections":1,"total_blocks":1,"total_characters":3,"metadata":{}
          },"edit":null
        }
        """;

    private const string DocumentJson = """
        {
          "id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","title":"Clipboard","source_type":"clipboard",
          "source_name":null,"source_uri":null,"source_sha256":null,"language_hint":null,"state":"inbox",
          "created_at":"2026-07-27T12:00:00Z","updated_at":"2026-07-27T12:00:00Z","imported_at":"2026-07-27T12:00:00Z",
          "deleted_at":null,"content_revision":1,"row_version":1,"total_sections":1,"total_blocks":1,"total_characters":5,"metadata":{}
        }
        """;

    private const string ErrorJson = """
        {"error":{"type":"reader_revision_conflict","message":"changed","param":null,"request_id":"request-1","details":{"expected_row_version":1,"actual_row_version":2}}}
        """;

    private const string PositionJson = """
        {
          "document_id":"doc",
          "cursor":{"document_id":"doc","block_id":"block","block_ordinal":0,"character_offset":3,"content_revision":1,"segment_index":null},
          "voice_profile_id":null,"pipeline_version":1,"rules_version":1,
          "updated_at":"2026-07-27T12:00:00Z","completed":false,"row_version":2
        }
        """;
}
