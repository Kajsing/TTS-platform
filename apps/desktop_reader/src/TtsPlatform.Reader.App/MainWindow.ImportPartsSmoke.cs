using System.IO;
using System.Net.Http;
using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private async Task<object> RunImportPartsSmokeAsync(AgentSmokeScenario scenario)
    {
        var gate = new ImportPreviewCleanupGate();
        using var http = new HttpClient(gate) { Timeout = TimeSpan.FromSeconds(15) };
        _client = new ReaderServiceClient(http, scenario.ServiceUrl,
            new FileTokenProvider(_settings.EffectiveTokenSource.Path));
        _editor = new DocumentEditor(_client);
        _library = new LibraryPager(_client);
        _readingWindow = new ReadingWindowPager(_client);
        DocumentsGrid.ItemsSource = _library.Documents;
        var path = Path.Combine(scenario.Root, "chaptered.md");
        var bodies = Enumerable.Range(1, 3).Select(number =>
            $"# Chapter {number}\n\n" + string.Concat(Enumerable.Repeat("A chapter sentence. ", 4)).Trim()).ToArray();
        File.WriteAllText(path, string.Join("\n\n", bodies));
        var dialog = new ImportPreviewDialog(_client, path, scenario.FolderId) { Owner = this };
        Exception? failure = null;
        var completed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(45));
        dialog.Loaded += async (_, _) =>
        {
            try
            {
                await dialog.VerifyPartsForSmokeAsync(deadline.Token);
                gate.Arm();
                var sourceRefresh = dialog.RefreshForSmokeAsync();
                await gate.Entered.WaitAsync(deadline.Token);
                var previewsBefore = gate.PreviewRequests;
                await dialog.RefreshForSmokeAsync();
                if (gate.PreviewRequests != previewsBefore)
                    throw new InvalidOperationException("Competing preview escaped operation ownership during cleanup.");
                gate.Release();
                await sourceRefresh.WaitAsync(deadline.Token);
                if (gate.PreviewRequests != previewsBefore + 1)
                    throw new InvalidOperationException("Source refresh did not run exactly once after cleanup.");
                var before = await _client.GetDocumentsByFolderAsync(folderId: scenario.FolderId, cancellationToken: deadline.Token);
                if (before.Documents.Count != 0) throw new InvalidOperationException("Import preview saved articles before confirmation.");
                CaptureSmokeWindow(dialog, Path.Combine(scenario.Root, "import-parts-preview.png"));
                await dialog.CommitForSmokeAsync();
                if (dialog.ImportedDocuments.Count != 3) throw new InvalidOperationException("Reviewed desktop parts were not committed.");
            }
            catch (Exception exception)
            {
                failure = exception;
                dialog.Close();
            }
            finally { completed.TrySetResult(); }
        };
        _ = dialog.ShowDialog();
        await completed.Task.WaitAsync(deadline.Token);
        if (failure is not null) throw new InvalidOperationException("Desktop import parts smoke failed.", failure);
        var batchPaths = new[] { Path.Combine(scenario.Root, "batch-one.md"), Path.Combine(scenario.Root, "batch-two.md") };
        File.WriteAllText(batchPaths[0], string.Join("\n\n", bodies).Replace("A chapter", "Batch one", StringComparison.Ordinal));
        File.WriteAllText(batchPaths[1], string.Join("\n\n", bodies).Replace("A chapter", "Batch two", StringComparison.Ordinal));
        var folders = await _client.GetFoldersAsync(deadline.Token);
        var batch = new BatchImportDialog(_client, batchPaths, folders.Folders, scenario.FolderId) { Owner = this };
        batch.Show();
        await batch.PrepareForSmokeAsync(deadline.Token);
        var beforeBatchCommit = await _client.GetDocumentsByFolderAsync(folderId: scenario.FolderId, cancellationToken: deadline.Token);
        if (beforeBatchCommit.Documents.Count != 3) throw new InvalidOperationException("Batch review saved files before confirmation.");
        CaptureSmokeWindow(batch, Path.Combine(scenario.Root, "batch-parts-preview.png"));
        await batch.CommitForSmokeAsync();
        batch.Close();
        await _library.RefreshAsync(folderId: scenario.FolderId, cancellationToken: deadline.Token);
        if (_library.Documents.Count != 9) throw new InvalidOperationException("The library did not contain all single/batch reviewed parts.");
        var first = _library.Documents.Single(item => item.Id == dialog.ImportedDocuments[0].Id);
        await LoadDocumentAsync(first);
        var chapterCount = _continuousDocument is not null ? _chapters.Count : _pagedChapterIndex?.Chapters.Count;
        if (chapterCount != 1 || ChapterToolbar.Visibility != Visibility.Visible)
            throw new InvalidOperationException("A committed import part did not expose its real chapter selector.");
        CaptureSmokeWindow(this, Path.Combine(scenario.Root, "import-parts-reader.png"));
        return new
        {
            preview_before_save = true,
            default_characters = 900000,
            reviewed_limit = 160,
            explicit_heading_level = true,
            stale_options_rejected = true,
            oversized_chapter_rejected = true,
            cleanup_operation_ownership = true,
            batch_review_before_save = true,
            batch_parts = batch.ImportedDocuments.Count,
            parts = dialog.ImportedDocuments.Count,
            chapter_selector = true,
            document_ids = dialog.ImportedDocuments.Select(item => item.Id).ToArray(),
            batch_document_ids = batch.ImportedDocuments.Select(item => item.Id).ToArray()
        };
    }

    private sealed class ImportPreviewCleanupGate : DelegatingHandler
    {
        private bool _armed;
        private readonly TaskCompletionSource _entered = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public ImportPreviewCleanupGate() : base(new HttpClientHandler()) { }
        public Task Entered => _entered.Task;
        public int PreviewRequests { get; private set; }
        public void Arm() => _armed = true;
        public void Release() => _release.TrySetResult();
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (request.Method == HttpMethod.Post && path == "/v1/reader/imports/preview") PreviewRequests++;
            if (_armed && request.Method == HttpMethod.Delete && path.StartsWith("/v1/reader/imports/", StringComparison.Ordinal))
            {
                _armed = false;
                _entered.TrySetResult();
                await _release.Task.WaitAsync(cancellationToken);
            }
            return await base.SendAsync(request, cancellationToken);
        }
    }
}
