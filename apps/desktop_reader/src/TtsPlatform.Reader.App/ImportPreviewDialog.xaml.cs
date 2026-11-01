using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
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
    private ReaderImportPartsPreview? _parts;
    private bool _sourceDirty;
    private bool _updatingInputs;
    private bool _closed;
    private bool _committing;

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
        HeadingLevelComboBox.ItemsSource = Enumerable.Range(1, 9);
        HeadingLevelComboBox.SelectedItem = 1;
        StructureList.ItemsSource = _structure;
        SampleList.ItemsSource = _samples;
        ImportButton.Content = folderId is null ? "Import to All articles" : "Import to selected folder";
        Loaded += ImportPreviewDialog_Loaded;
        Closed += ImportPreviewDialog_Closed;
        Closing += ImportPreviewDialog_Closing;
    }

    public ReaderDocument? ImportedDocument { get; private set; }
    public IReadOnlyList<ReaderDocument> ImportedDocuments { get; private set; } = [];
    public bool NeedsLibraryRefresh { get; private set; }

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
        if (!TryReadPolicy(out var maximum, out var level)) return;
        var operation = new CancellationTokenSource();
        _operationCancellation = operation;
        SetBusy(true, "Reading and checking the document...");
        try
        {
            await DiscardPreviewAsync();
            if (_closed || operation.IsCancellationRequested) return;
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
                operation.Token);
            if (_closed || operation.IsCancellationRequested)
            {
                await DiscardPreviewAsync();
                return;
            }
            _sourceDirty = false;
            ShowPreview(_preview);
            await PreparePartsCoreAsync(_preview, maximum, level, operation.Token);
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
            if (ReferenceEquals(_operationCancellation, operation)) _operationCancellation = null;
            operation.Dispose();
            if (!_closed) SetBusy(false);
        }
    }

    private void ShowPreview(ReaderImportPreview preview)
    {
        _updatingInputs = true;
        TitleTextBox.Text = preview.Title;
        _updatingInputs = false;
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
        _parts = null;
        PartsGrid.ItemsSource = null;
        var truncation = preview.PreviewTruncated ? " Preview is intentionally bounded." : string.Empty;
        StatusText.Text = $"{preview.TotalSections} section(s), {preview.TotalBlocks} block(s), " +
            $"{preview.TotalCharacters:N0} character(s), {preview.Warnings.Count} warning(s).{truncation}";
    }

    private async Task PreparePartsCoreAsync(
        ReaderImportPreview preview, int maximum, int level, CancellationToken cancellationToken)
    {
        var planned = await _client.PreviewImportPartsAsync(
            preview.PreviewId, maximum, level, cancellationToken);
        if (_closed || cancellationToken.IsCancellationRequested || !ReferenceEquals(preview, _preview)) return;
        if (planned.PreviewId != preview.PreviewId || planned.MaxCharacters != maximum ||
            planned.HeadingLevel != level || string.IsNullOrWhiteSpace(planned.PlanKey) || planned.PlanKey.Length != 64 ||
            !planned.PlanKey.All(Uri.IsHexDigit) || planned.Parts is null || planned.Issues is null ||
            planned.Parts.Count > 100 || planned.CanCommit && planned.Parts.Count == 0 ||
            planned.Parts.Any(part => part is null || part.Codepoints is < 1 ||
                part.Codepoints > maximum || part.Utf16Units < part.Codepoints ||
                part.Utf16Units > maximum || part.Blocks is < 1 or > 20000 ||
                part.FirstChapter < 1 || part.LastChapter < part.FirstChapter ||
                part.LastChapter > planned.ChapterCount))
            throw new ReaderServiceUnavailableException("The service returned an invalid part review. Refresh the preview.");
        _parts = planned;
        PartsGrid.ItemsSource = planned.Parts;
        StatusText.Text = planned.CanCommit
            ? $"Review {planned.Parts.Count:N0} part(s) containing {planned.ChapterCount:N0} chapter(s). " +
                $"Each part is limited to {planned.MaxCharacters:N0} characters. Nothing has been saved."
            : string.Join(" ", planned.Issues);
    }

    private async void UpdatePartsButton_Click(object sender, RoutedEventArgs e) => await UpdatePartsAsync();

    private async Task UpdatePartsAsync()
    {
        if (_preview is null || _sourceDirty || _operationCancellation is not null ||
            !TryReadPolicy(out var maximum, out var level)) return;
        _parts = null;
        var operation = new CancellationTokenSource();
        _operationCancellation = operation;
        SetBusy(true, "Planning complete chapter parts...");
        try
        {
            await PreparePartsCoreAsync(_preview, maximum, level, operation.Token);
        }
        catch (OperationCanceledException) { StatusText.Text = "Part planning cancelled."; }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        { StatusText.Text = $"Part preview: {exception.Message}"; }
        finally
        {
            if (ReferenceEquals(_operationCancellation, operation)) _operationCancellation = null;
            operation.Dispose();
            if (!_closed) SetBusy(false);
        }
    }

    private bool TryReadPolicy(out int maximum, out int level)
    {
        level = HeadingLevelComboBox.SelectedItem is int selected ? selected : 1;
        if (!int.TryParse(MaxCharactersTextBox.Text, NumberStyles.None, CultureInfo.InvariantCulture,
                out maximum) || maximum is < 1 or > 1000000)
        {
            StatusText.Text = "Enter a maximum between 1 and 1,000,000 characters.";
            return false;
        }
        return true;
    }

    private bool CanImport => !_sourceDirty && _preview is not null && _parts is { CanCommit: true } &&
        (_preview.DuplicateDocumentId is null || AllowDuplicateCheckBox.IsChecked == true);

    private void SourceOptionChanged(object sender, RoutedEventArgs e)
    {
        if (_updatingInputs || _preview is null || _committing) return;
        _sourceDirty = true;
        InvalidateParts("Source options changed. Refresh the preview before importing.");
    }

    private void PartOptionChanged(object sender, RoutedEventArgs e)
    {
        if (_updatingInputs || _preview is null || _committing) return;
        InvalidateParts("Part options changed. Update parts to review the new plan.");
    }

    private void InvalidateParts(string message)
    {
        _parts = null;
        PartsGrid.ItemsSource = null;
        ImportButton.IsEnabled = false;
        UpdatePartsButton.IsEnabled = !_sourceDirty && _operationCancellation is null;
        StatusText.Text = message;
    }

    private async void ImportButton_Click(object sender, RoutedEventArgs e)
        => await CommitAsync();

    private async Task CommitAsync()
    {
        if (!CanImport || _preview is null || _parts is null || _operationCancellation is not null)
        {
            return;
        }
        _operationCancellation = new CancellationTokenSource();
        _committing = true;
        SetBusy(true, "Saving the reviewed parts...");
        try
        {
            var result = await _client.CommitImportPartsAsync(
                _preview.PreviewId,
                _parts.PlanKey,
                _parts.MaxCharacters,
                _parts.HeadingLevel,
                AllowDuplicateCheckBox.IsChecked == true,
                _folderId,
                _operationCancellation.Token);
            if (result.Documents is null || result.Documents.Count != _parts.Parts.Count ||
                result.Documents.Any(item => item is null) ||
                result.Documents.Select(item => item.Id).Distinct(StringComparer.Ordinal).Count() != result.Documents.Count ||
                result.Documents.Where((item, index) => item.Title != _parts.Parts[index].Title ||
                    item.TotalBlocks != _parts.Parts[index].Blocks || item.FolderId != _folderId ||
                    item.TotalCharacters + Math.Max(0, item.TotalBlocks - 1) * 2 != _parts.Parts[index].Codepoints).Any())
                throw new ReaderServiceUnavailableException("The import acknowledgement is incomplete. Refresh the library before retrying.");
            ImportedDocuments = result.Documents;
            ImportedDocument = result.Documents.FirstOrDefault();
            NeedsLibraryRefresh = true;
            _committed = true;
            _committing = false;
            DialogResult = true;
        }
        catch (OperationCanceledException)
        {
            NeedsLibraryRefresh = true;
            InvalidateParts("The save result is unknown. Refresh the library before retrying.");
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            NeedsLibraryRefresh = true;
            InvalidateParts($"Import: {exception.Message} Refresh the library before retrying an uncertain save.");
        }
        finally
        {
            _operationCancellation?.Dispose();
            _operationCancellation = null;
            _committing = false;
            SetBusy(false);
        }
    }

    internal async Task VerifyPartsForSmokeAsync(CancellationToken cancellationToken)
    {
        // Exercise the real Loaded handler and event-driven option invalidation.
        for (var attempt = 0; attempt < 100 && (_preview is null || _operationCancellation is not null); attempt++)
            await Task.Delay(100, cancellationToken);
        if (_parts is not { CanCommit: true } || _parts.MaxCharacters != 900000 || !ImportButton.IsEnabled)
            throw new InvalidOperationException("Initial desktop import part preview was not ready.");
        MaxCharactersTextBox.Text = "160";
        if (ImportButton.IsEnabled || _parts is not null)
            throw new InvalidOperationException("A changed import limit did not invalidate its review.");
        await UpdatePartsAsync();
        if (_parts is not { CanCommit: true } || _parts.Parts.Count != 3 || !ImportButton.IsEnabled)
            throw new InvalidOperationException("The desktop import preview did not expose three complete parts.");
        HeadingLevelComboBox.SelectedItem = 2;
        await UpdatePartsAsync();
        if (_parts is not { CanCommit: false } || ImportButton.IsEnabled)
            throw new InvalidOperationException("Unstructured oversized input was not blocked.");
        HeadingLevelComboBox.SelectedItem = 1;
        await UpdatePartsAsync();
        TitleTextBox.Text = "Reviewed desktop import";
        if (!_sourceDirty || ImportButton.IsEnabled || UpdatePartsButton.IsEnabled)
            throw new InvalidOperationException("A changed source title retained a stale import plan.");
        await PreviewAsync();
        if (!CanImport || _parts?.Parts.Count != 3)
            throw new InvalidOperationException("Refreshing the source did not rebuild its part review.");
    }

    internal Task CommitForSmokeAsync() => CommitAsync();
    internal Task RefreshForSmokeAsync() => PreviewAsync();

    private async void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        if (_operationCancellation is not null)
        {
            if (_committing) return;
            _operationCancellation.Cancel();
            return;
        }
        await DiscardPreviewAsync();
        DialogResult = false;
    }

    private void AllowDuplicateCheckBox_Click(object sender, RoutedEventArgs e) =>
        ImportButton.IsEnabled = _operationCancellation is null && CanImport;

    private async Task DiscardPreviewAsync()
    {
        if (_preview is null || _committed)
        {
            return;
        }
        var previewId = _preview.PreviewId;
        _preview = null;
        _parts = null;
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
        _closed = true;
        _operationCancellation?.Cancel();
        _ = DiscardPreviewAsync();
    }

    private void ImportPreviewDialog_Closing(object? sender, CancelEventArgs e)
    {
        if (!_committing) return;
        e.Cancel = true;
        StatusText.Text = "Waiting for the save result. Closing now could hide a committed import.";
    }

    private void SetBusy(bool busy, string? message = null)
    {
        Progress.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
        PreviewButton.IsEnabled = !busy;
        ImportButton.IsEnabled = !busy && CanImport;
        UpdatePartsButton.IsEnabled = !busy && _preview is not null && !_sourceDirty;
        TitleTextBox.IsEnabled = !busy;
        LanguageTextBox.IsEnabled = !busy;
        KeepSourceCheckBox.IsEnabled = !busy;
        MaxCharactersTextBox.IsEnabled = !busy;
        HeadingLevelComboBox.IsEnabled = !busy;
        AllowDuplicateCheckBox.IsEnabled = !busy;
        CancelButton.IsEnabled = !_committing;
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
