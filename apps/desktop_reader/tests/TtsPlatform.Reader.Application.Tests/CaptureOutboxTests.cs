using System.Reflection;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class CaptureOutboxTests
{
    [Fact]
    public async Task Duplicate_permission_only_changes_the_rejected_operation()
    {
        var queue = new CaptureOutbox(new MemoryStore());
        var first = queue.Enqueue("a", new("create", "Same text."), true);
        var other = queue.Enqueue("a", new("create", "Another article."), true);
        Assert.Null(await queue.DeliverNextAsync("a", Client((_, _) =>
            throw new ReaderApiException("reader_duplicate_document", "Duplicate", 409))));
        queue.AllowDuplicate(other.Id);
        Assert.False(queue.Items[1].Request.AllowDuplicate);
        Assert.True(queue.NeedsAttention);
        queue.AllowDuplicate(first.Id);
        Assert.True(queue.Items[0].Request.AllowDuplicate);
        Assert.False(queue.NeedsAttention);
    }

    [Fact]
    public async Task Restart_after_lost_response_reuses_identity_and_preserves_order()
    {
        var store = new MemoryStore();
        var queue = new CaptureOutbox(store);
        var parent = queue.Enqueue("workspace", new("create", new string('x', 150_000)), true);
        var child = queue.Enqueue("workspace", new("append", "Next chapter.", TargetOperationId: parent.Id), true);
        var client = Client((id, _) => throw new ReaderServiceUnavailableException("Lost response"));
        Assert.Null(await queue.DeliverNextAsync("workspace", client));
        Assert.True(store.Load()[0].Attempted);
        var restored = new CaptureOutbox(store);
        var ids = new List<string>();
        client = Client((id, request) =>
        {
            ids.Add(id);
            if (id == child.Id) Assert.Equal(parent.Id, request.TargetOperationId);
            return Task.FromResult(new CaptureReceipt(id, "document", "already_delivered"));
        });
        Assert.NotNull(await restored.DeliverNextAsync("workspace", client));
        Assert.NotNull(await restored.DeliverNextAsync("workspace", client));
        Assert.Equal([parent.Id, child.Id], ids);
        Assert.Empty(store.Load());
    }

    [Fact]
    public async Task Rate_limit_retains_text_and_manual_retry_cannot_bypass_deadline()
    {
        var clock = new Clock();
        var queue = new CaptureOutbox(new MemoryStore(), clock);
        queue.Enqueue("a", new("create", "Keep me."), true);
        var calls = 0;
        var client = Client((id, _) =>
        {
            calls++;
            if (calls == 1) throw new ReaderApiException("rate_limited", "Wait", 429,
                details: new Dictionary<string, object?> { ["retry_after_seconds"] = 60 });
            return Task.FromResult(new CaptureReceipt(id, "doc", "delivered"));
        });
        Assert.Null(await queue.DeliverNextAsync("a", client));
        queue.Retry();
        Assert.Null(await queue.DeliverNextAsync("a", client));
        Assert.Equal(1, calls);
        Assert.Single(queue.Items);
        clock.Now += TimeSpan.FromSeconds(60);
        Assert.NotNull(await queue.DeliverNextAsync("a", client));
        Assert.Empty(queue.Items);
    }

    [Fact]
    public async Task Different_workspace_never_receives_a_capture()
    {
        var queue = new CaptureOutbox(new MemoryStore());
        queue.Enqueue("original", new("create", "Private text."), true);
        var client = Client((_, _) => throw new InvalidOperationException("Must not call"));
        Assert.Null(await queue.DeliverNextAsync("other", client));
        Assert.Single(queue.Items);
    }

    [Fact]
    public async Task Invalid_receipt_or_local_delete_failure_does_not_remove_text()
    {
        var store = new MemoryStore { FailDelete = true };
        var queue = new CaptureOutbox(store);
        var item = queue.Enqueue("a", new("create", "Keep until acknowledged."), true);
        Assert.Null(await queue.DeliverNextAsync("a", Client((id, _) => Task.FromResult(new CaptureReceipt(id, "doc", "delivered")))));
        Assert.True(queue.NeedsAttention);
        Assert.Single(new CaptureOutbox(store).Items);
        store.FailDelete = false;
        queue.Retry();
        Assert.NotNull(await queue.DeliverNextAsync("a", Client((id, _) => Task.FromResult(new CaptureReceipt(id, "doc", "already_delivered")))));
        Assert.Empty(store.Load());
        queue.Enqueue("a", new("create", "Another capture."), true);
        Assert.Null(await queue.DeliverNextAsync("a", Client((_, _) => Task.FromResult(new CaptureReceipt(item.Id, "doc", "delivered")))));
        Assert.Single(store.Load());
    }

    [Fact]
    public void Failed_save_is_not_acknowledged_and_dependencies_cannot_be_orphaned()
    {
        var store = new MemoryStore { FailSave = true };
        var queue = new CaptureOutbox(store);
        Assert.Throws<IOException>(() => queue.Enqueue("a", new("create", "Not saved."), true));
        Assert.Empty(queue.Items);
        store.FailSave = false;
        var parent = queue.Enqueue("a", new("create", "Parent."), true);
        var child = queue.Enqueue("a", new("append", "Child.", TargetOperationId: parent.Id), true);
        Assert.Throws<InvalidOperationException>(() => queue.Discard(parent.Id));
        queue.Discard(child.Id);
        queue.Discard(parent.Id);
        Assert.Empty(queue.Items);
    }

    [Fact]
    public async Task Only_one_delivery_can_run_at_once()
    {
        var queue = new CaptureOutbox(new MemoryStore());
        var item = queue.Enqueue("a", new("create", "One."), true);
        var completion = new TaskCompletionSource<CaptureReceipt>(TaskCreationOptions.RunContinuationsAsynchronously);
        var first = queue.DeliverNextAsync("a", Client((_, _) => completion.Task));
        Assert.True(queue.Sending);
        Assert.Null(await queue.DeliverNextAsync("a", Client((_, _) => throw new InvalidOperationException())));
        Assert.Throws<InvalidOperationException>(() => queue.Discard(item.Id));
        completion.SetResult(new(item.Id, "doc", "delivered"));
        Assert.NotNull(await first);
    }

    [Fact]
    public void Queue_enforces_item_and_total_budgets()
    {
        var queue = new CaptureOutbox(new MemoryStore());
        Assert.Throws<InvalidOperationException>(() => queue.Enqueue("a", new("create", new string('x', 1_000_001)), true));
        for (var i = 0; i < 8; i++) queue.Enqueue("a", new("create", new string('x', 1_000_000)), true);
        Assert.Throws<InvalidOperationException>(() => queue.Enqueue("a", new("create", "x"), true));
        Assert.Equal(8, queue.Items.Count);
    }

    private static IReaderServiceClient Client(Func<string, CaptureRequest, Task<CaptureReceipt>> deliver)
    {
        var proxy = DispatchProxy.Create<IReaderServiceClient, CaptureClientProxy>();
        ((CaptureClientProxy)proxy).Deliver = deliver;
        return proxy;
    }
    public class CaptureClientProxy : DispatchProxy
    {
        public Func<string, CaptureRequest, Task<CaptureReceipt>> Deliver { get; set; } = null!;
        protected override object? Invoke(MethodInfo? targetMethod, object?[]? args) =>
            targetMethod?.Name == nameof(IReaderServiceClient.DeliverCaptureAsync)
                ? Deliver((string)args![0]!, (CaptureRequest)args[1]!) : throw new NotSupportedException();
    }
    private sealed class Clock : TimeProvider
    {
        public DateTimeOffset Now = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => Now;
    }
    private sealed class MemoryStore : ICaptureOutboxStore
    {
        private readonly Dictionary<string, PendingCapture> _items = [];
        public bool FailSave;
        public bool FailDelete;
        public IReadOnlyList<PendingCapture> Load() => _items.Values.ToArray();
        public void Save(PendingCapture item)
        {
            if (FailSave) throw new IOException("Disk full");
            _items[item.Id] = item;
        }
        public void Delete(string id)
        {
            if (FailDelete) throw new IOException("File locked");
            _items.Remove(id);
        }
    }
}
