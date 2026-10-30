using System.Diagnostics;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

internal static class DocumentCallsSmoke
{
    public static async Task<int> RunAsync(string baseUrl, ITokenProvider tokenProvider)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        var token = new FixedToken(await tokenProvider.GetTokenAsync(timeout.Token));
        var counter = new CountingHandler();
        using var http = new HttpClient(counter) { Timeout = TimeSpan.FromSeconds(10) };
        var client = new ReaderServiceClient(http, baseUrl, token);
        var duplicateReads = Enumerable.Range(0, 8).Select(_ => client.GetCapabilitiesAsync(timeout.Token)).ToArray();
        Require(counter.Count == 1);
        counter.Release.TrySetResult();
        await Task.WhenAll(duplicateReads);
        Require(counter.Count == 1);
        await client.GetCapabilitiesAsync(timeout.Token);
        Require(counter.Count == 2); // Completed responses are never reused.

        var document = (await client.GetDocumentsAsync(limit: 1, query: "Bounded document fixture",
            cancellationToken: timeout.Token)).Documents.Single();
        Require(document.TotalCharacters > 2_000_000);
        var before = counter.Count;
        var allocatedBefore = GC.GetTotalAllocatedBytes();
        var timer = Stopwatch.StartNew();
        var loaded = await new ReaderDocumentLoader(client).LoadAsync(document, timeout.Token);
        var loadMs = timer.Elapsed.TotalMilliseconds;
        var allocatedBytes = GC.GetTotalAllocatedBytes() - allocatedBefore;
        var loadCalls = counter.Count - before;
        Require(loaded.ContinuousText is null && loaded.Page.Blocks.Count == 64);
        var retainedCharacters = loaded.Page.Blocks.Sum(block => block.Text.Length);
        Require(retainedCharacters < 100_000);
        Require(loadCalls == 2); // One bounded page and one fresh revision fence.
        before = counter.Count;
        var follows = Enumerable.Range(0, 8).Select(_ => loaded.ReadingWindow.FollowPlaybackAsync(
            document.Id, 60, cancellationToken: timeout.Token)).ToArray();
        await Task.WhenAll(follows);
        var followCalls = counter.Count - before;
        Require(followCalls == 1 && loaded.ReadingWindow.Current.Blocks.Count == 64);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            bounded_document_calls = true,
            overlapping_logical_reads = 8,
            overlapping_physical_reads = 1,
            initial_load_calls_with_metadata = loadCalls,
            overlapping_follow_calls = followCalls,
            source_characters = document.TotalCharacters,
            retained_blocks = loaded.Page.Blocks.Count,
            retained_source_characters = retainedCharacters,
            load_ms = Math.Round(loadMs, 2),
            observed_client_allocations_bytes = allocatedBytes,
        }));
        return 0;
    }

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidOperationException("Bounded document-call acceptance failed.");
    }

    private sealed class FixedToken(string? value) : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult(value);
    }

    private sealed class CountingHandler : DelegatingHandler
    {
        private int _count;
        public int Count => Volatile.Read(ref _count);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public CountingHandler() : base(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false }) { }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _count);
            await Release.Task.WaitAsync(cancellationToken);
            return await base.SendAsync(request, cancellationToken);
        }
    }
}
