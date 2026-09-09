using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record PendingCapture(string Id, string Workspace, DateTimeOffset AcceptedAt,
    CaptureRequest Request, bool OpenDocument, bool Attempted = false, int StorageVersion = 1,
    string? DisplayDocumentId = null);

public interface ICaptureOutboxStore
{
    IReadOnlyList<PendingCapture> Load();
    void Save(PendingCapture capture);
    void Delete(string id);
}

/// <summary>One explicit capture, one durable identity. UI refresh is not delivery.</summary>
public sealed class CaptureOutbox(ICaptureOutboxStore store, TimeProvider? time = null)
{
    public const int MaxItemCharacters = 1_000_000;
    public const int MaxCharacters = 8_000_000;
    public const int MaxItems = 50;
    private readonly TimeProvider _time = time ?? TimeProvider.System;
    private readonly SemaphoreSlim _delivery = new(1, 1);
    private readonly object _gate = new();
    private readonly List<PendingCapture> _items = store.Load().OrderBy(item => item.AcceptedAt).ThenBy(item => item.Id).ToList();
    public DateTimeOffset RetryAt { get; private set; }
    public string Status { get; private set; } = "Ready";
    public bool NeedsAttention { get; private set; }
    public string? AttentionId { get; private set; }
    public bool Sending => _delivery.CurrentCount == 0;
    public IReadOnlyList<PendingCapture> Items { get { lock (_gate) return _items.ToArray(); } }

    public PendingCapture Enqueue(string workspace, CaptureRequest request, bool openDocument, string? displayDocumentId = null)
    {
        if (string.IsNullOrWhiteSpace(request.Text) || request.Text.Length > MaxItemCharacters)
            throw new InvalidOperationException("Capture must contain 1 to 1,000,000 characters.");
        lock (_gate)
        {
            if (_items.Count >= MaxItems || _items.Sum(item => item.Request.Text.Length) + request.Text.Length > MaxCharacters)
                throw new InvalidOperationException("The local capture queue is full. Deliver or discard queued items first.");
            var now = _time.GetUtcNow();
            if (_items.LastOrDefault() is { } last && now <= last.AcceptedAt) now = last.AcceptedAt.AddTicks(1);
            var item = new PendingCapture(Guid.NewGuid().ToString(), workspace, now, request, openDocument,
                DisplayDocumentId: displayDocumentId);
            store.Save(item); // Never acknowledge a capture that exists only in memory.
            _items.Add(item);
            return item;
        }
    }

    public void Retry()
    {
        NeedsAttention = false;
        AttentionId = null;
        // Retry-After is a server requirement, not bypassed by repeated clicks.
        Status = "Retry requested";
    }

    public void Discard(string id)
    {
        if (!_delivery.Wait(0)) throw new InvalidOperationException("Wait for the current delivery attempt before discarding.");
        try
        {
            lock (_gate)
            {
                var item = _items.Single(candidate => candidate.Id == id);
                if (_items.Any(candidate => candidate.Request.TargetOperationId == id))
                    throw new InvalidOperationException("Discard dependent appends before discarding their new article.");
                store.Delete(item.Id);
                _items.Remove(item);
                NeedsAttention = false;
                AttentionId = null;
            }
        }
        finally { _delivery.Release(); }
    }

    public void AllowDuplicate(string id)
    {
        if (!_delivery.Wait(0)) throw new InvalidOperationException("Wait for delivery to finish first.");
        try
        {
            lock (_gate)
            {
                if (!NeedsAttention || AttentionId != id) return;
                var index = _items.FindIndex(item => item.Id == id);
                if (index < 0 || _items[index].Request.Action != "create") return;
                // Only use this after an explicit duplicate rejection, never after
                // an uncertain connection failure. The server did not commit it.
                if (Status != "Duplicate article: choose discard or allow duplicate.") return;
                var changed = _items[index] with { Request = _items[index].Request with { AllowDuplicate = true } };
                store.Save(changed);
                _items[index] = changed;
                NeedsAttention = false;
                AttentionId = null;
            }
        }
        finally { _delivery.Release(); }
    }

    public async Task<(PendingCapture Capture, CaptureReceipt Receipt)?> DeliverNextAsync(
        string workspace, IReaderServiceClient client, CancellationToken cancellationToken = default)
    {
        if (NeedsAttention || RetryAt > _time.GetUtcNow() || !await _delivery.WaitAsync(0, cancellationToken)) return null;
        PendingCapture? item = null;
        try
        {
            lock (_gate) item = _items.FirstOrDefault(candidate => candidate.Workspace == workspace);
            if (item is null) { Status = "All accepted captures delivered"; return null; }
            var attempted = item with { Attempted = true };
            store.Save(attempted);
            lock (_gate) _items[_items.IndexOf(item)] = attempted;
            Status = "Sending saved capture…";
            var receipt = await client.DeliverCaptureAsync(item.Id, item.Request, cancellationToken).ConfigureAwait(false);
            if (receipt.OperationId != item.Id || receipt.Outcome is not ("delivered" or "already_delivered") || string.IsNullOrWhiteSpace(receipt.DocumentId))
                throw new ReaderServiceUnavailableException("The service returned an invalid delivery receipt.");
            store.Delete(item.Id);
            lock (_gate) _items.RemoveAll(candidate => candidate.Id == item.Id);
            RetryAt = default;
            Status = "Delivered to the service";
            return (attempted, receipt);
        }
        catch (ReaderApiException error) when (error.StatusCode == 429 || error.ErrorType == "reader_document_locked")
        {
            var seconds = error.StatusCode == 429 ? RetrySeconds(error) : 5;
            RetryAt = _time.GetUtcNow().AddSeconds(seconds);
            Status = error.StatusCode == 429 ? "Saved locally — waiting for service capacity" : "Saved locally — pause reading to append";
            return null;
        }
        catch (Exception error) when (error is ReaderServiceUnavailableException or HttpRequestException or TaskCanceledException)
        {
            RetryAt = _time.GetUtcNow().AddSeconds(15);
            Status = "Saved locally — service unavailable; delivery will retry safely";
            return null;
        }
        catch (Exception error) when (error is ReaderApiException or ReaderTokenUnavailableException or NotSupportedException or IOException or UnauthorizedAccessException)
        {
            NeedsAttention = true;
            AttentionId = item?.Id;
            Status = error is ReaderApiException { ErrorType: "reader_duplicate_document" }
                ? "Duplicate article: choose discard or allow duplicate."
                : "Capture retained — attention required: " + (error is ReaderApiException api ? api.ErrorType : "check connection, credentials or local storage");
            return null;
        }
        finally { _delivery.Release(); }
    }

    private static int RetrySeconds(ReaderApiException error) =>
        error.Details.TryGetValue("retry_after_seconds", out var value) && int.TryParse(value?.ToString(), out var seconds)
            ? Math.Clamp(seconds, 1, 3600) : 61;
}
