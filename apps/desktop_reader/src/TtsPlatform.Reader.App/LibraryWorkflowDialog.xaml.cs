using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Threading;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class LibraryWorkflowDialog : Window
{
    private readonly IReaderServiceClient _client;
    private readonly ReaderDocument? _currentDocument;
    private readonly ReaderCursor? _currentCursor;
    private readonly ObservableCollection<QueueDisplayItem> _queue = [];
    private readonly ObservableCollection<ReaderBookmark> _bookmarks = [];
    private readonly ObservableCollection<ExportDisplayItem> _exports = [];
    private readonly DispatcherTimer _refreshTimer;

    public LibraryWorkflowDialog(
        IReaderServiceClient client,
        ReaderDocument? currentDocument,
        ReaderCursor? currentCursor)
    {
        _client = client;
        _currentDocument = currentDocument;
        _currentCursor = currentCursor;
        InitializeComponent();
        QueueGrid.ItemsSource = _queue;
        BookmarkGrid.ItemsSource = _bookmarks;
        ExportGrid.ItemsSource = _exports;
        _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        _refreshTimer.Tick += async (_, _) => await RefreshExportsAsync();
        Loaded += async (_, _) =>
        {
            await RefreshAllAsync();
            _refreshTimer.Start();
        };
        Closed += (_, _) => _refreshTimer.Stop();
    }

    public string? SelectedDocumentId { get; private set; }
    public ReaderCursor? SelectedCursor { get; private set; }

    private async Task RefreshAllAsync()
    {
        await RefreshQueueAsync();
        await RefreshBookmarksAsync();
        await RefreshExportsAsync();
    }

    private async Task RefreshQueueAsync()
    {
        try
        {
            var page = await _client.GetQueueAsync();
            _queue.Clear();
            foreach (var item in page.Items.OrderBy(item => item.Ordinal))
            {
                var document = await _client.GetDocumentAsync(item.DocumentId);
                _queue.Add(new QueueDisplayItem(item, document.Title));
            }
            StatusText.Text = $"{_queue.Count} queue item(s).";
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async Task RefreshBookmarksAsync()
    {
        _bookmarks.Clear();
        if (_currentDocument is null)
        {
            return;
        }
        try
        {
            var page = await _client.GetBookmarksAsync(_currentDocument.Id);
            foreach (var bookmark in page.Bookmarks)
            {
                _bookmarks.Add(bookmark);
            }
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async Task RefreshExportsAsync()
    {
        try
        {
            var page = await _client.GetExportsAsync();
            _exports.Clear();
            foreach (var job in page.Jobs)
            {
                _exports.Add(new ExportDisplayItem(job));
            }
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAllAsync();

    private async void AddCurrent_Click(object sender, RoutedEventArgs e)
    {
        if (_currentDocument is null)
        {
            StatusText.Text = "Select a document first.";
            return;
        }
        try
        {
            await _client.AddQueueItemAsync(_currentDocument.Id);
            await RefreshQueueAsync();
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async void MoveUp_Click(object sender, RoutedEventArgs e) =>
        await MoveSelectedAsync(-1);

    private async void MoveDown_Click(object sender, RoutedEventArgs e) =>
        await MoveSelectedAsync(1);

    private async Task MoveSelectedAsync(int delta)
    {
        if (QueueGrid.SelectedItem is not QueueDisplayItem selected)
        {
            return;
        }
        var index = _queue.IndexOf(selected);
        var target = index + delta;
        if (target < 0 || target >= _queue.Count)
        {
            return;
        }
        var ids = _queue.Select(item => item.Item.Id).ToList();
        (ids[index], ids[target]) = (ids[target], ids[index]);
        try
        {
            await _client.ReorderQueueAsync(ids);
            await RefreshQueueAsync();
            QueueGrid.SelectedIndex = target;
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async void RemoveQueue_Click(object sender, RoutedEventArgs e)
    {
        if (QueueGrid.SelectedItem is not QueueDisplayItem selected)
        {
            return;
        }
        try
        {
            await _client.RemoveQueueItemAsync(selected.Item.Id, selected.Item.RowVersion);
            await RefreshQueueAsync();
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async void PlayQueue_Click(object sender, RoutedEventArgs e)
    {
        if (QueueGrid.SelectedItem is not QueueDisplayItem selected)
        {
            return;
        }
        try
        {
            await _client.ActivateQueueItemAsync(selected.Item.Id);
            SelectedDocumentId = selected.Item.DocumentId;
            DialogResult = true;
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async void AddBookmark_Click(object sender, RoutedEventArgs e)
    {
        if (_currentDocument is null || _currentCursor is null)
        {
            StatusText.Text = "Play or select a position before adding a bookmark.";
            return;
        }
        try
        {
            await _client.CreateBookmarkAsync(
                _currentDocument.Id,
                new CreateBookmarkRequest(
                    _currentCursor,
                    $"Block {_currentCursor.BlockOrdinal + 1}"));
            await RefreshBookmarksAsync();
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private void JumpBookmark_Click(object sender, RoutedEventArgs e)
    {
        if (BookmarkGrid.SelectedItem is not ReaderBookmark selected)
        {
            return;
        }
        SelectedDocumentId = selected.DocumentId;
        SelectedCursor = selected.Cursor;
        DialogResult = true;
    }

    private async void DeleteBookmark_Click(object sender, RoutedEventArgs e)
    {
        if (BookmarkGrid.SelectedItem is not ReaderBookmark selected)
        {
            return;
        }
        try
        {
            await _client.DeleteBookmarkAsync(selected.Id, selected.RowVersion);
            await RefreshBookmarksAsync();
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async void ExportCurrent_Click(object sender, RoutedEventArgs e)
    {
        if (_currentDocument is null)
        {
            StatusText.Text = "Select a document first.";
            return;
        }
        await CreateExportAsync(new CreateExportRequest(DocumentIds: [_currentDocument.Id]));
    }

    private async void ExportQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_queue.Count == 0)
        {
            StatusText.Text = "The queue is empty.";
            return;
        }
        await CreateExportAsync(
            new CreateExportRequest(QueueItemIds: _queue.Select(item => item.Item.Id).ToArray()));
    }

    private async Task CreateExportAsync(CreateExportRequest request)
    {
        try
        {
            var job = await _client.CreateExportAsync(request);
            StatusText.Text = $"WAV export {job.Id[..8]} queued; it continues if this window closes.";
            WorkflowTabs.SelectedIndex = 2;
            await RefreshExportsAsync();
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private async void CancelExport_Click(object sender, RoutedEventArgs e)
    {
        if (ExportGrid.SelectedItem is not ExportDisplayItem selected)
        {
            return;
        }
        try
        {
            await _client.CancelExportAsync(selected.Job.Id);
            await RefreshExportsAsync();
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private static bool IsServiceError(Exception exception) =>
        exception is ReaderApiException or ReaderServiceUnavailableException or
            ReaderTokenUnavailableException or NotSupportedException;

    private sealed record QueueDisplayItem(ReaderQueueItem Item, string Title)
    {
        public int Ordinal => Item.Ordinal + 1;
        public string Status => Item.Status;
    }

    private sealed record ExportDisplayItem(ReaderExportJob Job)
    {
        public DateTimeOffset CreatedAt => Job.CreatedAt;
        public string Status => Job.Status;
        public string Progress => $"{Job.CompletedDocuments}/{Job.TotalDocuments}";
        public string OutputSummary => Job.OutputFiles.Count > 0
            ? string.Join(", ", Job.OutputFiles)
            : Job.ErrorMessage ?? string.Empty;
    }
}
