using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    internal async Task VerifyCaptureOutboxAsync(string root)
    {
        if (!_smokeTest || _editor is not null || _playback is not null)
            throw new InvalidOperationException("Capture smoke requires an isolated Reader.");
        static void Require(bool condition, string message)
        { if (!condition) throw new InvalidOperationException(message); }
        var client = DispatchProxy.Create<IReaderServiceClient, DocumentSwitchSmokeClient>();
        var fake = (DocumentSwitchSmokeClient)client;
        var clock = new CaptureSmokeClock();
        var store = new ProtectedCaptureOutboxStore(Path.Combine(root, "synthetic-outbox"));
        _captureOutbox = new CaptureOutbox(store, clock);
        _captureTokenProvider = new CaptureSmokeToken();
        _captureServiceUrl = "http://127.0.0.1:17777/";
        _client = client;
        _editor = new DocumentEditor(client);
        _library = new LibraryPager(client);
        DocumentsGrid.ItemsSource = _library.Documents;
        try
        {
            await QueueCaptureAsync(new string('x', 150_000), true, true, true);
            var parent = _captureOutbox.Items.Single();
            Require(parent.Request.Text.Length == 150_000 && PendingAppendTarget == parent.Id, "New article was not persisted/bound before delivery.");
            fake.CaptureGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var pending = CaptureTickAsync();
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            Require(!pending.IsCompleted && _captureOutbox.Sending, "Synthetic delivery did not remain pending.");
            await QueueCaptureAsync("Next synthetic chapter.", false, true, true);
            Require(_captureOutbox.Items.Count == 2 && _captureOutbox.Items[1].Request.TargetOperationId == parent.Id,
                "Append while sending did not preserve its queued parent.");
            fake.CaptureGate.SetResult(new(parent.Id, "first", "delivered"));
            await pending;
            fake.CaptureGate = null;
            fake.CaptureFailure = new("rate_limited", "Synthetic wait", 429,
                details: new Dictionary<string, object?> { ["retry_after_seconds"] = 60 });
            await CaptureTickAsync();
            Require(_captureOutbox.Items.Count == 1 && CaptureStatusText.Text.Contains("waiting"), "429 lost the capture or hid the wait state.");
            var window = new CaptureOutboxWindow(_captureOutbox) { Owner = this };
            window.Show();
            await Dispatcher.InvokeAsync(() => window.UpdateLayout(), DispatcherPriority.ApplicationIdle);
            var bitmap = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(window);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var image = File.Create(Path.Combine(root, "capture-queue.png"))) encoder.Save(image);
            window.Close();
            clock.Now += TimeSpan.FromSeconds(61);
            fake.CaptureFailure = null;
            fake.FailLibrary = true;
            await CaptureTickAsync();
            Require(_captureOutbox.Items.Count == 0 && _captureRefreshDocumentId == "first" &&
                CaptureStatusText.Text.Contains("Delivered to service"), "Failed refresh was treated as failed delivery.");
            var deliveries = fake.CaptureCalls;
            fake.FailLibrary = false;
            _captureCheckAfter = default;
            await CaptureTickAsync();
            Require(fake.CaptureCalls == deliveries && _editor.Document?.Id == "first" && _captureRefreshDocumentId is null,
                "Refresh retry resent content or failed to open the delivered article.");
            Require(new CaptureOutbox(store).Items.Count == 0, "Delivered captures survived in protected storage.");
            await File.WriteAllTextAsync(Path.Combine(root, "capture-outbox-result.json"),
                JsonSerializer.Serialize(new
                {
                    status = "passed",
                    largeCapture = 150000,
                    responsiveWhileSending = true,
                    dependentAppend = true,
                    rateLimitRetention = true,
                    refreshDoesNotResend = true
                }));
        }
        finally
        {
            ClearDocumentDisplay();
            DocumentsGrid.ItemsSource = null;
            _library = null; _editor = null; _readingWindow = null; _client = null;
            _captureOutbox = null; _captureTokenProvider = null; _captureServiceUrl = null;
            _captureRefreshDocumentId = null; _pendingCaptureCreateId = null; _captureCheckAfter = default;
        }
    }
    private sealed class CaptureSmokeToken : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => new("synthetic-only");
    }
    private sealed class CaptureSmokeClock : TimeProvider
    {
        public DateTimeOffset Now = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => Now;
    }
}
