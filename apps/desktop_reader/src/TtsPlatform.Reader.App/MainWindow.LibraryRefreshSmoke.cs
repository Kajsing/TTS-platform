using System.Reflection;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private async Task RunLibraryRefreshLifetimeSmokeAsync(ReaderDocument fixture)
    {
        if (!_smokeTest) throw new InvalidOperationException("Library lifetime probe requires isolated smoke mode.");
        var savedClient = _client;
        var savedLibrary = _library;
        var savedItems = DocumentsGrid.ItemsSource;
        var savedFilters = _folderFilters.ToArray();
        var savedSelection = FolderFilterComboBox.SelectedItem;
        var savedFooter = FooterText.Text;
        var savedMore = LoadMoreButton.IsEnabled;
        var savedSuppress = _suppressDocumentSelectionLoad;
        _suppressDocumentSelectionLoad = true;
        try
        {
            foreach (var holdFolders in new[] { true, false })
            {
                var oldClient = DispatchProxy.Create<IReaderServiceClient, FolderVisibilitySmokeClient>();
                var old = (FolderVisibilitySmokeClient)oldClient;
                var folders = new TaskCompletionSource<ReaderFolderPage>(TaskCreationOptions.RunContinuationsAsynchronously);
                var documents = new TaskCompletionSource<DocumentPage>(TaskCreationOptions.RunContinuationsAsynchronously);
                old.PendingFolders = holdFolders ? folders.Task : null;
                old.PendingDocuments = holdFolders ? null : documents.Task;
                _client = oldClient;
                _library = new LibraryPager(oldClient);
                DocumentsGrid.ItemsSource = _library.Documents;
                _refreshingFolders = true;
                _folderFilters.Clear();
                _folderFilters.Add(new(null, "All articles", false, true));
                FolderFilterComboBox.SelectedItem = _folderFilters[0];
                _refreshingFolders = false;
                using var cancelled = new CancellationTokenSource();
                var pending = RefreshLibraryAsync(cancellationToken: cancelled.Token);
                if (pending.IsCompleted || old.FolderReads != 1 || old.DocumentReads != (holdFolders ? 0 : 1))
                    throw new InvalidOperationException("Library lifetime fixture did not hold the expected request.");

                // Simulate client/library replacement while the old transport ignores cancellation.
                var replacement = DispatchProxy.Create<IReaderServiceClient, FolderVisibilitySmokeClient>();
                var current = (FolderVisibilitySmokeClient)replacement;
                _client = replacement;
                _library = new LibraryPager(replacement);
                DocumentsGrid.ItemsSource = _library.Documents;
                _refreshingFolders = true;
                _folderFilters.Clear();
                _folderFilters.Add(new(null, "New workspace", false, true));
                FolderFilterComboBox.SelectedItem = _folderFilters[0];
                _refreshingFolders = false;
                FooterText.Text = "New workspace";
                LoadMoreButton.IsEnabled = false;
                if (holdFolders) cancelled.Cancel();
                folders.TrySetResult(new ReaderFolderPage([]));
                documents.TrySetResult(new DocumentPage([fixture with { FolderId = null }], "late-cursor"));
                try { await pending; }
                catch (OperationCanceledException) when (cancelled.IsCancellationRequested) { }
                if (_folderFilters.Count != 1 || _folderFilters[0].DisplayName != "New workspace" ||
                    FooterText.Text != "New workspace" || LoadMoreButton.IsEnabled || _library.Documents.Count != 0 ||
                    current.FolderReads != 0 || current.DocumentReads != 0 ||
                    (holdFolders && (old.DocumentReads != 0 || !old.LastFolderCancellation.IsCancellationRequested)))
                    throw new InvalidOperationException("An obsolete library refresh touched the replacement workspace.");
            }
        }
        finally
        {
            _client = savedClient;
            _library = savedLibrary;
            DocumentsGrid.ItemsSource = savedItems;
            _refreshingFolders = true;
            _folderFilters.Clear();
            foreach (var filter in savedFilters) _folderFilters.Add(filter);
            FolderFilterComboBox.SelectedItem = savedSelection;
            _refreshingFolders = false;
            FooterText.Text = savedFooter;
            LoadMoreButton.IsEnabled = savedMore;
            _suppressDocumentSelectionLoad = savedSuppress;
        }
    }
}
