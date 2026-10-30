using System.Net;
using System.Text;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class DesktopHandoffTests
{
    [Fact]
    public async Task Busy_reader_skips_polling_and_idle_reader_opens_and_acknowledges_once()
    {
        var handler = new Handler();
        var coordinator = new DesktopHandoffCoordinator(Client(handler));
        for (var tick = 0; tick < 6; tick++)
            Assert.Equal(DesktopHandoffResult.Skipped, await coordinator.CheckAsync(() => false, Open));
        Assert.Equal(0, handler.Polls);
        Assert.Equal(DesktopHandoffResult.Opened, await coordinator.CheckAsync(() => true, Open));
        Assert.Equal(1, handler.Polls);
        Assert.Equal(1, handler.DocumentReads);
        Assert.Equal(1, handler.Acknowledgements);
    }

    [Theory]
    [InlineData("poll")]
    [InlineData("document")]
    [InlineData("open")]
    public async Task Becoming_busy_during_a_held_operation_never_acknowledges(string phase)
    {
        var entered = Signal();
        var release = Signal();
        var canOpen = true;
        var handler = new Handler
        {
            Hold = async (current, _) =>
            {
                if (current != phase) return;
                entered.TrySetResult();
                await release.Task;
            },
        };
        var coordinator = new DesktopHandoffCoordinator(Client(handler));
        var opening = 0;
        var check = coordinator.CheckAsync(() => canOpen, async (_, _) =>
        {
            opening++;
            if (phase == "open")
            {
                entered.TrySetResult();
                await release.Task;
            }
            return true;
        });
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(3));
        canOpen = false;
        release.TrySetResult();
        Assert.Equal(DesktopHandoffResult.Deferred, await check.WaitAsync(TimeSpan.FromSeconds(3)));
        Assert.Equal(phase == "open" ? 1 : 0, opening);
        Assert.Equal(0, handler.Acknowledgements);
    }

    [Theory]
    [InlineData("poll")]
    [InlineData("document")]
    public async Task Cancelled_workspace_never_opens_or_acknowledges_and_new_workspace_is_independent(string phase)
    {
        var entered = Signal();
        var release = Signal();
        var old = new Handler
        {
            Hold = async (current, _) =>
            {
                if (current != phase) return;
                entered.TrySetResult();
                // Deliberately finish late even when transport cancellation was signalled.
                await release.Task;
            },
        };
        var previous = new DesktopHandoffCoordinator(Client(old));
        var oldOpenCalls = 0;
        var pending = previous.CheckAsync(() => true, (_, _) =>
        {
            oldOpenCalls++;
            return Task.FromResult(true);
        });
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(3));
        previous.Cancel();
        var current = new Handler();
        var next = new DesktopHandoffCoordinator(Client(current));
        Assert.Equal(DesktopHandoffResult.Opened, await next.CheckAsync(() => true, Open));
        release.TrySetResult();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(0, oldOpenCalls);
        Assert.Equal(0, old.Acknowledgements);
        Assert.Equal(1, current.Polls);
        Assert.Equal(1, current.Acknowledgements);
        Assert.Equal(DesktopHandoffResult.Skipped, await previous.CheckAsync(() => true, Open));
    }

    [Fact]
    public async Task Overlapping_checks_do_not_create_a_second_poll()
    {
        var entered = Signal();
        var release = Signal();
        var handler = new Handler
        {
            Hold = async (phase, _) =>
            {
                if (phase != "poll") return;
                entered.TrySetResult();
                await release.Task;
            },
        };
        var coordinator = new DesktopHandoffCoordinator(Client(handler));
        var first = coordinator.CheckAsync(() => true, Open);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(3));
        Assert.Equal(DesktopHandoffResult.Skipped, await coordinator.CheckAsync(() => true, Open));
        release.TrySetResult();
        Assert.Equal(DesktopHandoffResult.Opened, await first);
        Assert.Equal(1, handler.Polls);
    }

    [Fact]
    public async Task Failed_open_remains_pending_and_retry_fetches_fresh_request()
    {
        var handler = new Handler();
        var coordinator = new DesktopHandoffCoordinator(Client(handler));
        Assert.Equal(DesktopHandoffResult.Deferred,
            await coordinator.CheckAsync(() => true, (_, _) => Task.FromResult(false)));
        Assert.Equal(0, handler.Acknowledgements);
        Assert.Equal(DesktopHandoffResult.Opened, await coordinator.CheckAsync(() => true, Open));
        Assert.Equal(2, handler.Polls);
        Assert.Equal(2, handler.DocumentReads);
        Assert.Equal(1, handler.Acknowledgements);
    }

    private static Task<bool> Open(ReaderDocument document, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        Assert.Equal("doc", document.Id);
        return Task.FromResult(true);
    }

    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static ReaderServiceClient Client(Handler handler) =>
        new(new HttpClient(handler), "http://localhost:7777", new Token());

    private sealed class Handler : HttpMessageHandler
    {
        public Func<string, CancellationToken, Task>? Hold { get; init; }
        public int Polls, DocumentReads, Acknowledgements;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var phase = request.Method == HttpMethod.Delete ? "ack" :
                request.RequestUri!.AbsolutePath.EndsWith("/next", StringComparison.Ordinal) ? "poll" : "document";
            if (phase == "poll") Polls++;
            else if (phase == "document") DocumentReads++;
            else Acknowledgements++;
            if (Hold is not null) await Hold(phase, cancellationToken);
            if (phase == "ack") return new HttpResponseMessage(HttpStatusCode.NoContent);
            var body = phase == "poll" ? "{\"id\":\"request\",\"document_id\":\"doc\"}" :
                "{\"id\":\"doc\",\"title\":\"Synthetic handoff\",\"source_type\":\"plain_text\",\"content_revision\":1,\"row_version\":1,\"metadata\":{}}";
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json"),
            };
        }
    }

    private sealed class Token : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<string?>("test-owner");
    }
}
