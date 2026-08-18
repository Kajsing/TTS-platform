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
    public async Task Onboarding_reports_rate_limit_as_transient()
    {
        var client = new StubClient
        {
            Health = Healthy(),
            CapabilitiesException = new ReaderApiException(
                "rate_limited",
                "Rate limit exceeded.",
                429),
        };

        var result = await new OnboardingCoordinator(client).CheckAsync();

        Assert.Equal(ConnectionState.RateLimited, result.State);
        Assert.Equal(SuggestedAction.Retry, result.Action);
        Assert.Contains("about a minute", result.Message);
    }

    [Fact]
    public void Desktop_connection_policy_only_reconnects_for_service_or_token_changes()
    {
        var settings = new DesktopSettings(
            ServiceBaseUrl: "http://127.0.0.1:7777/",
            TokenSource: new TokenSourceSettings("file", @"C:\safe\token.txt"),
            PreferredVoiceId: "voice-a");

        Assert.False(DesktopConnectionPolicy.RequiresReconnect(
            settings with { PreferredVoiceId = "voice-b" },
            "http://127.0.0.1:7777/",
            @"C:\SAFE\TOKEN.TXT"));
        Assert.True(DesktopConnectionPolicy.RequiresReconnect(
            settings,
            "http://127.0.0.1:7788/",
            @"C:\safe\token.txt"));
        Assert.True(DesktopConnectionPolicy.RequiresReconnect(
            settings,
            "http://127.0.0.1:7777/",
            @"C:\safe\other-token.txt"));
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
    public async Task Library_replaces_a_mutated_document_without_an_api_refresh()
    {
        var client = new StubClient
        {
            DocumentPages = new Queue<DocumentPage>(
                [new DocumentPage([Document("one", 1)], null)]),
        };
        var pager = new LibraryPager(client);
        await pager.RefreshAsync();
        var updated = Document("one", 2) with { Title = "Updated" };

        var replaced = pager.ReplaceDocument(updated);

        Assert.True(replaced);
        Assert.Same(updated, pager.Documents.Single());
        Assert.Single(client.ReceivedCursors);
    }

    [Fact]
    public async Task Library_preserves_folder_filter_across_pages()
    {
        var client = new StubClient
        {
            DocumentPages = new Queue<DocumentPage>(
            [
                new DocumentPage([Document("one", 1)], "next"),
                new DocumentPage([Document("two", 1)], null),
            ]),
        };
        var pager = new LibraryPager(client, 1);

        await pager.RefreshAsync(folderId: "folder-id");
        await pager.LoadMoreAsync();

        Assert.Equal(["folder-id", "folder-id"], client.ReceivedFolderIds);
    }

    [Fact]
    public void Library_updates_observable_collection_on_calling_synchronization_context()
    {
        var previousContext = SynchronizationContext.Current;
        using var context = new PumpSynchronizationContext();
        SynchronizationContext.SetSynchronizationContext(context);

        try
        {
            var pageCompletion = new TaskCompletionSource<DocumentPage>(
                TaskCreationOptions.RunContinuationsAsynchronously);
            var client = new StubClient { PendingDocumentPage = pageCompletion.Task };
            var pager = new LibraryPager(client, 1);
            var callingThreadId = Environment.CurrentManagedThreadId;
            var notificationThreadId = 0;
            pager.Documents.CollectionChanged += (_, _) =>
                notificationThreadId = Environment.CurrentManagedThreadId;

            var refresh = pager.RefreshAsync();
            ThreadPool.QueueUserWorkItem(
                _ => pageCompletion.SetResult(new DocumentPage([Document("one", 1)], null)));

            context.RunUntil(refresh);

            Assert.True(refresh.IsCompletedSuccessfully, refresh.Exception?.ToString());
            Assert.Equal(callingThreadId, notificationThreadId);
            Assert.True(context.PostCount > 0);
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(previousContext);
        }
    }

    [Fact]
    public async Task Reading_window_pages_book_scale_content_without_materializing_the_document()
    {
        var first = Enumerable.Range(0, 64).Select(index => Block($"Block {index}", index)).ToArray();
        var second = Enumerable.Range(64, 64).Select(index => Block($"Block {index}", index)).ToArray();
        var client = new StubClient
        {
            BlockPages = new Queue<BlockPage>(
            [
                new BlockPage(first, 63),
                new BlockPage(second, 127),
                new BlockPage(first, 63),
            ]),
        };
        var pager = new ReadingWindowPager(client);

        var initial = await pager.LoadAsync("document", 0);
        var next = await pager.LoadNextAsync("document");
        var previous = await pager.LoadPreviousAsync("document");

        Assert.Equal(64, initial.Blocks.Count);
        Assert.Equal(64, next.StartOrdinal);
        Assert.Equal(0, previous.StartOrdinal);
        Assert.Equal([-1, 63, -1], client.ReceivedBlockAfterOrdinals);
        Assert.All(client.ReceivedBlockLimits, limit => Assert.Equal(64, limit));
    }

    [Fact]
    public async Task Find_loader_materializes_every_paged_block_and_caches_the_revision()
    {
        var blocks = Enumerable.Range(0, 7)
            .Select(index => Block(index == 6 ? "final needle" : $"Block {index}", index) with
            {
                Id = $"block-{index}",
            })
            .ToArray();
        var client = new StubClient { PaginatedBlocks = blocks };
        var document = Document("doc", 3, "html") with
        {
            ContentRevision = 8,
            TotalBlocks = blocks.Length,
            TotalCharacters = blocks.Sum(block => block.Text.Length),
        };
        var loader = new ArticleFindDocumentLoader(client, pageSize: 2);

        var loaded = await loader.LoadAsync(document);
        var result = ArticleFindEngine.Search(loaded.Text, "needle");
        var location = loaded.Locate(Assert.Single(result.Matches));
        _ = await loader.LoadAsync(document);

        Assert.Equal(7, loaded.Blocks.Count);
        Assert.Equal(6, location.StartCursor.BlockOrdinal);
        Assert.Equal([-1, 1, 3, 5], client.ReceivedBlockAfterOrdinals);
        Assert.All(client.ReceivedBlockLimits, limit => Assert.Equal(2, limit));
    }

    [Fact]
    public async Task Reading_window_reuses_a_loaded_editable_document_without_more_api_calls()
    {
        var blocks = Enumerable.Range(0, 130).Select(index => Block($"Block {index}", index)).ToArray();
        var client = new StubClient();
        var pager = new ReadingWindowPager(client);

        var initial = pager.UseLoadedDocument("document", blocks);
        var next = await pager.LoadNextAsync("document");
        var last = await pager.LoadNextAsync("document");
        var previous = await pager.LoadPreviousAsync("document");

        Assert.Equal(64, initial.Blocks.Count);
        Assert.Equal(64, next.StartOrdinal);
        Assert.Equal(2, last.Blocks.Count);
        Assert.Equal(64, previous.StartOrdinal);
        Assert.Empty(client.ReceivedBlockAfterOrdinals);
    }

    [Fact]
    public async Task Reading_window_prefetches_with_context_before_playback_reaches_the_page_end()
    {
        var blocks = Enumerable.Range(0, 150).Select(index => Block($"Block {index}", index)).ToArray();
        var client = new StubClient();
        var pager = new ReadingWindowPager(client);
        pager.UseLoadedDocument("document", blocks);

        var unchanged = await pager.FollowPlaybackAsync("document", 40);
        var advanced = await pager.FollowPlaybackAsync("document", 56);

        Assert.Equal(0, unchanged.StartOrdinal);
        Assert.Equal(40, advanced.StartOrdinal);
        Assert.Equal(40, advanced.Blocks.First().Ordinal);
        Assert.Equal(103, advanced.Blocks.Last().Ordinal);
        Assert.Contains(56, advanced.Blocks.Select(block => block.Ordinal));
        Assert.Empty(client.ReceivedBlockAfterOrdinals);
    }

    [Fact]
    public async Task Reading_window_finds_the_next_section_beyond_the_current_api_page()
    {
        var blocks = Enumerable.Range(0, 600)
            .Select(index => Block($"Block {index}", index) with
            {
                Id = $"block-{index}",
                SectionId = index < 400 ? "section-a" : "section-b",
            })
            .ToArray();
        var client = new StubClient { PaginatedBlocks = blocks };
        var pager = new ReadingWindowPager(client);

        var target = await pager.FindNextSectionAsync("document", 20);

        Assert.NotNull(target);
        Assert.Equal(400, target.Ordinal);
        Assert.Equal("section-b", target.SectionId);
        Assert.Equal([19, 275], client.ReceivedBlockAfterOrdinals);
    }

    [Fact]
    public async Task Reading_window_finds_the_start_of_a_previous_section_across_api_pages()
    {
        var blocks = Enumerable.Range(0, 600)
            .Select(index => Block($"Block {index}", index) with
            {
                Id = $"block-{index}",
                SectionId = index < 20
                    ? "section-a"
                    : index < 500
                        ? "section-b"
                        : "section-c",
            })
            .ToArray();
        var client = new StubClient { PaginatedBlocks = blocks };
        var pager = new ReadingWindowPager(client);

        var target = await pager.FindPreviousSectionAsync("document", 530);

        Assert.NotNull(target);
        Assert.Equal(20, target.Ordinal);
        Assert.Equal("section-b", target.SectionId);
        Assert.Equal([529, 273, 17], client.ReceivedBlockAfterOrdinals);
    }

    [Fact]
    public async Task Reading_window_uses_loaded_blocks_for_section_navigation()
    {
        var blocks = Enumerable.Range(0, 9)
            .Select(index => Block($"Block {index}", index) with
            {
                Id = $"block-{index}",
                SectionId = index < 3
                    ? "section-a"
                    : index < 6
                        ? "section-b"
                        : "section-c",
            })
            .ToArray();
        var client = new StubClient();
        var pager = new ReadingWindowPager(client);
        pager.UseLoadedDocument("document", blocks);

        var next = await pager.FindNextSectionAsync("document", 4);
        var previous = await pager.FindPreviousSectionAsync("document", 4);

        Assert.Equal(6, next?.Ordinal);
        Assert.Equal(0, previous?.Ordinal);
        Assert.Empty(client.ReceivedBlockAfterOrdinals);
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
        var client = new StubClient
        {
            Blocks = new BlockPage([Block("book", documentId: "book")], null),
        };
        var editor = new DocumentEditor(client);
        await editor.LoadAsync(Document("book", 2, "epub"));

        editor.SetWorkingText("changed");
        var result = await editor.SaveAsync();

        Assert.False(editor.IsEditable);
        Assert.False(result.Saved);
        Assert.Equal("book", editor.WorkingText);
        Assert.Null(client.LastReplaceRequest);
    }

    [Fact]
    public async Task Editor_can_select_a_later_visible_block_without_flattening_the_document()
    {
        var first = Block("first", 0);
        var later = Block("later text", 7) with { Id = "later-block" };
        var document = Document("doc", 3);
        var client = new StubClient { Blocks = new BlockPage([first], null) };
        var editor = new DocumentEditor(client);
        await editor.LoadAsync(document);

        editor.LoadBlock(document, later);
        Assert.Equal("later text", editor.OriginalText);
        editor.SetWorkingText("edited later text");
        var result = await editor.SaveAsync();

        Assert.True(result.Saved);
        Assert.Equal("later-block", client.LastReplaceRequest?.BlockId);
        Assert.Equal("edited later text", editor.OriginalText);
        Assert.Equal("edited later text", editor.WorkingText);
    }

    [Fact]
    public async Task Editor_saves_cross_paragraph_deletion_as_one_range_request()
    {
        var first = Block("first", 0);
        var last = Block("third", 2) with { Id = "last-block" };
        var client = new StubClient { Blocks = new BlockPage([first], null) };
        var editor = new DocumentEditor(client);
        await editor.LoadAsync(Document("doc", 4));
        var deletion = new ContinuousRangeDeletion(first, 2, last, 2, "fiird");
        editor.SetRangeDeletion(deletion);

        var result = await editor.SaveAsync();

        Assert.True(result.Saved);
        Assert.Same(deletion, result.AppliedRangeDeletion);
        Assert.Equal(first.Id, client.LastReplaceRequest?.BlockId);
        Assert.Equal(last.Id, client.LastReplaceRequest?.EndBlockId);
        Assert.Equal(2, client.LastReplaceRequest?.StartOffset);
        Assert.Equal(2, client.LastReplaceRequest?.EndOffset);
        Assert.Equal(string.Empty, client.LastReplaceRequest?.ReplacementText);
        Assert.Equal("fiird", editor.WorkingText);
        Assert.Null(editor.PendingRangeDeletion);
    }

    [Fact]
    public async Task Rename_trims_the_title_and_uses_the_document_row_version()
    {
        var document = Document("doc", 4);
        var client = new StubClient { Blocks = new BlockPage([Block("text")], null) };
        var editor = new DocumentEditor(client);
        await editor.LoadAsync(document);

        var result = await editor.RenameAsync("  A useful title  ");

        Assert.True(result.Saved);
        Assert.Equal("A useful title", editor.Document?.Title);
        Assert.Equal(4, client.LastUpdateRequest?.ExpectedRowVersion);
        Assert.Equal("A useful title", client.LastUpdateRequest?.Title);
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

    private static ReaderBlock Block(string text, int ordinal = 0, string documentId = "doc") => new(
        "block",
        documentId,
        null,
        ordinal,
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
        public Task<DocumentPage>? PendingDocumentPage { get; init; }
        public BlockPage Blocks { get; init; } = new([], null);
        public Queue<BlockPage> BlockPages { get; init; } = new();
        public IReadOnlyList<ReaderBlock>? PaginatedBlocks { get; init; }
        public ReaderApiException? ReplaceException { get; init; }
        public ReplaceContentRequest? LastReplaceRequest { get; private set; }
        public UpdateDocumentRequest? LastUpdateRequest { get; private set; }
        public List<string?> ReceivedCursors { get; } = [];
        public List<string?> ReceivedFolderIds { get; } = [];
        public List<int> ReceivedBlockAfterOrdinals { get; } = [];
        public List<int> ReceivedBlockLimits { get; } = [];

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
            return PendingDocumentPage ?? Task.FromResult(DocumentPages.Dequeue());
        }

        public Task<DocumentPage> GetDocumentsByFolderAsync(
            int limit = 50,
            string? cursor = null,
            string? query = null,
            string? state = null,
            string? folderId = null,
            CancellationToken cancellationToken = default)
        {
            ReceivedFolderIds.Add(folderId);
            return GetDocumentsAsync(limit, cursor, query, state, cancellationToken);
        }

        public Task<ReaderDocument> UpdateDocumentAsync(
            string documentId,
            UpdateDocumentRequest request,
            CancellationToken cancellationToken = default)
        {
            LastUpdateRequest = request;
            return Task.FromResult(
                Document(documentId, request.ExpectedRowVersion + 1) with
                {
                    Title = request.Title ?? documentId,
                    State = request.State ?? "inbox",
                });
        }

        public Task<BlockPage> GetBlocksAsync(
            string documentId,
            int afterOrdinal = -1,
            int limit = 200,
            CancellationToken cancellationToken = default)
        {
            ReceivedBlockAfterOrdinals.Add(afterOrdinal);
            ReceivedBlockLimits.Add(limit);
            if (PaginatedBlocks is not null)
            {
                var blocks = PaginatedBlocks
                    .Where(block => block.Ordinal > afterOrdinal)
                    .OrderBy(block => block.Ordinal)
                    .Take(limit)
                    .ToArray();
                var hasNext = blocks.Length > 0 &&
                    PaginatedBlocks.Any(block => block.Ordinal > blocks[^1].Ordinal);
                return Task.FromResult(new BlockPage(
                    blocks,
                    hasNext ? blocks[^1].Ordinal : null));
            }
            return Task.FromResult(BlockPages.Count > 0 ? BlockPages.Dequeue() : Blocks);
        }

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

    private sealed class PumpSynchronizationContext : SynchronizationContext, IDisposable
    {
        private readonly Queue<(SendOrPostCallback Callback, object? State)> _callbacks = new();
        private readonly AutoResetEvent _callbackAvailable = new(false);

        public int PostCount { get; private set; }

        public override void Post(SendOrPostCallback callback, object? state)
        {
            lock (_callbacks)
            {
                _callbacks.Enqueue((callback, state));
                PostCount++;
            }

            _callbackAvailable.Set();
        }

        public void RunUntil(Task task)
        {
            while (!task.IsCompleted)
            {
                if (TryRunOne())
                {
                    continue;
                }

                _callbackAvailable.WaitOne(TimeSpan.FromSeconds(1));
            }

            while (TryRunOne())
            {
            }
        }

        public void Dispose() => _callbackAvailable.Dispose();

        private bool TryRunOne()
        {
            (SendOrPostCallback Callback, object? State) workItem;
            lock (_callbacks)
            {
                if (_callbacks.Count == 0)
                {
                    return false;
                }

                workItem = _callbacks.Dequeue();
            }

            workItem.Callback(workItem.State);
            return true;
        }
    }
}
