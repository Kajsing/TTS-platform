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
    public async Task Replace_content_serializes_integer_version_and_optional_range_end()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.OK, MutationJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        await client.ReplaceContentAsync(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            new ReplaceContentRequest(
                7,
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                0,
                3,
                string.Empty,
                "cccccccc-cccc-4ccc-8ccc-cccccccccccc"));

        Assert.Contains("\"expected_row_version\":7", handler.Requests.Single().Body, StringComparison.Ordinal);
        Assert.DoesNotContain("\"expected_row_version\":\"7\"", handler.Requests.Single().Body, StringComparison.Ordinal);
        Assert.Contains(
            "\"end_block_id\":\"cccccccc-cccc-4ccc-8ccc-cccccccccccc\"",
            handler.Requests.Single().Body,
            StringComparison.Ordinal);
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
        var audio = await client.SynthesizeAsync(
            new EphemeralSynthesisRequest("Read only", Voice: "voice-two"));

        Assert.Equal("clipboard", document.SourceType);
        Assert.Equal(wave, audio);
        Assert.Equal(["/v1/reader/documents", "/v1/tts"],
            handler.Requests.Select(item => item.Uri.AbsolutePath));
        Assert.All(handler.Requests, request => Assert.Equal("Bearer token", request.Authorization));
        Assert.Contains("\"source_type\":\"clipboard\"", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("\"allow_duplicate\":true", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("\"text\":\"Read only\"", handler.Requests[1].Body, StringComparison.Ordinal);
        Assert.Contains("\"voice\":\"voice-two\"", handler.Requests[1].Body, StringComparison.Ordinal);
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

    [Fact]
    public async Task Global_highlighter_round_trip_uses_revisioned_protected_contract()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.OK, HighlighterJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        var loaded = await client.GetHighlighterAsync();
        var saved = await client.ReplaceHighlighterAsync(
            new ReplaceHighlighterRequest(
                loaded.RowVersion,
                [new SaveHighlighterTerm("Mara", Active: false)]));

        Assert.Equal("Mara", Assert.Single(saved.Terms).Term);
        Assert.Equal(HttpMethod.Get, handler.Requests[0].Method);
        Assert.Equal(HttpMethod.Put, handler.Requests[1].Method);
        Assert.All(handler.Requests, request => Assert.Equal("Bearer token", request.Authorization));
        Assert.Contains("\"expected_row_version\":2", handler.Requests[1].Body, StringComparison.Ordinal);
        Assert.Contains("\"term\":\"Mara\"", handler.Requests[1].Body, StringComparison.Ordinal);
        Assert.Contains("\"active\":false", handler.Requests[1].Body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Import_preview_commit_cancel_and_duplicate_use_protected_routes()
    {
        var handler = new RecordingHandler(request => request.RequestUri!.AbsolutePath switch
        {
            "/v1/reader/imports/preview" => Json(HttpStatusCode.OK, ImportPreviewJson),
            "/v1/reader/imports/preview-id/commit" => Json(HttpStatusCode.Created, DocumentJson),
            "/v1/reader/imports/preview-id" => new HttpResponseMessage(HttpStatusCode.NoContent),
            "/v1/reader/documents/doc-id/duplicate-as-editable" => Json(HttpStatusCode.Created, DocumentJson),
            _ => Json(HttpStatusCode.NotFound, "{}"),
        });
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));
        await using var input = new MemoryStream(Encoding.UTF8.GetBytes("# Heading"));

        var preview = await client.PreviewImportAsync(
            new ImportDocumentRequest(
                "book.md",
                "text/markdown",
                Title: "Book",
                LanguageHint: "da",
                CopySourceFile: true),
            input);
        var committed = await client.CommitImportAsync("preview-id", allowDuplicate: true);
        await client.CancelImportAsync("preview-id");
        await client.DuplicateAsEditableTextAsync("doc-id");

        Assert.Equal("Imported", preview.Title);
        Assert.Equal("clipboard", committed.SourceType);
        Assert.All(handler.Requests, request => Assert.Equal("Bearer token", request.Authorization));
        Assert.Contains("# Heading", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("name=title", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("Book", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("true", handler.Requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("\"allow_duplicate\":true", handler.Requests[1].Body, StringComparison.Ordinal);
        Assert.Equal(HttpMethod.Delete, handler.Requests[2].Method);
    }

    [Fact]
    public async Task Speech_rule_management_preview_and_interchange_use_protected_routes()
    {
        var handler = new RecordingHandler(request => request.RequestUri!.AbsolutePath switch
        {
            "/v1/reader/rule-sets" when request.Method == HttpMethod.Get =>
                Json(HttpStatusCode.OK, RuleSetPageJson),
            "/v1/reader/rule-sets" => Json(HttpStatusCode.Created, RuleSetJson),
            "/v1/reader/rule-sets/set-id/rules" => Json(HttpStatusCode.Created, RuleJson),
            "/v1/reader/rules/preview" => Json(HttpStatusCode.OK, RulePreviewJson),
            "/v1/reader/rule-imports" => Json(HttpStatusCode.OK, RuleImportJson),
            "/v1/reader/rule-sets/set-id/export" => Json(HttpStatusCode.OK, "{\"version\":1}"),
            "/v1/reader/rule-sets/set-id" when request.Method == HttpMethod.Delete =>
                new HttpResponseMessage(HttpStatusCode.NoContent),
            _ => Json(HttpStatusCode.NotFound, "{}"),
        });
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        var sets = await client.GetRuleSetsAsync();
        var set = await client.CreateRuleSetAsync(new CreateRuleSetRequest("Danish", Scope: "language"));
        var rule = await client.CreateRuleAsync(
            set.Id,
            new SaveRuleRequest(
                "Expand API",
                "pronunciation",
                "literal_replace",
                "API",
                "A P I",
                LanguageFilter: "da"));
        var preview = await client.PreviewRulesAsync(new RulePreviewRequest("API", [set.Id], "da"));
        var import = await client.ImportRulesAsync(set.Id, "{\"version\":1}", commit: false);
        var exported = await client.ExportRuleSetAsync(set.Id);
        await client.DeleteRuleSetAsync(set.Id, expectedRowVersion: 1);

        Assert.Equal(2, sets.RulesVersion);
        Assert.Equal("literal_replace", rule.RuleType);
        Assert.Equal("A P I", preview.SpokenText);
        Assert.False(import.Committed);
        Assert.Equal("{\"version\":1}", Encoding.UTF8.GetString(exported));
        Assert.All(handler.Requests, request => Assert.Equal("Bearer token", request.Authorization));
        Assert.Contains("\"language_filter\":\"da\"", handler.Requests[2].Body, StringComparison.Ordinal);
        Assert.Contains("\"rule_set_ids\":[\"set-id\"]", handler.Requests[3].Body, StringComparison.Ordinal);
        Assert.Contains("\"commit\":false", handler.Requests[4].Body, StringComparison.Ordinal);
        Assert.Equal("?expected_row_version=1", handler.Requests[6].Uri.Query);
    }

    [Fact]
    public async Task Queue_bookmark_state_and_export_workflows_use_protected_contracts()
    {
        var handler = new RecordingHandler(request => request.RequestUri!.AbsolutePath switch
        {
            "/v1/reader/documents/doc" when request.Method == HttpMethod.Get =>
                Json(HttpStatusCode.OK, DocumentJson),
            "/v1/reader/documents/doc" => Json(HttpStatusCode.OK, DocumentJson),
            "/v1/reader/documents/doc/bookmarks" => Json(HttpStatusCode.Created, BookmarkJson),
            "/v1/reader/queue" => Json(HttpStatusCode.OK, $"{{\"items\":[{QueueItemJson}]}}"),
            "/v1/reader/queue/items" => Json(HttpStatusCode.Created, QueueItemJson),
            "/v1/reader/queue/items/item/activate" => Json(HttpStatusCode.OK, QueueItemJson),
            "/v1/reader/queue/advance/doc" => Json(HttpStatusCode.OK, "null"),
            "/v1/reader/desktop/open-requests/next" =>
                Json(HttpStatusCode.OK, DesktopOpenRequestJson),
            "/v1/reader/desktop/open-requests/open" =>
                new HttpResponseMessage(HttpStatusCode.NoContent),
            "/v1/reader/exports" when request.Method == HttpMethod.Get =>
                Json(HttpStatusCode.OK, $"{{\"jobs\":[{ExportJobJson}]}}"),
            "/v1/reader/exports" => Json(HttpStatusCode.Accepted, ExportJobJson),
            "/v1/reader/exports/job/history" =>
                new HttpResponseMessage(HttpStatusCode.NoContent),
            "/v1/reader/exports/job" => Json(HttpStatusCode.OK, ExportJobJson),
            "/v1/reader/exports/job/result" => new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent([73, 68, 51, 4]),
            },
            _ => Json(HttpStatusCode.NotFound, "{}"),
        });
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        await client.GetDocumentAsync("doc");
        await client.UpdateDocumentAsync("doc", new UpdateDocumentRequest(1, State: "finished"));
        var bookmark = await client.CreateBookmarkAsync(
            "doc",
            new CreateBookmarkRequest(new ReaderCursor("doc", "block", 0, 2, 1), "Mark"));
        var queue = await client.GetQueueAsync();
        await client.AddQueueItemAsync("doc");
        await client.ActivateQueueItemAsync("item");
        var next = await client.AdvanceQueueAsync("doc");
        var openRequest = await client.GetNextDesktopOpenRequestAsync();
        await client.AcknowledgeDesktopOpenRequestAsync(openRequest!.Id);
        var export = await client.CreateExportAsync(
            new CreateExportRequest(
                DocumentIds: ["doc"],
                VoiceId: "voice-two",
                AudioFormat: "mp3"));
        var exports = await client.GetExportsAsync();
        await client.CancelExportAsync("job");
        await client.DeleteExportAsync("job");
        using var exportAudio = new MemoryStream();
        await client.DownloadExportResultAsync("job", 0, exportAudio);

        Assert.Equal("Mark", bookmark.Label);
        Assert.Single(queue.Items);
        Assert.Null(next);
        Assert.Equal("doc", openRequest.DocumentId);
        Assert.Equal("job", export.Id);
        Assert.Single(exports.Jobs);
        Assert.Equal([73, 68, 51, 4], exportAudio.ToArray());
        Assert.All(handler.Requests, request => Assert.Equal("Bearer token", request.Authorization));
        Assert.Contains("\"state\":\"finished\"", handler.Requests[1].Body, StringComparison.Ordinal);
        Assert.Contains("\"document_ids\":[\"doc\"]", handler.Requests[9].Body, StringComparison.Ordinal);
        Assert.Contains("\"audio_format\":\"mp3\"", handler.Requests[9].Body, StringComparison.Ordinal);
        Assert.Contains("\"voice_id\":\"voice-two\"", handler.Requests[9].Body, StringComparison.Ordinal);
        Assert.DoesNotContain("queue_item_ids", handler.Requests[9].Body, StringComparison.Ordinal);
        Assert.DoesNotContain("section_ids", handler.Requests[9].Body, StringComparison.Ordinal);
        Assert.Contains(
            handler.Requests,
            request => request.Method == HttpMethod.Delete &&
                request.Uri.AbsolutePath == "/v1/reader/exports/job/history");
    }

    [Fact]
    public async Task Validation_error_message_includes_the_first_rejected_field()
    {
        const string validationError = """
            {
              "error": {
                "type": "invalid_request",
                "message": "Request body validation failed.",
                "param": "queue_item_ids",
                "request_id": "request-validation",
                "details": {
                  "issues": [
                    {
                      "param": "queue_item_ids",
                      "message": "Input should be a valid list",
                      "type": "list_type"
                    }
                  ]
                }
              }
            }
            """;
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.BadRequest, validationError));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        var exception = await Assert.ThrowsAsync<ReaderApiException>(() =>
            client.CreateExportAsync(
                new CreateExportRequest(DocumentIds: ["doc"], AudioFormat: "mp3")));

        Assert.Equal(
            "Request body validation failed. (queue_item_ids: Input should be a valid list)",
            exception.Message);
    }

    [Fact]
    public async Task Queue_export_omits_unused_document_and_section_collections()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.Accepted, ExportJobJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        await client.CreateExportAsync(
            new CreateExportRequest(QueueItemIds: ["queue-item"], AudioFormat: "mp3"));

        var request = Assert.Single(handler.Requests);
        Assert.Contains("\"queue_item_ids\":[\"queue-item\"]", request.Body, StringComparison.Ordinal);
        Assert.DoesNotContain("document_ids", request.Body, StringComparison.Ordinal);
        Assert.DoesNotContain("section_ids", request.Body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Delete_document_uses_protected_soft_delete_contract_with_row_version()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.OK, DocumentJson));
        var client = new ReaderServiceClient(
            new HttpClient(handler),
            "http://localhost:8000/",
            new StaticTokenProvider("token"));

        var deleted = await client.DeleteDocumentAsync("doc/id", expectedRowVersion: 7);

        var request = Assert.Single(handler.Requests);
        Assert.Equal(HttpMethod.Delete, request.Method);
        Assert.Equal("/v1/reader/documents/doc%2Fid", request.Uri.AbsolutePath);
        Assert.Equal("?expected_row_version=7", request.Uri.Query);
        Assert.Equal("Bearer token", request.Authorization);
        Assert.Equal("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", deleted.Id);
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
                body,
                request.Method));
            return responseFactory(request);
        }
    }

    private sealed record RecordedRequest(
        Uri Uri,
        string? Authorization,
        string Body,
        HttpMethod Method);

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

    private const string HighlighterJson = """
        {
          "id":"global","row_version":2,"updated_at":"2026-08-18T12:00:00Z",
          "terms":[{
            "id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","term":"Mara",
            "normalized_term":"mara","active":false,"color":"#BFE8D5","ordinal":0,
            "created_at":"2026-08-18T12:00:00Z","updated_at":"2026-08-18T12:00:00Z"
          }]
        }
        """;

    private const string ImportPreviewJson = """
        {
          "preview_id":"preview-id","title":"Imported","source_type":"markdown","source_name":"book.md",
          "total_sections":1,"total_blocks":1,"total_characters":9,"warnings":[],
          "sections":[{"ordinal":0,"level":1,"heading":"Imported","first_block_ordinal":0}],
          "sample_blocks":[{"ordinal":0,"kind":"heading","text":"Heading","section_ordinal":0}],
          "preview_truncated":false,"duplicate_document_id":null,"expires_in_seconds":600
        }
        """;

    private const string RuleSetPageJson = """
        {"rule_sets":[],"rules_version":2}
        """;

    private const string RuleSetJson = """
        {
          "id":"set-id","name":"Danish","description":"","enabled":true,"scope":"language",
          "version":1,"row_version":1,"created_at":"2026-07-27T12:00:00Z","updated_at":"2026-07-27T12:00:00Z"
        }
        """;

    private const string RuleJson = """
        {
          "id":"rule-id","rule_set_id":"set-id","name":"Expand API","enabled":true,
          "stage":"pronunciation","rule_type":"literal_replace","pattern":"API","replacement":"A P I",
          "case_sensitive":false,"whole_word":false,"language_filter":"da","engine_filter":null,
          "voice_filter":null,"document_filter":null,"priority":100,"regex_timeout_ms":25,"row_version":1,
          "created_at":"2026-07-27T12:00:00Z","updated_at":"2026-07-27T12:00:00Z","raw_import_metadata":{}
        }
        """;

    private const string RulePreviewJson = """
        {
          "original_text":"API","spoken_text":"A P I",
          "source_spans":[{"start_offset":0,"end_offset":3}],"trace":[],"warnings":[],
          "elapsed_ms":0.2,"pipeline_version":1,"rules_version":2
        }
        """;

    private const string RuleImportJson = """
        {
          "source_sha256":"abc","imported":0,"disabled":0,"duplicate":0,"invalid":0,
          "unsupported":0,"committed":false,"idempotent":false
        }
        """;

    private const string BookmarkJson = """
        {
          "id":"bookmark","document_id":"doc",
          "cursor":{"document_id":"doc","block_id":"block","block_ordinal":0,"character_offset":2,"content_revision":1,"segment_index":null},
          "label":"Mark","note":"","created_at":"2026-07-27T12:00:00Z",
          "updated_at":"2026-07-27T12:00:00Z","row_version":1
        }
        """;

    private const string QueueItemJson = """
        {
          "id":"item","document_id":"doc","ordinal":0,"status":"queued",
          "added_at":"2026-07-27T12:00:00Z","updated_at":"2026-07-27T12:00:00Z","row_version":1
        }
        """;

    private const string DesktopOpenRequestJson = """
        {
          "id":"open","document_id":"doc","created_at":"2026-07-27T12:00:00Z"
        }
        """;

    private const string ExportJobJson = """
        {
          "id":"job","status":"queued","document_ids":["doc"],"section_ids":[],
          "voice_id":"voice","audio_format":"mp3","output_basename":null,"overwrite_existing":false,
          "total_documents":1,"completed_documents":0,"progress_phase":"queued","progress_percent":0,"current_document_id":null,
          "output_files":[],"error_type":null,"error_message":null,"cancel_requested":false,
          "created_at":"2026-07-27T12:00:00Z","updated_at":"2026-07-27T12:00:00Z",
          "completed_at":null,"row_version":1
        }
        """;
}
