using System.Reflection;
using System.Text.Json;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    // Isolated --smoke-test only; delayed fake HTTP replies exercise the real
    // WPF selection/load/delete paths without private articles or real audio.
    internal async Task VerifyDocumentSwitchAsync()
    {
        if (!_smokeTest || _playback is not null || _editor is not null)
            throw new InvalidOperationException("Document switch smoke requires an isolated Reader.");
        var client = DispatchProxy.Create<IReaderServiceClient, DocumentSwitchSmokeClient>();
        var fake = (DocumentSwitchSmokeClient)client;
        _client = client;
        _editor = new DocumentEditor(client);
        _library = new LibraryPager(client);
        DocumentsGrid.ItemsSource = _library.Documents;
        async Task Idle() => await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        static void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
        }
        void SelectWithoutLoading(ReaderDocument document)
        {
            _suppressDocumentSelectionLoad = true;
            try { DocumentsGrid.SelectedItem = _library.Documents.Single(item => item.Id == document.Id); }
            finally { _suppressDocumentSelectionLoad = false; }
        }
        try
        {
            await RefreshLibraryAsync();
            var first = fake.Documents[0];
            var second = fake.Documents[1];
            await LoadDocumentAsync(first);
            Require(_editor.Document?.Id == first.Id && DeleteDocumentButton.IsEnabled,
                "Initial article was not actionable after loading.");

            // The library row can be older than an appended/moved article.
            fake.Documents[1] = second with { RowVersion = 2, ContentRevision = 2 };
            await LoadDocumentAsync(second);
            Require(_editor.Document?.RowVersion == 2 && _editor.Document.ContentRevision == 2 &&
                ReferenceEquals(DocumentsGrid.SelectedItem, _editor.Document), "A stale library row caused a revision ghost.");
            await LoadDocumentAsync(first);
            var originalText = EditorTextBox.Text;
            var originalMapping = _continuousDocument;

            // While B is pending, do not delete A. A newer selection wins even
            // when B's blocks arrive later, and its metadata must never publish.
            fake.BlockGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            SelectWithoutLoading(second);
            var pending = LoadDocumentAsync(second);
            Require(_documentReloadInProgress && !DeleteDocumentButton.IsEnabled && !PlayPauseButton.IsEnabled,
                "Pending article load left destructive/playback controls enabled.");
            await DeleteDisplayedDocumentAsync(first);
            Require(fake.DeleteCalls == 0, "Delete targeted the previous editor during a pending selection.");
            var newer = LoadDocumentAsync(first);
            fake.BlockGate.SetResult(new BlockPage([fake.Block(second.Id)], null));
            await Task.WhenAll(pending, newer);
            fake.BlockGate = null;
            Require(_editor.Document?.Id == first.Id && EditorTextBox.Text == originalText &&
                ReferenceEquals(DocumentsGrid.SelectedItem, _editor.Document), "An older load overwrote a newer selection.");

            originalMapping = _continuousDocument;
            fake.FailBlocks = true;
            SelectWithoutLoading(second);
            await LoadDocumentAsync(second);
            Require(_editor.Document?.Id == first.Id && EditorTextBox.Text == originalText &&
                ReferenceEquals(_continuousDocument, originalMapping) && ReferenceEquals(DocumentsGrid.SelectedItem, _editor.Document) &&
                DeleteDocumentButton.IsEnabled && !EditorTextBox.IsReadOnly,
                "Failed load mixed editor state, retained the wrong selection, or left the editor locked.");
            fake.FailBlocks = false;

            // A successful delete must stay removed if refresh fails, and two
            // invocations/another selection must not send a second mutation.
            fake.DeleteGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
            fake.FailLibrary = true;
            var deletion = DeleteDisplayedDocumentAsync(first);
            Require(_documentMutationInProgress && !DeleteDocumentButton.IsEnabled && !DocumentsGrid.IsEnabled,
                "Pending delete did not guard the UI.");
            await DeleteDisplayedDocumentAsync(first);
            await LoadDocumentAsync(second);
            Require(fake.DeleteCalls == 1, "Concurrent delete was submitted twice.");
            fake.DeleteGate.SetResult(first with { DeletedAt = DateTimeOffset.UtcNow });
            await deletion;
            await Idle();
            Require(_library.Documents.All(item => item.Id != first.Id) && _editor.Document?.Id != first.Id &&
                !_documentMutationInProgress && DocumentsGrid.IsEnabled,
                "Deleted article survived a failed library refresh or locked the UI.");

            // A stale row for an externally deleted article must also disappear.
            fake.Documents[1] = fake.Documents[1] with { DeletedAt = DateTimeOffset.UtcNow };
            await LoadDocumentAsync(second);
            Require(_editor.Document is null && _library.Documents.Count == 0 &&
                EditorTextBox.Text.Length == 0 && !DeleteDocumentButton.IsEnabled && !PlayPauseButton.IsEnabled,
                "A deleted article remained visible or actionable.");
        }
        finally
        {
            ClearDocumentDisplay();
            DocumentsGrid.ItemsSource = null;
            _library = null;
            _editor = null;
            _readingWindow = null;
            _client = null;
        }
    }
}

public class DocumentSwitchSmokeClient : DispatchProxy
{
    private static readonly JsonElement Metadata = JsonSerializer.SerializeToElement(new { });
    public List<ReaderDocument> Documents { get; } = [Document("first"), Document("second")];
    public TaskCompletionSource<BlockPage>? BlockGate { get; set; }
    public TaskCompletionSource<ReaderDocument>? DeleteGate { get; set; }
    public bool FailBlocks { get; set; }
    public bool FailLibrary { get; set; }
    public int DeleteCalls { get; private set; }
    public TaskCompletionSource<CaptureReceipt>? CaptureGate { get; set; }
    public ReaderApiException? CaptureFailure { get; set; }
    public int CaptureCalls { get; private set; }
    private static ReaderDocument Document(string id) => new(id, $"Synthetic {id}", "clipboard",
        null, null, null, null, "inbox", DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch,
        DateTimeOffset.UnixEpoch, null, 1, 1, 1, 1, 20, Metadata);
    public ReaderBlock Block(string id) => new($"block-{id}", id, null, 0, "paragraph",
        $"Synthetic text {id}.", 20, "hash", 1, Metadata);

    protected override object? Invoke(MethodInfo? method, object?[]? args)
    {
        var id = args?.FirstOrDefault() as string;
        switch (method?.Name)
        {
            case nameof(IReaderServiceClient.DeliverCaptureAsync):
                CaptureCalls++;
                if (CaptureFailure is not null) return Task.FromException<CaptureReceipt>(CaptureFailure);
                return CaptureGate?.Task ?? Task.FromResult(new CaptureReceipt(id!, "first", "delivered"));
            case nameof(IReaderServiceClient.GetDocumentAsync):
                return Task.FromResult(Documents.Single(item => item.Id == id));
            case nameof(IReaderServiceClient.GetBlocksAsync):
                if (FailBlocks) return Task.FromException<BlockPage>(new ReaderApiException("synthetic", "Synthetic load failed.", 503));
                return id == "second" && BlockGate is not null ? BlockGate.Task :
                    Task.FromResult(new BlockPage([Block(id!)], null));
            case nameof(IReaderServiceClient.GetFoldersAsync):
                return Task.FromResult(new ReaderFolderPage([]));
            case nameof(IReaderServiceClient.GetDocumentsByFolderAsync):
                return FailLibrary ? Task.FromException<DocumentPage>(new ReaderApiException("synthetic", "Synthetic refresh failed.", 503)) :
                    Task.FromResult(new DocumentPage(Documents.ToArray(), null));
            case nameof(IReaderServiceClient.DeleteDocumentAsync):
                DeleteCalls++;
                return DeleteGate!.Task;
            default: throw new InvalidOperationException($"Unexpected API in document switch smoke: {method?.Name}");
        }
    }
}
