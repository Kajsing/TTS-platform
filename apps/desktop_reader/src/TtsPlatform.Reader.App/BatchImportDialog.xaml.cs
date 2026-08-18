using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class BatchImportDialog : Window
{
    private readonly IReaderServiceClient _client;
    private readonly ObservableCollection<BatchFileDisplay> _files;
    private CancellationTokenSource? _cancellation;

    public BatchImportDialog(
        IReaderServiceClient client,
        IReadOnlyList<string> filePaths,
        IReadOnlyList<ReaderFolder> folders,
        string? initialFolderId)
    {
        _client = client;
        InitializeComponent();
        _files = new ObservableCollection<BatchFileDisplay>(
            filePaths.Select(path => new BatchFileDisplay(CreateInput(path))));
        FileGrid.ItemsSource = _files;
        SummaryText.Text = $"{_files.Count:N0} file(s). Each successful file becomes one article.";
        Progress.Maximum = _files.Count;
        var destinations = new List<FolderDestination>
        {
            new(null, "All articles (no folder)"),
        };
        destinations.AddRange(folders
            .Where(folder => !folder.PrivacyLocked || folder.PrivacyUnlocked)
            .Select(folder => new FolderDestination(folder.Id, folder.Name)));
        DestinationComboBox.ItemsSource = destinations;
        DestinationComboBox.SelectedItem = destinations.FirstOrDefault(
            item => string.Equals(item.Id, initialFolderId, StringComparison.Ordinal)) ?? destinations[0];
        Closing += (_, _) => _cancellation?.Cancel();
    }

    public IReadOnlyList<ReaderDocument> ImportedDocuments { get; private set; } = [];

    private async void StartButton_Click(object sender, RoutedEventArgs e)
    {
        if (_cancellation is not null ||
            DestinationComboBox.SelectedItem is not FolderDestination destination)
        {
            return;
        }
        _cancellation = new CancellationTokenSource();
        SetBusy(true);
        var completed = 0;
        try
        {
            var runner = new BatchImportRunner(_client);
            var result = await runner.RunAsync(
                _files.Select(item => item.Input).ToArray(),
                new BatchImportOptions(
                    destination.Id,
                    AllowDuplicateCheckBox.IsChecked == true,
                    KeepSourceCheckBox.IsChecked == true),
                item =>
                {
                    var display = _files.First(file => ReferenceEquals(file.Input, item.Input));
                    display.Apply(item);
                    if (item.Status is BatchImportStatus.Completed or
                        BatchImportStatus.Failed or BatchImportStatus.Cancelled)
                    {
                        completed++;
                        Progress.Value = completed;
                    }
                },
                _cancellation.Token);
            ImportedDocuments = result.Files
                .Where(item => item.Document is not null)
                .Select(item => item.Document!)
                .ToArray();
            StatusText.Text =
                $"Finished: {result.Completed:N0} imported, {result.Failed:N0} failed, " +
                $"{result.Cancelled:N0} cancelled.";
        }
        catch (ArgumentOutOfRangeException exception)
        {
            StatusText.Text = exception.Message;
        }
        finally
        {
            _cancellation.Dispose();
            _cancellation = null;
            SetBusy(false);
        }
    }

    private void CancelRemainingButton_Click(object sender, RoutedEventArgs e)
    {
        _cancellation?.Cancel();
        StatusText.Text = "Stopping. Articles already imported will be kept.";
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e)
    {
        if (_cancellation is null)
        {
            DialogResult = ImportedDocuments.Count > 0;
        }
    }

    private void SetBusy(bool busy)
    {
        DestinationComboBox.IsEnabled = !busy;
        AllowDuplicateCheckBox.IsEnabled = !busy;
        KeepSourceCheckBox.IsEnabled = !busy;
        StartButton.IsEnabled = !busy;
        CancelRemainingButton.IsEnabled = busy;
        CloseButton.IsEnabled = !busy;
    }

    private static BatchImportInput CreateInput(string path) =>
        new(
            Path.GetFileName(path),
            ContentTypeFor(path),
            Path.GetFileNameWithoutExtension(path),
            () => new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                bufferSize: 64 * 1024,
                useAsync: true));

    private static string ContentTypeFor(string filePath) =>
        Path.GetExtension(filePath).ToLowerInvariant() switch
        {
            ".txt" => "text/plain",
            ".md" or ".markdown" => "text/markdown",
            ".html" or ".htm" => "text/html",
            ".docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".epub" => "application/epub+zip",
            _ => "application/octet-stream",
        };

    private sealed record FolderDestination(string? Id, string Name);

    private sealed class BatchFileDisplay : INotifyPropertyChanged
    {
        private string _status = "Waiting";
        private string _message = string.Empty;

        public BatchFileDisplay(BatchImportInput input)
        {
            Input = input;
        }

        public BatchImportInput Input { get; }
        public string FileName => Input.FileName;
        public string Status
        {
            get => _status;
            private set => SetField(ref _status, value);
        }
        public string Message
        {
            get => _message;
            private set => SetField(ref _message, value);
        }

        public event PropertyChangedEventHandler? PropertyChanged;

        public void Apply(BatchImportProgress progress)
        {
            Status = progress.Status switch
            {
                BatchImportStatus.Previewing => "Previewing",
                BatchImportStatus.Committing => "Saving",
                BatchImportStatus.Completed => "Imported",
                BatchImportStatus.Failed => "Failed",
                BatchImportStatus.Cancelled => "Cancelled",
                _ => "Waiting",
            };
            Message = progress.Message;
        }

        private void SetField(ref string field, string value, [CallerMemberName] string? name = null)
        {
            if (string.Equals(field, value, StringComparison.Ordinal))
            {
                return;
            }
            field = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
        }
    }
}
