using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Windows;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private CaptureOutbox? _captureOutbox;
    private readonly DispatcherTimer _captureTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly CancellationTokenSource _captureCancellation = new();
    private ITokenProvider? _captureTokenProvider;
    private string? _captureServiceUrl;
    private bool _captureTickBusy;
    private string? _pendingCaptureCreateId;
    private string? _pendingCaptureDisplayedId;
    private string? _captureRefreshDocumentId;
    private string? _captureRefreshSelectionId;
    private string? _pendingCaptureTitle;
    private string? _pendingCaptureWorkspace;
    private string? _captureRefreshWorkspace;
    private DateTimeOffset _captureCheckAfter;
    private bool _captureStoreFailed;
    private string? _lastCaptureDiagnosticStatus;
    // Unaccepted clipboard prompts stay only in bounded RAM, never on disk.
    private readonly Queue<(string Text, ClipboardChangedEventArgs Change)> _deferredClipboardPrompts = new();

    private async Task InitializeCaptureOutboxAsync()
    {
        try
        {
            _captureOutbox = await Task.Run(() => new CaptureOutbox(new ProtectedCaptureOutboxStore()));
            _captureTimer.Tick += async (_, _) => await CaptureTickAsync();
            _captureTimer.Start();
            UpdateCaptureStatus();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ReaderTokenUnavailableException or ReaderClientConfigurationException)
        {
            _captureStoreFailed = true;
            CaptureStatusText.Text = "Local capture queue could not be opened. Existing files are preserved; do not reset the queue.";
            CaptureStatusPanel.Visibility = Visibility.Visible;
        }
    }

    private async Task<string> CaptureWorkspaceAsync()
    {
        if (_captureTokenProvider is null || _captureServiceUrl is null)
            throw new ReaderTokenUnavailableException("Configure the service connection before saving captures.");
        var provider = _captureTokenProvider;
        var url = _captureServiceUrl;
        var token = await provider.GetTokenAsync(_captureCancellation.Token);
        if (!ReferenceEquals(provider, _captureTokenProvider) || url != _captureServiceUrl)
            throw new ReaderTokenUnavailableException("The selected workspace changed. Retry with the intended connection.");
        if (string.IsNullOrWhiteSpace(token)) throw new ReaderTokenUnavailableException("Select a valid token before saving captures.");
        // Store no token. A changed endpoint/account cannot silently receive an old queue.
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(new Uri(url).AbsoluteUri + "\n" + token)));
    }

    private string? PendingAppendTarget => _pendingCaptureCreateId is not null &&
        _editor?.Document?.Id == _pendingCaptureDisplayedId ? _pendingCaptureCreateId : null;

    private async Task QueueCaptureAsync(string text, bool create, bool openDocument, bool newChapter)
    {
        var parent = create ? null : PendingAppendTarget;
        var target = create || parent is not null ? null : _editor?.Document;
        var displayedId = _editor?.Document?.Id;
        try
        {
            if (_captureOutbox is null) throw new IOException("The local capture queue is unavailable. Text has NOT been saved.");
            var workspace = await CaptureWorkspaceAsync();
            if (parent is not null && workspace != _pendingCaptureWorkspace)
                throw new InvalidOperationException("The queued article belongs to another workspace. Select that connection before appending.");
            if (!create && parent is null && (target is null || !target.IsEditable))
                throw new InvalidOperationException("Open an editable article, or create a queued article, before appending.");
            var title = $"Clipboard {DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}";
            var request = new CaptureRequest(create ? "create" : "append", text, title,
                DocumentId: target?.Id, TargetOperationId: parent, NewChapter: newChapter);
            var captured = await Task.Run(() => _captureOutbox.Enqueue(workspace, request, openDocument, displayedId));
            _playbackPerformance?.Record(new PlaybackPerformanceEvent("capture_queued", RequestId: captured.Id, Operation: request.Action));
            if (create && openDocument)
            {
                _pendingCaptureCreateId = captured.Id;
                _pendingCaptureDisplayedId = displayedId;
                _pendingCaptureTitle = title;
                _pendingCaptureWorkspace = workspace;
            }
            FooterText.Text = $"{text.Length:N0} characters saved locally. Delivery continues in Capture queue.";
            UpdateCaptureStatus();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ReaderTokenUnavailableException or InvalidOperationException)
        {
            FooterText.Text = "Capture NOT saved: " + error.Message;
            CaptureOutboxWindow.ShowRecovery(this, text, error.Message);
        }
    }

    private async Task CaptureTickAsync()
    {
        if (_closed || _captureTickBusy || _captureOutbox is null || _client is null) return;
        if (_captureOutbox.Items.Count == 0 && _captureRefreshDocumentId is null) { UpdateCaptureStatus(); return; }
        if (_captureCheckAfter > DateTimeOffset.UtcNow) { UpdateCaptureStatus(); return; }
        _captureTickBusy = true;
        try
        {
            var client = _client;
            var workspace = await CaptureWorkspaceAsync();
            if (!ReferenceEquals(client, _client)) return;
            if (_captureRefreshWorkspace is not null && _captureRefreshWorkspace != workspace)
            {
                _captureRefreshDocumentId = null;
                _captureRefreshWorkspace = null;
            }
            var active = _captureOutbox.Items.FirstOrDefault(item => item.Workspace == workspace);
            if (active is not null && (_editor?.HasUnsavedChanges == true || _documentMutationInProgress || _documentReloadInProgress))
            {
                CaptureStatusText.Text = "Capture saved locally — save/revert your edit before synchronization.";
                CaptureStatusPanel.Visibility = Visibility.Visible;
                return;
            }
            if (active?.Request.Action == "append" && _playback?.IsActive == true &&
                (active.Request.DocumentId == _playback.DocumentId || active.Request.TargetOperationId is not null))
            {
                CaptureStatusText.Text = "Capture saved locally — pause reading to append.";
                CaptureStatusPanel.Visibility = Visibility.Visible;
                return;
            }
            var attempt = _captureOutbox.DeliverNextAsync(workspace, client, _captureCancellation.Token);
            UpdateCaptureStatus();
            var delivery = await attempt;
            if (delivery is { } delivered)
            {
                // Inbox-only captures must not replace an earlier explicit
                // request to open an article after the same delivery batch.
                if (delivered.Capture.OpenDocument || _captureRefreshDocumentId is null)
                {
                    _captureRefreshDocumentId = delivered.Receipt.DocumentId;
                    _captureRefreshWorkspace = workspace;
                    _captureRefreshSelectionId = delivered.Capture.OpenDocument ? delivered.Capture.DisplayDocumentId : "do-not-open";
                }
                _playbackPerformance?.Record(new PlaybackPerformanceEvent("capture_delivered",
                    RequestId: delivered.Receipt.OperationId, DocumentId: delivered.Receipt.DocumentId,
                    State: delivered.Receipt.Outcome, Operation: delivered.Capture.Request.Action));
            }
            else if (active is not null && _lastCaptureDiagnosticStatus != _captureOutbox.Status)
            {
                _lastCaptureDiagnosticStatus = _captureOutbox.Status;
                _playbackPerformance?.Record(new PlaybackPerformanceEvent("capture_waiting", RequestId: active.Id,
                    State: _captureOutbox.NeedsAttention ? "attention" : "retry", Operation: active.Request.Action));
            }
            UpdateCaptureStatus();
            // One refresh after the batch. A refresh failure never re-enqueues a write.
            if (_captureRefreshDocumentId is { } documentId && !_captureOutbox.Items.Any(item => item.Workspace == workspace) &&
                _playback?.IsActive != true && _editor?.HasUnsavedChanges != true && !_clipboardPromptOpen &&
                !_documentMutationInProgress && !_documentReloadInProgress && ReferenceEquals(client, _client))
            {
                var shouldOpen = _editor?.Document?.Id == _captureRefreshSelectionId;
                await RefreshLibraryAsync(throwOnFailure: true);
                if (shouldOpen && _editor?.Document?.Id == _captureRefreshSelectionId &&
                    ReferenceEquals(client, _client) && _editor?.HasUnsavedChanges != true)
                {
                    var document = await client.GetDocumentAsync(documentId, _captureCancellation.Token);
                    if (_editor?.Document?.Id != _captureRefreshSelectionId || !ReferenceEquals(client, _client)) return;
                    await LoadDocumentAsync(document);
                    if (_editor?.Document?.Id != documentId || _editor.Document.ContentRevision < document.ContentRevision)
                        throw new ReaderServiceUnavailableException("Capture was delivered, but the article view has not caught up yet.");
                }
                _captureRefreshDocumentId = null;
                _captureRefreshWorkspace = null;
                _pendingCaptureCreateId = null;
                _pendingCaptureTitle = null;
            }
        }
        catch (OperationCanceledException) when (_closed) { }
        catch (Exception error) when (error is ReaderApiException or ReaderTokenUnavailableException or ReaderServiceUnavailableException or IOException or UnauthorizedAccessException)
        {
            var seconds = error is ReaderApiException { StatusCode: 429 } api &&
                api.Details.TryGetValue("retry_after_seconds", out var retry) && int.TryParse(retry?.ToString(), out var parsed)
                ? Math.Clamp(parsed, 1, 3600) : 15;
            _captureCheckAfter = DateTimeOffset.UtcNow.AddSeconds(seconds);
            CaptureStatusText.Text = _captureRefreshDocumentId is not null
                ? "Delivered to service; article refresh is waiting. No capture will be resent."
                : "Capture queue retained. Check the selected workspace and connection.";
            CaptureStatusPanel.Visibility = Visibility.Visible;
        }
        finally { _captureTickBusy = false; }
    }

    private void UpdateCaptureStatus()
    {
        if (_captureOutbox is null) return;
        var items = _captureOutbox.Items;
        if (_pendingCaptureCreateId is not null && !items.Any(item => item.Id == _pendingCaptureCreateId) &&
            _captureRefreshDocumentId is null && !_captureTickBusy)
        {
            _pendingCaptureCreateId = null;
            _pendingCaptureTitle = null;
        }
        var retryAt = _captureOutbox.RetryAt > _captureCheckAfter ? _captureOutbox.RetryAt : _captureCheckAfter;
        var wait = Math.Max(0, (int)Math.Ceiling((retryAt - DateTimeOffset.UtcNow).TotalSeconds));
        var status = items.Count == 0 && _captureRefreshDocumentId is not null
            ? "Delivered to service — article refresh pending" : _captureOutbox.Status;
        CaptureStatusText.Text = $"{items.Count} saved locally · {items.Sum(item => item.Request.Text.Length):N0} characters · {status}" +
            (wait > 0 ? $" · retry in {wait}s" : "") +
            (PendingAppendTarget is not null ? $" · Append target: {_pendingCaptureTitle}" : "");
        CaptureStatusPanel.Visibility = Visibility.Visible;
    }

    private void CaptureQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_captureOutbox is null)
        {
            MessageBox.Show(this, _captureStoreFailed ? "Queue files are preserved. Resolve the local storage problem before capturing more text." : "Capture queue is not initialized.");
            return;
        }
        new CaptureOutboxWindow(_captureOutbox) { Owner = this }.Show();
    }
}
