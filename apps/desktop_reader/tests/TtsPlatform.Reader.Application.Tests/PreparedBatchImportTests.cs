using System.Text;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class PreparedBatchImportTests
{
    [Fact]
    public async Task Preview_never_writes_and_explicit_commit_returns_every_reviewed_part()
    {
        var client = new PartsClient();
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions(FolderId: "folder");
        var preview = await runner.PrepareAsync([Input("one"), Input("two")], options);
        Assert.Equal(2, preview.Ready);
        Assert.Empty(client.Commits);
        Assert.True(runner.CanCommit(options));
        Assert.All(preview.Files, file => Assert.Equal(2, file.PartsPreview!.Parts.Count));
        Assert.Contains("Navigation ignored", preview.Files[0].Message);
        var imported = await runner.CommitAsync(options);
        Assert.Equal(2, imported.Completed);
        Assert.Equal(4, imported.Documents.Count);
        Assert.All(client.Commits, commit =>
        {
            Assert.Equal(900_000, commit.Options.MaxCharacters);
            Assert.Equal(1, commit.Options.HeadingLevel);
            Assert.Equal("folder", commit.Options.FolderId);
        });
        Assert.False(runner.CanCommit(options));
        await Assert.ThrowsAsync<InvalidOperationException>(() => runner.CommitAsync(options));
    }

    [Fact]
    public async Task Option_changes_and_discard_invalidate_old_review_without_writes()
    {
        var client = new PartsClient();
        var runner = new PreparedBatchImportRunner(client);
        var input = Input("one");
        var options = new PreparedBatchImportOptions();
        await runner.PrepareAsync([input], options);
        var changed = options with { MaxCharacters = 800_000 };
        Assert.False(runner.CanCommit(changed));
        await Assert.ThrowsAsync<InvalidOperationException>(() => runner.CommitAsync(changed));
        await runner.DiscardAsync();
        Assert.False(runner.CanCommit(options));
        Assert.Null(runner.Result.Files[0].PartsPreview);
        Assert.Contains("one", client.CancelledPreviews);
        Assert.Empty(client.Commits);
        await runner.PrepareAsync([input], changed);
        Assert.True(runner.CanCommit(changed));
    }

    [Fact]
    public async Task Cancellation_discards_all_prepared_files_and_does_not_write()
    {
        var client = new PartsClient();
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        using var cancellation = new CancellationTokenSource();
        var result = await runner.PrepareAsync([Input("one"), Input("two")], options,
            file => { if (file.Status == PreparedBatchImportStatus.Ready) cancellation.Cancel(); },
            cancellation.Token);
        Assert.Equal(2, result.Cancelled);
        Assert.False(runner.CanCommit(options));
        Assert.Empty(client.Commits);
        Assert.Equal(["one"], client.Previewed);
        Assert.Contains("one", client.CancelledPreviews);
    }

    [Fact]
    public async Task Invalidation_rejects_a_late_preview_reply()
    {
        var waiting = new TaskCompletionSource<ReaderImportPartsPreview>(TaskCreationOptions.RunContinuationsAsynchronously);
        var requested = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var client = new PartsClient
        {
            PreviewParts = (_, _) => { requested.SetResult(); return waiting.Task; },
        };
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        var preparing = runner.PrepareAsync([Input("one")], options);
        await requested.Task;
        await runner.DiscardAsync();
        waiting.SetResult(PartsClient.Plan("one", options));
        var result = await preparing;
        Assert.Equal(PreparedBatchImportStatus.Cancelled, result.Files[0].Status);
        Assert.False(runner.CanCommit(options));
        Assert.Empty(client.Commits);
        Assert.Contains("one", client.CancelledPreviews);
    }

    [Fact]
    public async Task Cancelling_before_a_saving_request_does_not_send_it()
    {
        var client = new PartsClient();
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        await runner.PrepareAsync([Input("one")], options);
        using var cancellation = new CancellationTokenSource();
        var result = await runner.CommitAsync(options, file =>
        {
            if (file.Status == PreparedBatchImportStatus.Committing) cancellation.Cancel();
        }, cancellation.Token);
        Assert.Equal(1, result.Cancelled);
        Assert.Equal(0, result.Unknown);
        Assert.Empty(client.Commits);
        Assert.Contains("one", client.CancelledPreviews);
    }

    [Fact]
    public async Task Discard_during_an_active_commit_preserves_acknowledgement_and_fences_later_files()
    {
        var requested = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var response = new TaskCompletionSource<ReaderImportPartsResult>(TaskCreationOptions.RunContinuationsAsynchronously);
        var client = new PartsClient
        {
            Commit = (_, _) => { requested.SetResult(); return response.Task; },
        };
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        await runner.PrepareAsync([Input("one"), Input("two")], options);
        var committing = runner.CommitAsync(options);
        await requested.Task;
        await runner.DiscardAsync();
        response.SetResult(PartsClient.Committed("one"));
        var result = await committing;
        Assert.Equal(1, result.Completed);
        Assert.Equal(1, result.Cancelled);
        Assert.Equal(2, result.Documents.Count);
        Assert.Single(client.Commits);
        Assert.False(runner.CanCommit(options));
    }

    [Fact]
    public async Task Noncommittable_source_stays_visible_with_issues_and_valid_sources_can_import()
    {
        var client = new PartsClient
        {
            PreviewParts = (id, options) => Task.FromResult(id == "too-large"
                ? PartsClient.Plan(id, options) with { CanCommit = false, Issues = ["A complete chapter exceeds the part limit."] }
                : PartsClient.Plan(id, options)),
        };
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        var result = await runner.PrepareAsync([Input("too-large"), Input("good")], options);
        Assert.Equal(1, result.Failed);
        Assert.Equal(1, result.Ready);
        Assert.Contains("complete chapter", result.Files[0].Message);
        Assert.NotNull(result.Files[0].PartsPreview);
        Assert.Contains("too-large", client.CancelledPreviews);
        var imported = await runner.CommitAsync(options);
        Assert.Equal(1, imported.Completed);
        Assert.Single(client.Commits);
    }

    [Fact]
    public async Task Cancellation_after_acknowledgement_keeps_completed_parts_and_skips_unstarted_files()
    {
        var client = new PartsClient();
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        var inputs = new[] { Input("one"), Input("two"), Input("three") };
        await runner.PrepareAsync(inputs, options);
        using var cancellation = new CancellationTokenSource();
        var result = await runner.CommitAsync(options, file =>
        {
            if (file.Status == PreparedBatchImportStatus.Completed) cancellation.Cancel();
        }, cancellation.Token);
        Assert.Equal(1, result.Completed);
        Assert.Equal(2, result.Cancelled);
        Assert.Equal(2, result.Documents.Count);
        Assert.Single(client.Commits);
        await runner.PrepareAsync(inputs, options);
        Assert.Equal(1, runner.Result.Completed);
        Assert.Equal(2, runner.Result.Documents.Count);
        Assert.Equal(1, client.Previewed.Count(name => name == "one"));
    }

    [Theory]
    [InlineData("cancel")]
    [InlineData("transport")]
    [InlineData("server")]
    [InlineData("json")]
    public async Task Uncertain_commit_is_not_claimed_cancelled_and_stops_unstarted_work(string failure)
    {
        var client = new PartsClient
        {
            Commit = (id, _) => id == "two" ? throw failure switch
            {
                "cancel" => new OperationCanceledException(),
                "server" => new ReaderApiException("server_error", "Unknown", 500),
                "json" => new JsonException("Malformed acknowledgement"),
                _ => new ReaderServiceUnavailableException("Lost response"),
            } : Task.FromResult(PartsClient.Committed(id)),
        };
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        var inputs = new[] { Input("one"), Input("two"), Input("three") };
        await runner.PrepareAsync(inputs, options);
        var result = await runner.CommitAsync(options);
        Assert.Equal(1, result.Completed);
        Assert.Equal(1, result.Unknown);
        Assert.Equal(1, result.Cancelled);
        Assert.Equal(2, result.Documents.Count);
        Assert.Equal(2, client.Commits.Count);
        Assert.Contains("may already be saved", result.Files[1].Message);
        Assert.DoesNotContain("cancelled", result.Files[1].Message, StringComparison.OrdinalIgnoreCase);
        await runner.PrepareAsync(inputs, options);
        Assert.Equal(PreparedBatchImportStatus.OutcomeUnknown, runner.Result.Files[1].Status);
        Assert.Equal(1, client.Previewed.Count(name => name == "two"));
    }

    [Theory]
    [InlineData(400)]
    [InlineData(404)]
    [InlineData(409)]
    public async Task Expired_or_stale_file_fails_actionably_without_losing_other_files(int status)
    {
        var client = new PartsClient
        {
            Commit = (id, _) => id == "one"
                ? throw new ReaderApiException("preview_missing", "Unavailable", status)
                : Task.FromResult(PartsClient.Committed(id)),
        };
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        await runner.PrepareAsync([Input("one"), Input("two")], options);
        var result = await runner.CommitAsync(options);
        Assert.Equal(1, result.Failed);
        Assert.Equal(1, result.Completed);
        Assert.Equal(0, result.Unknown);
        Assert.Contains("preview", result.Files[0].Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Capacity_and_source_failures_do_not_block_valid_reviewed_files()
    {
        var client = new PartsClient
        {
            PreviewParts = (id, options) => id == "capacity"
                ? throw new ReaderApiException("preview_capacity", "Preview capacity reached", 413)
                : Task.FromResult(PartsClient.Plan(id, options)),
        };
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        var broken = new BatchImportInput("broken", "text/plain", "broken", () => throw new IOException("Unreadable file"));
        var result = await runner.PrepareAsync([Input("good"), Input("capacity"), broken], options);
        Assert.Equal(1, result.Ready);
        Assert.Equal(2, result.Failed);
        Assert.True(runner.CanCommit(options));
        Assert.Contains("capacity", client.CancelledPreviews);
        var imported = await runner.CommitAsync(options);
        Assert.Equal(1, imported.Completed);
        Assert.Equal(2, imported.Failed);
        Assert.Single(client.Commits);
    }

    [Fact]
    public async Task Duplicate_content_requires_checkbox_and_a_fresh_matching_review()
    {
        var client = new PartsClient { Duplicate = true };
        var runner = new PreparedBatchImportRunner(client);
        var input = Input("one");
        var options = new PreparedBatchImportOptions();
        var result = await runner.PrepareAsync([input], options);
        Assert.Contains("Duplicate content", result.Files[0].Message);
        Assert.False(runner.CanCommit(options));
        await Assert.ThrowsAsync<InvalidOperationException>(() => runner.CommitAsync(options));
        var approved = options with { AllowDuplicate = true };
        await Assert.ThrowsAsync<InvalidOperationException>(() => runner.CommitAsync(approved));
        await runner.PrepareAsync([input], approved);
        Assert.True(runner.CanCommit(approved));
        await runner.CommitAsync(approved);
        Assert.True(client.Commits[0].Options.AllowDuplicate);
    }

    [Theory]
    [InlineData(0, 1)]
    [InlineData(1_000_001, 1)]
    [InlineData(900_000, 0)]
    [InlineData(900_000, 10)]
    public async Task Invalid_options_never_reach_upload_or_write(int maximum, int level)
    {
        var client = new PartsClient();
        var runner = new PreparedBatchImportRunner(client);
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() => runner.PrepareAsync(
            [Input("one")], new PreparedBatchImportOptions(maximum, level)));
        Assert.Empty(client.Previewed);
        Assert.Empty(client.Commits);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(101)]
    public async Task Batch_file_count_is_bounded_before_upload(int count)
    {
        var client = new PartsClient();
        var runner = new PreparedBatchImportRunner(client);
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() => runner.PrepareAsync(
            Enumerable.Range(0, count).Select(index => Input(index.ToString())).ToArray(), new()));
        Assert.Empty(client.Previewed);
    }

    [Fact]
    public async Task Duplicate_document_acknowledgements_are_unknown_and_stop_remaining_files()
    {
        var saved = PartsClient.Committed("one").Documents[0];
        var client = new PartsClient { Commit = (_, _) => Task.FromResult(new ReaderImportPartsResult([saved, saved])) };
        var runner = new PreparedBatchImportRunner(client);
        var options = new PreparedBatchImportOptions();
        await runner.PrepareAsync([Input("one"), Input("two")], options);
        var result = await runner.CommitAsync(options);
        Assert.Equal(1, result.Unknown);
        Assert.Equal(1, result.Cancelled);
        Assert.Empty(result.Documents);
        Assert.Single(client.Commits);
    }

    private static BatchImportInput Input(string name) => new(name, "text/plain", name,
        () => new MemoryStream(Encoding.UTF8.GetBytes("Chapter content.")));

    private sealed class PartsClient : IReaderServiceClient
    {
        public List<string> Previewed { get; } = [];
        public List<string> CancelledPreviews { get; } = [];
        public List<(string Id, PreparedBatchImportOptions Options)> Commits { get; } = [];
        public Func<string, PreparedBatchImportOptions, Task<ReaderImportPartsPreview>>? PreviewParts { get; init; }
        public Func<string, PreparedBatchImportOptions, Task<ReaderImportPartsResult>>? Commit { get; init; }
        public bool Duplicate { get; init; }

        public Task<ReaderImportPreview> PreviewImportAsync(ImportDocumentRequest request, Stream content,
            CancellationToken cancellationToken = default)
        {
            Previewed.Add(request.FileName);
            return Task.FromResult(new ReaderImportPreview(request.FileName, request.Title!, "text_file",
                request.FileName, 2, 4, 100, [new("navigation", "Navigation ignored", 1)], [], [], false,
                Duplicate ? "existing" : null, 600));
        }

        public Task<ReaderImportPartsPreview> PreviewImportPartsAsync(string previewId,
            int maxCharacters = 900000, int headingLevel = 1, CancellationToken cancellationToken = default)
        {
            var options = new PreparedBatchImportOptions(maxCharacters, headingLevel);
            return PreviewParts?.Invoke(previewId, options) ?? Task.FromResult(Plan(previewId, options));
        }

        public Task<ReaderImportPartsResult> CommitImportPartsAsync(string previewId, string planKey,
            int maxCharacters = 900000, int headingLevel = 1, bool allowDuplicate = false,
            string? folderId = null, CancellationToken cancellationToken = default)
        {
            Assert.Equal("plan-" + previewId, planKey);
            var options = new PreparedBatchImportOptions(maxCharacters, headingLevel, folderId, allowDuplicate);
            Commits.Add((previewId, options));
            return Commit?.Invoke(previewId, options) ?? Task.FromResult(Committed(previewId));
        }

        public Task CancelImportAsync(string previewId, CancellationToken cancellationToken = default)
        {
            CancelledPreviews.Add(previewId);
            return Task.CompletedTask;
        }

        public static ReaderImportPartsPreview Plan(string id, PreparedBatchImportOptions options) =>
            new(id, "plan-" + id, options.MaxCharacters, options.HeadingLevel, 2,
                [new(1, id + " - Part 1", 1, 1, "One", "One", 50, 51, 2, "hash1"),
                 new(2, id + " - Part 2", 2, 2, "Two", "Two", 50, 51, 2, "hash2")], true, []);

        public static ReaderImportPartsResult Committed(string id) => new([Document(id + "-1"), Document(id + "-2")]);
        private static ReaderDocument Document(string id) => new(id, id, "text_file", null, null, null, null,
            "inbox", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null,
            1, 1, 1, 2, 50, JsonDocument.Parse("{}").RootElement.Clone());

        public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderCapabilities> GetCapabilitiesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderDocument> CreateDocumentAsync(CreateDocumentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DocumentPage> GetDocumentsAsync(int limit = 50, string? cursor = null, string? query = null, string? state = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<BlockPage> GetBlocksAsync(string documentId, int afterOrdinal = -1, int limit = 200, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> ReplaceContentAsync(string documentId, ReplaceContentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> AppendContentAsync(string documentId, AppendContentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> UndoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> RedoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition?> GetPositionAsync(string documentId, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition> SavePositionAsync(string documentId, SavePositionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<byte[]> SynthesizeAsync(EphemeralSynthesisRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}
