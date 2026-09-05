using System.IO.Pipes;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class ReaderInstanceChannelTests
{
    [Fact]
    public async Task One_owner_receives_repeated_bounded_activation_requests()
    {
        var scope = Guid.NewGuid().ToString();
        Assert.True(ReaderInstanceChannel.TryAcquire(scope, out var owner));
        using (owner)
        {
            Assert.False(ReaderInstanceChannel.TryAcquire(scope, out var duplicate));
            Assert.Null(duplicate);
            var received = new System.Collections.Concurrent.ConcurrentQueue<ReaderActivation>();
            owner!.Listen(received.Enqueue);
            Assert.True(await ReaderInstanceChannel.SendAsync(scope, ReaderActivation.OpenReader));
            Assert.True(await ReaderInstanceChannel.SendAsync(scope, ReaderActivation.OpenServiceCenter));
            Assert.True(await ReaderInstanceChannel.SendAsync(scope, ReaderActivation.Background));
            Assert.Equal(new[] { ReaderActivation.OpenReader, ReaderActivation.OpenServiceCenter, ReaderActivation.Background }, received);
        }
        Assert.True(ReaderInstanceChannel.TryAcquire(scope, out var replacement));
        replacement!.Dispose();
        replacement.Dispose();
    }

    [Fact]
    public async Task Invalid_request_does_not_activate_and_next_client_can_reconnect()
    {
        var scope = Guid.NewGuid().ToString();
        Assert.True(ReaderInstanceChannel.TryAcquire(scope, out var owner));
        using (owner)
        {
            var count = 0;
            owner!.Listen(_ => Interlocked.Increment(ref count));
            await using (var invalid = new NamedPipeClientStream(".", ReaderInstanceChannel.PipeName(scope),
                PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly))
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                await invalid.ConnectAsync(timeout.Token);
                await invalid.WriteAsync(new byte[] { 255 }, timeout.Token);
                var reply = new byte[1];
                Assert.Equal(0, await invalid.ReadAsync(reply, timeout.Token));
            }
            Assert.Equal(0, count);
            Assert.True(await ReaderInstanceChannel.SendAsync(scope, ReaderActivation.OpenReader));
            Assert.Equal(1, count);
        }
    }

    [Fact]
    public async Task Stalled_client_is_disconnected_without_losing_ownership()
    {
        var scope = Guid.NewGuid().ToString();
        Assert.True(ReaderInstanceChannel.TryAcquire(scope, out var owner));
        using (owner)
        {
            owner!.Listen(_ => { });
            await using var stalled = new NamedPipeClientStream(".", ReaderInstanceChannel.PipeName(scope),
                PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(6));
            await stalled.ConnectAsync(timeout.Token);
            Assert.Equal(0, await stalled.ReadAsync(new byte[1], timeout.Token));
            Assert.False(ReaderInstanceChannel.TryAcquire(scope, out _));
            Assert.True(await ReaderInstanceChannel.SendAsync(scope, ReaderActivation.OpenReader));
        }
    }

    [Fact]
    public async Task Missing_owner_honors_cancellation_and_rejects_unknown_commands()
    {
        using var canceled = new CancellationTokenSource();
        canceled.Cancel();
        Assert.False(await ReaderInstanceChannel.SendAsync(Guid.NewGuid().ToString(), ReaderActivation.OpenReader, canceled.Token));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() => ReaderInstanceChannel.SendAsync("test", (ReaderActivation)255));
        Assert.NotEqual(ReaderInstanceChannel.PipeName("a"), ReaderInstanceChannel.PipeName("b"));
        Assert.DoesNotContain("secret/path", ReaderInstanceChannel.PipeName("secret/path"));
    }
}
