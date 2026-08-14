using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Win32;
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
        await RefreshExportFormatsAsync();
        await RefreshQueueAsync();
        await RefreshBookmarksAsync();
        await RefreshExportsAsync();
    }

    private async Task RefreshExportFormatsAsync()
    {
        try
        {
            var selected = ExportFormatComboBox.SelectedItem as string;
            var capabilities = await _client.GetCapabilitiesAsync();
            var formats = capabilities.Exports?.Formats
                .Where(value => value is "wav" or "mp3")
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray() ?? [];
            ExportFormatComboBox.Items.Clear();
            foreach (var format in formats)
            {
                ExportFormatComboBox.Items.Add(format.ToUpperInvariant());
            }
            var preferred = formats.Contains("mp3", StringComparer.OrdinalIgnoreCase)
                ? "MP3"
                : formats.FirstOrDefault()?.ToUpperInvariant();
            ExportFormatComboBox.SelectedItem = selected is not null &&
                formats.Contains(selected, StringComparer.OrdinalIgnoreCase)
                    ? selected
                    : preferred;
            ExportCurrentButton.IsEnabled = formats.Length > 0;
            ExportQueueButton.IsEnabled = formats.Length > 0;
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            ExportFormatComboBox.Items.Clear();
            ExportCurrentButton.IsEnabled = false;
            ExportQueueButton.IsEnabled = false;
            StatusText.Text = exception.Message;
        }
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
        await CreateExportAsync(
            new CreateExportRequest(
                DocumentIds: [_currentDocument.Id],
                AudioFormat: SelectedExportFormat()));
    }

    private async void ExportQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_queue.Count == 0)
        {
            StatusText.Text = "The queue is empty.";
            return;
        }
        await CreateExportAsync(
            new CreateExportRequest(
                QueueItemIds: _queue.Select(item => item.Item.Id).ToArray(),
                AudioFormat: SelectedExportFormat()));
    }

    private async Task CreateExportAsync(CreateExportRequest request)
    {
        try
        {
            var job = await _client.CreateExportAsync(request);
            StatusText.Text =
                $"{(job.AudioFormat ?? "wav").ToUpperInvariant()} export {job.Id[..8]} queued; " +
                "it continues if this window closes.";
            WorkflowTabs.SelectedIndex = 2;
            await RefreshExportsAsync();
        }
        catch (Exception exception) when (IsServiceError(exception))
        {
            StatusText.Text = exception.Message;
        }
    }

    private string SelectedExportFormat() =>
        ExportFormatComboBox.SelectedItem is string format
            ? format.ToLowerInvariant()
            : "wav";

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

    private async void SaveExport_Click(object sender, RoutedEventArgs e)
    {
        if (ExportGrid.SelectedItem is not ExportDisplayItem selected)
        {
            StatusText.Text = "Select a completed export first.";
            return;
        }
        if (!string.Equals(selected.Job.Status, "completed", StringComparison.OrdinalIgnoreCase) ||
            selected.Job.OutputFiles.Count != 1)
        {
            StatusText.Text = "Save as is available for a completed single-article export.";
            return;
        }
        var extension = string.Equals(
            selected.Job.AudioFormat,
            "mp3",
            StringComparison.OrdinalIgnoreCase)
            ? ".mp3"
            : ".wav";
        var dialog = new SaveFileDialog
        {
            Title = "Save Reader audio export",
            FileName = selected.Job.OutputFiles[0],
            DefaultExt = extension,
            AddExtension = true,
            OverwritePrompt = true,
            Filter = extension == ".mp3"
                ? "MP3 audio (*.mp3)|*.mp3|All files (*.*)|*.*"
                : "WAV audio (*.wav)|*.wav|All files (*.*)|*.*",
        };
        if (dialog.ShowDialog(this) != true)
        {
            return;
        }
        string? temporary = null;
        try
        {
            var destination = Path.GetFullPath(dialog.FileName);
            var directory = Path.GetDirectoryName(destination) ??
                throw new InvalidOperationException("The selected export folder is invalid.");
            temporary = Path.Combine(
                directory,
                $".{Path.GetFileName(destination)}.{Guid.NewGuid():N}.part");
            await using (var output = new FileStream(
                temporary,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                64 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan))
            {
                await _client.DownloadExportResultAsync(selected.Job.Id, 0, output);
                await output.FlushAsync();
            }
            File.Move(temporary, destination, overwrite: true);
            StatusText.Text = $"Saved {Path.GetFileName(destination)}.";
        }
        catch (Exception exception) when (
            IsServiceError(exception) ||
            exception is IOException or UnauthorizedAccessException or
                ArgumentException or NotSupportedException)
        {
            StatusText.Text = $"Could not save the export: {exception.Message}";
        }
        finally
        {
            if (temporary is not null)
            {
                try
                {
                    File.Delete(temporary);
                }
                catch (Exception cleanupException) when (
                    cleanupException is IOException or UnauthorizedAccessException)
                {
                    // The save error is already shown; do not replace it with cleanup noise.
                }
            }
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
        public string Format => (Job.AudioFormat ?? "wav").ToUpperInvariant();
        public string Status => Job.Status;
        public string Progress => $"{Job.CompletedDocuments}/{Job.TotalDocuments}";
        public string OutputSummary => Job.OutputFiles.Count > 0
            ? string.Join(", ", Job.OutputFiles)
            : Job.ErrorMessage ?? string.Empty;
    }
}
