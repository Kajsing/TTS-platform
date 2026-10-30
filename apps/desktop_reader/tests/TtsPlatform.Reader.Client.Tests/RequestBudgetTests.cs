using System.Net;
using System.Text;
using System.Text.Json;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class RequestBudgetTests
{
    public static IEnumerable<object[]> RouteCases() =>
        JsonSerializer.Deserialize<string[][]>(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "request_budget_cases.json")))!
            .Select(row => row.Cast<object>().ToArray());

    [Theory]
    [MemberData(nameof(RouteCases))]
    public void Routes_match_the_shared_service_contract(string method, string path, string expected)
    {
        using var relative = new HttpRequestMessage(new HttpMethod(method), path + "?limit=2");
        using var absolute = new HttpRequestMessage(new HttpMethod(method), "http://localhost:7777" + path + "?limit=2");
        Assert.Equal(expected, ReaderRequestBudget.ForRequest(relative));
        Assert.Equal(expected, ReaderRequestBudget.ForRequest(absolute));
    }

    [Theory]
    [InlineData(ReaderRequestBudget.Background)]
    [InlineData(ReaderRequestBudget.Playback)]
    public async Task Cooldown_is_shared_only_within_its_budget_and_expires(string limitedBudget)
    {
        var time = new ManualTime();
        var cooldown = new ReaderRequestCooldown(time);
        var calls = 0;
        var deny = true;
        var handler = new Handler((request, _) =>
        {
            Interlocked.Increment(ref calls);
            return Task.FromResult(deny && ReaderRequestBudget.ForRequest(request) == limitedBudget
                ? Limited(limitedBudget) : Ok(request));
        });
        var first = Client(handler, cooldown);
        var second = Client(handler, cooldown);
        Task LimitedCall(ReaderServiceClient client) => limitedBudget == ReaderRequestBudget.Background
            ? client.GetCapabilitiesAsync() : client.GetPositionAsync("doc");
        Task OtherCall() => limitedBudget == ReaderRequestBudget.Background
            ? second.GetPositionAsync("doc") : second.GetCapabilitiesAsync();

        await Assert.ThrowsAsync<ReaderApiException>(() => LimitedCall(first));
        var blocked = await Assert.ThrowsAsync<ReaderApiException>(() => LimitedCall(second));
        Assert.Equal(42, blocked.Details["retry_after_seconds"]);
        Assert.Equal(1, calls);
        await OtherCall();
        Assert.Equal(2, calls);
        deny = false;
        time.Advance(TimeSpan.FromSeconds(42));
        await LimitedCall(second);
        Assert.Equal(3, calls);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("unknown")]
    public void Legacy_or_unknown_budget_preserves_global_backoff(string? budget)
    {
        var cooldown = new ReaderRequestCooldown();
        using var response = Limited(budget);
        cooldown.Observe(response);
        Assert.Throws<ReaderApiException>(() => cooldown.Check(ReaderRequestBudget.Playback));
        Assert.Throws<ReaderApiException>(() => cooldown.Check(ReaderRequestBudget.Background));
    }

    [Fact]
    public async Task Background_queue_is_bounded_cancellable_and_does_not_block_playback_or_storm_after_429()
    {
        var time = new ManualTime();
        var cooldown = new ReaderRequestCooldown(time);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var backgroundCalls = 0;
        var deny = true;
        var handler = new Handler(async (request, cancellation) =>
        {
            if (ReaderRequestBudget.ForRequest(request) == ReaderRequestBudget.Playback) return Ok(request);
            if (Interlocked.Increment(ref backgroundCalls) == 2) entered.TrySetResult();
            await release.Task.WaitAsync(cancellation);
            return deny ? Limited(ReaderRequestBudget.Background) : Ok(request);
        });
        var first = Client(handler, cooldown);
        var second = Client(handler, cooldown);
        using var cancel = new CancellationTokenSource();
        var firstRequests = new[] { first.GetCapabilitiesAsync(), second.GetCapabilitiesAsync() };
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var cancelled = second.GetCapabilitiesAsync(cancel.Token);
        var queued = Enumerable.Range(0, ReaderRequestCooldown.MaxPendingRequestsPerBudget - 3)
            .Select(_ => first.GetCapabilitiesAsync()).ToArray();
        var full = await Assert.ThrowsAsync<ReaderApiException>(() => second.GetCapabilitiesAsync());
        Assert.Equal("reader_request_queue_full", full.ErrorType);
        Assert.Equal(2, backgroundCalls);
        await second.GetPositionAsync("doc").WaitAsync(TimeSpan.FromSeconds(5));
        cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => cancelled);
        release.TrySetResult();
        foreach (var request in firstRequests.Concat(queued))
        {
            var error = await Assert.ThrowsAsync<ReaderApiException>(() => request);
            Assert.Equal("rate_limited", error.ErrorType);
        }
        Assert.Equal(2, backgroundCalls); // Queued writes/reads never hit a throttled server.
        time.Advance(TimeSpan.FromSeconds(42));
        deny = false;
        await first.GetCapabilitiesAsync();
        Assert.Equal(3, backgroundCalls);
    }

    [Fact]
    public async Task Websocket_error_retains_retry_details_and_coordinates_with_http_playback()
    {
        var parser = new ReaderStreamProtocolParser();
        var error = Assert.IsType<ReaderStreamError>(parser.ProcessText("""
            {"type":"error","error":{"type":"rate_limited","message":"Wait",
             "details":{"request_budget":"playback","retry_after_seconds":17}}}
            """));
        Assert.Equal(17, error.RetryAfterSeconds);
        var cooldown = new ReaderRequestCooldown();
        cooldown.Observe(error);
        cooldown.Check(ReaderRequestBudget.Background);
        Assert.Throws<ReaderApiException>(() => cooldown.Check(ReaderRequestBudget.Playback));
        var stream = new ReaderStreamClient("http://localhost:7777", new Token(), cooldown: cooldown);
        await Assert.ThrowsAsync<ReaderApiException>(() => stream.OpenAsync(new ReaderStreamStartRequest(
            "doc", new ReaderCursor("doc", "block", 0, 0, 1))));
    }

    private static ReaderServiceClient Client(HttpMessageHandler handler, ReaderRequestCooldown cooldown) =>
        new(new HttpClient(handler), "http://localhost:7777", new Token(), cooldown: cooldown);

    private static HttpResponseMessage Limited(string? budget)
    {
        var response = new HttpResponseMessage(HttpStatusCode.TooManyRequests)
        {
            Content = new StringContent("{\"error\":{\"type\":\"rate_limited\",\"message\":\"Wait\"}}", Encoding.UTF8, "application/json"),
        };
        response.Headers.RetryAfter = new(TimeSpan.FromSeconds(42));
        if (budget is not null) response.Headers.Add(ReaderRequestBudget.Header, budget);
        return response;
    }

    private static HttpResponseMessage Ok(HttpRequestMessage request) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(request.RequestUri!.AbsolutePath.EndsWith("/position", StringComparison.Ordinal)
            ? "{\"position\":null}" : "{}", Encoding.UTF8, "application/json"),
    };

    private sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            send(request, cancellationToken);
    }

    private sealed class Token : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<string?>("owner");
    }

    private sealed class ManualTime : TimeProvider
    {
        private DateTimeOffset _now = new(2026, 10, 30, 12, 0, 0, TimeSpan.Zero);
        public override DateTimeOffset GetUtcNow() => _now;
        public void Advance(TimeSpan delta) => _now += delta;
    }
}
