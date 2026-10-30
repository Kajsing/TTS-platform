using System.Collections.Concurrent;
using System.Net;
using System.Text;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class ReadCoalescingTests
{
    [Fact]
    public async Task Overlapping_reads_share_one_request_without_caching_completed_results()
    {
        var handler = new HeldHandler();
        var client = Client(handler);
        var reads = Enumerable.Range(0, 12).Select(_ => client.GetCapabilitiesAsync()).ToArray();
        await handler.WaitForSendAsync();
        Assert.Equal(1, handler.Calls);
        handler.Release.TrySetResult();
        await Task.WhenAll(reads);
        await client.GetCapabilitiesAsync();
        Assert.Equal(2, handler.Calls);
    }

    [Fact]
    public async Task Cancelling_one_waiter_preserves_the_physical_read_for_the_other()
    {
        var handler = new HeldHandler();
        var client = Client(handler);
        using var cancel = new CancellationTokenSource();
        var first = client.GetCapabilitiesAsync(cancel.Token);
        var second = client.GetCapabilitiesAsync();
        await handler.WaitForSendAsync();
        cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first);
        Assert.False(handler.Cancelled.Task.IsCompleted);
        handler.Release.TrySetResult();
        await second;
        Assert.Equal(1, handler.Calls);
    }

    [Fact]
    public async Task Last_waiter_cancellation_aborts_network_and_next_read_starts_fresh()
    {
        var handler = new HeldHandler();
        var client = Client(handler);
        using var cancel = new CancellationTokenSource();
        var first = client.GetCapabilitiesAsync(cancel.Token);
        var second = client.GetCapabilitiesAsync(cancel.Token);
        await handler.WaitForSendAsync();
        cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => second);
        await handler.Cancelled.Task.WaitAsync(TimeSpan.FromSeconds(5));
        handler.Release.TrySetResult();
        await client.GetCapabilitiesAsync();
        Assert.Equal(2, handler.Calls);
    }

    [Fact]
    public async Task Failed_reads_are_shared_only_while_pending_and_can_be_retried_fresh()
    {
        var handler = new HeldHandler { Status = HttpStatusCode.InternalServerError };
        var client = Client(handler);
        var first = client.GetCapabilitiesAsync();
        var second = client.GetCapabilitiesAsync();
        await handler.WaitForSendAsync();
        handler.Release.TrySetResult();
        await Assert.ThrowsAsync<ReaderApiException>(() => first);
        await Assert.ThrowsAsync<ReaderApiException>(() => second);
        Assert.Equal(1, handler.Calls);
        handler.Status = HttpStatusCode.OK;
        await client.GetCapabilitiesAsync();
        Assert.Equal(2, handler.Calls);
    }

    [Fact]
    public async Task Revision_fence_and_service_activity_reads_never_join_older_pending_reads()
    {
        var handler = new HeldHandler();
        var client = Client(handler);
        var old = client.GetDocumentAsync("doc");
        var fresh = client.GetDocumentFreshAsync("doc");
        await handler.WaitForSendAsync();
        await handler.WaitForSendAsync();
        Assert.Equal(2, handler.Calls);
        handler.Release.TrySetResult();
        await Task.WhenAll(old, fresh);

        var statusHandler = new HeldHandler();
        var statusClient = Client(statusHandler);
        var status1 = statusClient.GetLocalStatusAsync();
        var status2 = statusClient.GetLocalStatusAsync();
        await statusHandler.WaitForSendAsync();
        await statusHandler.WaitForSendAsync();
        Assert.Equal(2, statusHandler.Calls);
        statusHandler.Release.TrySetResult();
        await Task.WhenAll(status1, status2);
    }

    [Fact]
    public async Task Different_documents_credentials_and_privacy_contexts_are_not_shared()
    {
        var handler = new HeldHandler();
        var token = new Token();
        using var privacy = new ReaderPrivacySessionStore();
        var client = Client(handler, token, privacy);
        var first = client.GetDocumentAsync("doc");
        var differentQuery = client.GetDocumentAsync("other-doc");
        token.Value = "rotated";
        var differentToken = client.GetDocumentAsync("doc");
        privacy.Store(new("folder", "privacy-token", DateTimeOffset.UtcNow.AddMinutes(5), 300));
        var differentPrivacy = client.GetDocumentAsync("doc");
        await handler.WaitForSendAsync();
        await handler.WaitForSendAsync();
        handler.Release.TrySetResult();
        await Task.WhenAll(first, differentQuery, differentToken, differentPrivacy);
        Assert.Equal(4, handler.Calls);
        Assert.Contains(handler.Identities, value => value.Contains("Bearer owner", StringComparison.Ordinal));
        Assert.Contains(handler.Identities, value => value.Contains("Bearer rotated", StringComparison.Ordinal));
        Assert.Contains(handler.Identities, value => value.Contains("privacy-token", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Writes_invalidate_old_read_identity_and_are_never_coalesced()
    {
        var handler = new HeldHandler { ReleaseWrites = true };
        var client = Client(handler);
        var old = client.GetDocumentAsync("doc");
        await handler.WaitForSendAsync();
        await client.UpdateDocumentAsync("doc", new UpdateDocumentRequest(1, Title: "Changed"));
        await client.UpdateDocumentAsync("doc", new UpdateDocumentRequest(2, Title: "Changed again"));
        var afterWrites = client.GetDocumentAsync("doc");
        await handler.WaitForSendAsync();
        await handler.WaitForSendAsync();
        await handler.WaitForSendAsync();
        Assert.Equal(4, handler.Calls);
        handler.Release.TrySetResult();
        await Task.WhenAll(old, afterWrites);
    }

    [Fact]
    public async Task Shared_waiters_are_bounded_and_a_full_group_does_not_cancel_others()
    {
        var handler = new HeldHandler();
        var client = Client(handler);
        var readers = Enumerable.Range(0, 16).Select(_ => client.GetCapabilitiesAsync()).ToArray();
        var error = await Assert.ThrowsAsync<ReaderApiException>(() => client.GetCapabilitiesAsync());
        Assert.Equal("reader_request_queue_full", error.ErrorType);
        Assert.Equal(1, handler.Calls);
        handler.Release.TrySetResult();
        await Task.WhenAll(readers);
        await client.GetCapabilitiesAsync();
        Assert.Equal(2, handler.Calls);
    }

    [Fact]
    public async Task New_snapshot_does_not_join_a_page_started_before_an_external_revision_change()
    {
        var handler = new RevisionHandler();
        var client = new ReaderServiceClient(new HttpClient(handler), "http://localhost:7777", new Token());
        var oldPage = client.GetBlocksAsync("doc", limit: 2);
        await handler.OldPageStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        try
        {
            handler.Revision = 2; // Another client/agent writes; this client's mutation epoch is unchanged.
            var before = await client.GetDocumentAsync("doc");
            Assert.Equal(2, before.ContentRevision);
            var pageForNewSnapshot = client.GetBlocksAsync("doc", limit: 2);
            await handler.NewPageStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Equal(2, handler.PageCalls);
            var page = await pageForNewSnapshot;
            var after = await client.GetDocumentFreshAsync("doc");
            Assert.Equal(before.ContentRevision, after.ContentRevision);
            Assert.Equal("revision 2", Assert.Single(page.Blocks).Text);
        }
        finally { handler.ReleaseOldPage.TrySetResult(); }
        Assert.Equal("revision 1", Assert.Single((await oldPage).Blocks).Text);
    }

    private static ReaderServiceClient Client(HeldHandler handler, Token? token = null,
        ReaderPrivacySessionStore? privacy = null) =>
        new(new HttpClient(handler), "http://localhost:7777", token ?? new Token(), privacy);

    private sealed class Token : ITokenProvider
    {
        public string Value = "owner";
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) =>
            ValueTask.FromResult<string?>(Value);
    }

    private sealed class RevisionHandler : HttpMessageHandler
    {
        private int _pageCalls;
        public int Revision = 1;
        public int PageCalls => Volatile.Read(ref _pageCalls);
        public TaskCompletionSource OldPageStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource NewPageStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource ReleaseOldPage { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var revision = Volatile.Read(ref Revision);
            string body;
            if (request.RequestUri!.AbsolutePath.EndsWith("/blocks", StringComparison.Ordinal))
            {
                if (Interlocked.Increment(ref _pageCalls) == 1)
                {
                    OldPageStarted.TrySetResult();
                    await ReleaseOldPage.Task.WaitAsync(cancellationToken);
                }
                else NewPageStarted.TrySetResult();
                body = "{\"blocks\":[{\"id\":\"block\",\"document_id\":\"doc\",\"ordinal\":0,\"kind\":\"paragraph\",\"text\":\"revision " +
                    revision + "\",\"character_count\":10,\"row_version\":" + revision + "}],\"next_after_ordinal\":null}";
            }
            else body = "{\"id\":\"doc\",\"content_revision\":" + revision + ",\"row_version\":" + revision + "}";
            return new(HttpStatusCode.OK) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        }
    }

    private sealed class HeldHandler : HttpMessageHandler
    {
        private int _calls;
        private readonly SemaphoreSlim _sent = new(0);
        public int Calls => Volatile.Read(ref _calls);
        public bool ReleaseWrites;
        public HttpStatusCode Status = HttpStatusCode.OK;
        public ConcurrentQueue<string> Identities { get; } = new();
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Cancelled { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task WaitForSendAsync() => Assert.True(await _sent.WaitAsync(TimeSpan.FromSeconds(5)));

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _calls);
            Identities.Enqueue(request.RequestUri + " " + request.Headers.Authorization + " " +
                (request.Headers.TryGetValues(ReaderPrivacySessionStore.HeaderName, out var privacy) ? string.Join(',', privacy) : ""));
            _sent.Release();
            try
            {
                if (!ReleaseWrites || request.Method == HttpMethod.Get)
                    await Release.Task.WaitAsync(cancellationToken);
            }
            catch (OperationCanceledException) { Cancelled.TrySetResult(); throw; }
            var body = Status == HttpStatusCode.OK
                ? request.RequestUri!.AbsolutePath.EndsWith("/blocks", StringComparison.Ordinal)
                    ? "{\"blocks\":[],\"next_after_ordinal\":null}" : "{}"
                : "{\"error\":{\"type\":\"synthetic_failure\",\"message\":\"Failed\"}}";
            return new(Status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        }
    }
}
