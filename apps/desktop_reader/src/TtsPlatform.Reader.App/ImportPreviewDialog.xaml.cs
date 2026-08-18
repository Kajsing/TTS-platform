using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class ImportPreviewDialog : Window
{
    private readonly IReaderServiceClient _client;
    private readonly string _filePath;
    private readonly string? _folderId;
    private readonly ObservableCollection<string> _structure = [];
    private readonly ObservableCollection<string> _samples = [];
    private ReaderImportPreview? _preview;
    private CancellationTokenSource? _operationCancellation;
    private bool _committed;

    public ImportPreviewDialog(
        IReaderServiceClient client,
        string filePath,
        string? folderId = null)
    {
        _client = client;
        _filePath = filePath;
        _folderId = folderId;
        InitializeComponent();
        FileNameText.Text = Path.GetFileName(filePath);
        TitleTextBox.Text = Path.GetFileNameWithoutExtension(filePath);
        StructureList.ItemsSource = _structure;
        SampleList.ItemsSource = _samples;
        ImportButton.Content = folderId is null ? "Import to All articles" : "Import to selected folder";
        Loaded += ImportPreviewDialog_Loaded;
        Closed += ImportPreviewDialog_Closed;
    }

    public ReaderDocument? ImportedDocument { get; private set; }

    private async void ImportPreviewDialog_Loaded(object sender, RoutedEventArgs e) =>
        await PreviewAsync();

    private async void PreviewButton_Click(object sender, RoutedEventArgs e) =>
        await PreviewAsync();

    private async Task PreviewAsync()
    {
        if (_operationCancellation is not null)
        {
            return;
        }
        await DiscardPreviewAsync();
        _operationCancellation = new CancellationTokenSource();
        SetBusy(true, "Reading and checking the document...");
        try
        {
            await using var input = new FileStream(
                _filePath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                bufferSize: 64 * 1024,
                useAsync: true);
            _preview = await _client.PreviewImportAsync(
                new ImportDocumentRequest(
                    Path.GetFileName(_filePath),
                    ContentTypeFor(_filePath),
                    EmptyToNull(TitleTextBox.Text),
                    EmptyToNull(LanguageTextBox.Text),
                    KeepSourceCheckBox.IsChecked == true),
                input,
                _operationCancellation.Token);
            ShowPreview(_preview);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "Import preview cancelled.";
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or
                ReaderApiException or ReaderServiceUnavailableException)
        {
            StatusText.Text = $"Import preview: {exception.Message}";
        }
        finally
        {
            _operationCancellation.Dispose();
            _operationCancellation = null;
            SetBusy(false);
        }
    }

    private void ShowPreview(ReaderImportPreview preview)
    {
        TitleTextBox.Text = preview.Title;
        _structure.Clear();
        _samples.Clear();
        foreach (var warning in preview.Warnings)
        {
            _structure.Add($"Warning: {warning.Message} ({warning.Count})");
        }
        foreach (var section in preview.Sections)
        {
            _structure.Add($"{new string(' ', Math.Max(0, section.Level - 1) * 2)}{section.Heading ?? "Untitled section"}");
        }
        foreach (var block in preview.SampleBlocks)
        {
            _samples.Add($"{block.Kind}: {block.Text}");
        }
        AllowDuplicateCheckBox.Visibility = preview.DuplicateDocumentId is null
            ? Visibility.Collapsed
            : Visibility.Visible;
        AllowDuplicateCheckBox.IsChecked = false;
        ImportButton.IsEnabled = preview.DuplicateDocumentId is null;
        var truncation = preview.PreviewTruncated ? " Preview is intentionally bounded." : string.Empty;
        StatusText.Text = $"{preview.TotalSections} section(s), {preview.TotalBlocks} block(s), " +
            $"{preview.TotalCharacters:N0} character(s), {preview.Warnings.Count} warning(s).{truncation}";
    }

    private async void ImportButton_Click(object sender, RoutedEventArgs e)
    {
        if (_preview is null || _operationCancellation is not null)
        {
            return;
        }
        _operationCancellation = new CancellationTokenSource();
        SetBusy(true, "Saving the imported document...");
        try
        {
            ImportedDocument = await _client.CommitImportToFolderAsync(
                _preview.PreviewId,
                AllowDuplicateCheckBox.IsChecked == true,
                _folderId,
                _operationCancellation.Token);
            _committed = true;
            DialogResult = true;
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "Import was cancelled before it was saved.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            StatusText.Text = $"Import: {exception.Message}";
        }
        finally
        {
            _operationCancellation?.Dispose();
            _operationCancellation = null;
            SetBusy(false);
        }
    }

    private async void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        if (_operationCancellation is not null)
        {
            _operationCancellation.Cancel();
            return;
        }
        await DiscardPreviewAsync();
        DialogResult = false;
    }

    private void AllowDuplicateCheckBox_Click(object sender, RoutedEventArgs e) =>
        ImportButton.IsEnabled = _operationCancellation is null && _preview is not null &&
            (_preview.DuplicateDocumentId is null || AllowDuplicateCheckBox.IsChecked == true);

    private async Task DiscardPreviewAsync()
    {
        if (_preview is null || _committed)
        {
            return;
        }
        var previewId = _preview.PreviewId;
        _preview = null;
        try
        {
            await _client.CancelImportAsync(previewId);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            _ = exception;
        }
    }

    private void ImportPreviewDialog_Closed(object? sender, EventArgs e)
    {
        _operationCancellation?.Cancel();
        _ = DiscardPreviewAsync();
    }

    private void SetBusy(bool busy, string? message = null)
    {
        Progress.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
        PreviewButton.IsEnabled = !busy;
        ImportButton.IsEnabled = !busy && _preview is not null &&
            (_preview.DuplicateDocumentId is null || AllowDuplicateCheckBox.IsChecked == true);
        if (message is not null)
        {
            StatusText.Text = message;
        }
    }

    private static string? EmptyToNull(string value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

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
}
