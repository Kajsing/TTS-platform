using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Runtime.CompilerServices;
using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class BatchImportDialog : Window
{
    private readonly PreparedBatchImportRunner _runner;
    private readonly ObservableCollection<BatchFileDisplay> _files;
    private CancellationTokenSource? _cancellation;
    private Task _optionsCleanup = Task.CompletedTask;
    private bool _closed;

    public BatchImportDialog(
        IReaderServiceClient client,
        IReadOnlyList<string> filePaths,
        IReadOnlyList<ReaderFolder> folders,
        string? initialFolderId)
    {
        if (filePaths.Count is < 1 or > 100)
            throw new ArgumentOutOfRangeException(nameof(filePaths), "Select between 1 and 100 files.");
        _runner = new PreparedBatchImportRunner(client);
        _files = new ObservableCollection<BatchFileDisplay>(
            filePaths.Select(path => new BatchFileDisplay(CreateInput(path))));
        InitializeComponent();
        FileGrid.ItemsSource = _files;
        FileGrid.SelectedIndex = 0;
        FileGrid.SelectionChanged += (_, _) => ShowSelectedParts();
        SummaryText.Text = $"{_files.Count:N0} file(s). Review every file's parts before saving. Each file commits all its parts together.";
        Progress.Maximum = _files.Count;
        var destinations = new List<FolderDestination> { new(null, "All articles (no folder)") };
        destinations.AddRange(folders.Where(folder => !folder.PrivacyLocked || folder.PrivacyUnlocked)
            .Select(folder => new FolderDestination(folder.Id, folder.Name)));
        DestinationComboBox.ItemsSource = destinations;
        DestinationComboBox.SelectedItem = destinations.FirstOrDefault(
            item => string.Equals(item.Id, initialFolderId, StringComparison.Ordinal)) ?? destinations[0];
        HeadingLevelComboBox.ItemsSource = Enumerable.Range(1, 9).ToArray();
        HeadingLevelComboBox.SelectedItem = 1;
        DestinationComboBox.SelectionChanged += OptionsChanged;
        HeadingLevelComboBox.SelectionChanged += OptionsChanged;
        MaxCharactersTextBox.TextChanged += OptionsChanged;
        AllowDuplicateCheckBox.Click += OptionsChanged;
        KeepSourceCheckBox.Click += OptionsChanged;
        Closing += OnClosing;
        Closed += (_, _) =>
        {
            _closed = true;
            _cancellation?.Cancel();
            _ = _runner.DiscardAsync();
        };
    }

    public IReadOnlyList<ReaderDocument> ImportedDocuments { get; private set; } = [];

    private async void StartButton_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(commit: false);

    private async void ImportButton_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(commit: true);

    private async Task RunAsync(bool commit, CancellationToken cancellationToken = default)
    {
        if (_cancellation is not null || !TryOptions(out var options)) return;
        _cancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        Progress.Value = 0;
        SetBusy(true);
        StatusText.Text = commit ? "Importing the reviewed parts..." : "Reading files and preparing part previews. No articles are being saved.";
        try
        {
            var result = commit
                ? await _runner.CommitAsync(options, ApplyProgress, _cancellation.Token)
                : await _runner.PrepareAsync(_files.Select(file => file.Input).ToArray(),
                    options, ApplyProgress, _cancellation.Token);
            if (_closed) return;
            ApplyResult(result);
            StatusText.Text = commit
                ? $"Finished: {result.Completed:N0} file(s) imported as {result.Documents.Count:N0} article(s), " +
                    $"{result.Failed:N0} failed, {result.Cancelled:N0} skipped, {result.Unknown:N0} with unknown outcome." +
                    (result.Unknown > 0 ? " Refresh the library and check unknown files before importing them again." : "")
                : $"Preview ready: {result.Ready:N0} file(s) ready, {result.Failed:N0} failed, {result.Cancelled:N0} cancelled. " +
                    "Select each file to review its parts, then choose Import reviewed parts.";
        }
        catch (Exception exception) when (exception is ArgumentException or InvalidOperationException)
        {
            if (!_closed) StatusText.Text = exception.Message;
        }
        finally
        {
            ImportedDocuments = _runner.Result.Documents;
            _cancellation?.Dispose();
            _cancellation = null;
            if (!_closed) SetBusy(false);
        }
    }

    private void ApplyProgress(PreparedBatchImportFile file)
    {
        if (_closed) return;
        _files.First(display => ReferenceEquals(display.Input, file.Input)).Apply(file);
        Progress.Value = _files.Count(display => display.State is not
            (PreparedBatchImportStatus.Waiting or PreparedBatchImportStatus.Previewing or PreparedBatchImportStatus.Committing));
        ImportedDocuments = _runner.Result.Documents;
        ShowSelectedParts();
    }

    private void ApplyResult(PreparedBatchImportResult result)
    {
        foreach (var file in result.Files) ApplyProgress(file);
        ImportedDocuments = result.Documents;
    }

    private async void OptionsChanged(object sender, RoutedEventArgs e)
    {
        ImportButton.IsEnabled = false;
        _optionsCleanup = _runner.DiscardAsync();
        await _optionsCleanup;
        if (_closed) return;
        ApplyResult(_runner.Result);
        StatusText.Text = "Options changed. Preview parts again before importing.";
    }

    internal async Task PrepareForSmokeAsync(CancellationToken cancellationToken)
    {
        for (var attempt = 0; attempt < 100 && !IsLoaded; attempt++)
            await Task.Delay(20, cancellationToken);
        if (!IsLoaded || _closed || _files.Count != 2)
            throw new InvalidOperationException("The isolated two-file batch dialog did not load.");
        MaxCharactersTextBox.Text = "160";
        HeadingLevelComboBox.SelectedItem = 1;
        await _optionsCleanup;
        await RunAsync(commit: false, cancellationToken);
        VerifyReviewedSmokeParts();
        MaxCharactersTextBox.Text = "161";
        await _optionsCleanup;
        if (ImportButton.IsEnabled || _runner.Result.Files.Any(file => file.PartsPreview is not null))
            throw new InvalidOperationException("Changing a batch option retained a stale part review.");
        MaxCharactersTextBox.Text = "160";
        await _optionsCleanup;
        await RunAsync(commit: false, cancellationToken);
        VerifyReviewedSmokeParts();
    }

    internal async Task CommitForSmokeAsync()
    {
        await RunAsync(commit: true);
        if (_runner.Result.Completed != 2 || ImportedDocuments.Count != 6 || _runner.Result.Unknown != 0)
            throw new InvalidOperationException("The two reviewed batch files did not acknowledge all six parts.");
    }

    private void VerifyReviewedSmokeParts()
    {
        var files = _runner.Result.Files;
        if (!ImportButton.IsEnabled || files.Count != 2 ||
            files.Any(file => file.Status != PreparedBatchImportStatus.Ready || file.PartsPreview?.Parts.Count != 3) ||
            ImportedDocuments.Count != 0)
            throw new InvalidOperationException("The batch preview did not expose six reviewed parts before writing.");
    }

    private bool TryOptions(out PreparedBatchImportOptions options)
    {
        options = new();
        if (!int.TryParse(MaxCharactersTextBox.Text, NumberStyles.None, CultureInfo.InvariantCulture,
            out var maximum) || maximum is < 1 or > 1_000_000)
        {
            StatusText.Text = "Maximum characters per part must be a whole number between 1 and 1,000,000.";
            return false;
        }
        if (DestinationComboBox.SelectedItem is not FolderDestination destination ||
            HeadingLevelComboBox.SelectedItem is not int level)
        {
            StatusText.Text = "Choose a destination and chapter heading level.";
            return false;
        }
        options = new(maximum, level, destination.Id, AllowDuplicateCheckBox.IsChecked == true,
            KeepSourceCheckBox.IsChecked == true);
        return true;
    }

    private void CancelRemainingButton_Click(object sender, RoutedEventArgs e)
    {
        _cancellation?.Cancel();
        StatusText.Text = "Stopping unstarted work. A saving request may already have committed; acknowledged articles are kept.";
    }

    private async void CloseButton_Click(object sender, RoutedEventArgs e)
    {
        if (_cancellation is not null) return;
        await _runner.DiscardAsync();
        if (!_closed) DialogResult = ImportedDocuments.Count > 0;
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cancellation is null) return;
        e.Cancel = true;
        _cancellation.Cancel();
        StatusText.Text = "Stopping unstarted work. Wait for the current request outcome, then close.";
    }

    private void SetBusy(bool busy)
    {
        DestinationComboBox.IsEnabled = !busy;
        AllowDuplicateCheckBox.IsEnabled = !busy;
        KeepSourceCheckBox.IsEnabled = !busy;
        MaxCharactersTextBox.IsEnabled = !busy;
        HeadingLevelComboBox.IsEnabled = !busy;
        StartButton.IsEnabled = !busy;
        ImportButton.IsEnabled = !busy && TryOptions(out var options) && _runner.CanCommit(options);
        CancelRemainingButton.IsEnabled = busy;
        CloseButton.IsEnabled = !busy;
    }

    private void ShowSelectedParts()
    {
        PartsGrid.ItemsSource = FileGrid.SelectedItem is BatchFileDisplay selected
            ? selected.Parts.Select(part => new PartDisplay(part)).ToArray() : null;
    }

    private static BatchImportInput CreateInput(string path) => new(
        Path.GetFileName(path), ContentTypeFor(path), Path.GetFileNameWithoutExtension(path),
        () => new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read,
            bufferSize: 64 * 1024, useAsync: true));

    private static string ContentTypeFor(string path) => Path.GetExtension(path).ToLowerInvariant() switch
    {
        ".txt" => "text/plain",
        ".md" or ".markdown" => "text/markdown",
        ".html" or ".htm" => "text/html",
        ".docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".epub" => "application/epub+zip",
        _ => "application/octet-stream",
    };

    private sealed record FolderDestination(string? Id, string Name);
    private sealed record PartDisplay(ReaderImportPartPreview Part)
    {
        public int Number => Part.Number;
        public string Title => Part.Title;
        public string ChapterRange => Part.FirstChapter == Part.LastChapter
            ? $"{Part.FirstChapter}: {Part.ChapterStartTitle}"
            : $"{Part.FirstChapter}–{Part.LastChapter}: {Part.ChapterStartTitle} – {Part.ChapterEndTitle}";
        public int Codepoints => Part.Codepoints;
        public int Utf16Units => Part.Utf16Units;
        public int Blocks => Part.Blocks;
    }

    private sealed class BatchFileDisplay(BatchImportInput input) : INotifyPropertyChanged
    {
        private string _status = "Waiting";
        private string _message = "";
        public BatchImportInput Input { get; } = input;
        public string FileName => Input.FileName;
        public PreparedBatchImportStatus State { get; private set; }
        public IReadOnlyList<ReaderImportPartPreview> Parts { get; private set; } = [];
        public string Status { get => _status; private set => SetField(ref _status, value); }
        public string Message { get => _message; private set => SetField(ref _message, value); }
        public event PropertyChangedEventHandler? PropertyChanged;

        public void Apply(PreparedBatchImportFile file)
        {
            State = file.Status;
            Status = file.Status switch
            {
                PreparedBatchImportStatus.Previewing => "Previewing",
                PreparedBatchImportStatus.Ready => "Review parts",
                PreparedBatchImportStatus.Committing => "Saving parts",
                PreparedBatchImportStatus.Completed => "Imported",
                PreparedBatchImportStatus.Failed => "Failed",
                PreparedBatchImportStatus.Cancelled => "Skipped",
                PreparedBatchImportStatus.OutcomeUnknown => "Check library",
                _ => "Waiting",
            };
            Message = file.Message;
            Parts = file.PartsPreview?.Parts ?? [];
        }

        private void SetField(ref string field, string value, [CallerMemberName] string? name = null)
        {
            if (field == value) return;
            field = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
        }
    }
}
