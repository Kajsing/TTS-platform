using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public enum DesktopHandoffResult { Skipped, NoRequest, Deferred, Opened }

// One coordinator belongs to one client/workspace lifetime. No pending request
// is retained or acknowledged across a connection change.
public sealed class DesktopHandoffCoordinator(IReaderServiceClient client)
{
    private readonly CancellationTokenSource _lifetime = new();
    private readonly SemaphoreSlim _gate = new(1, 1);

    public void Cancel() => _lifetime.Cancel();

    public async Task<DesktopHandoffResult> CheckAsync(
        Func<bool> canOpen,
        Func<ReaderDocument, CancellationToken, Task<bool>> openDocument,
        CancellationToken cancellationToken = default)
    {
        if (_lifetime.IsCancellationRequested || !canOpen()) return DesktopHandoffResult.Skipped;
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token, cancellationToken);
        var token = lifetime.Token;
        if (!await _gate.WaitAsync(0, token)) return DesktopHandoffResult.Skipped;
        try
        {
            var request = await client.GetNextDesktopOpenRequestAsync(token);
            token.ThrowIfCancellationRequested();
            if (request is null) return DesktopHandoffResult.NoRequest;
            if (!canOpen()) return DesktopHandoffResult.Deferred;
            var document = await client.GetDocumentAsync(request.DocumentId, token);
            token.ThrowIfCancellationRequested();
            if (!canOpen()) return DesktopHandoffResult.Deferred;
            var opened = await openDocument(document, token);
            token.ThrowIfCancellationRequested();
            if (!opened || !canOpen()) return DesktopHandoffResult.Deferred;
            await client.AcknowledgeDesktopOpenRequestAsync(request.Id, token);
            token.ThrowIfCancellationRequested();
            return DesktopHandoffResult.Opened;
        }
        finally { _gate.Release(); }
    }
}
