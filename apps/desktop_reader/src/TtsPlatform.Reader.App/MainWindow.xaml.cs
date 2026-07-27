using System.Collections.ObjectModel;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Microsoft.Win32;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class MainWindow : Window
{
    private readonly IDesktopSettingsStore _settingsStore;
    private readonly bool _smokeTest;
    private DesktopSettings _settings;
    private HttpClient? _httpClient;
    private IReaderServiceClient? _client;
    private LibraryPager? _library;
    private DocumentEditor? _editor;
    private ReaderPlaybackCoordinator? _playback;
    private readonly ObservableCollection<ReaderBlockDisplay> _readingBlocks = [];
    private OnboardingResult _onboarding = new(
        ConnectionState.NotChecked,
        "Connection has not been checked.",
        SuggestedAction.Retry);
    private bool _updatingEditor;

    public MainWindow(IDesktopSettingsStore settingsStore, DesktopSettings settings, bool smokeTest)
    {
        _settingsStore = settingsStore;
        _settings = settings;
        _smokeTest = smokeTest;
        InitializeComponent();
        ServiceUrlTextBox.Text = settings.ServiceBaseUrl;
        TokenPathTextBox.Text = settings.EffectiveTokenSource.Path;
        ReadingBlocksList.ItemsSource = _readingBlocks;
        ContentRendered += MainWindow_ContentRendered;
        Loaded += MainWindow_Loaded;
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        if (!_smokeTest)
        {
            await RefreshConnectionAsync();
        }
    }

    private void MainWindow_ContentRendered(object? sender, EventArgs e)
    {
        if (!_smokeTest)
        {
            return;
        }

        var marker = Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_SMOKE_MARKER");
        if (!string.IsNullOrWhiteSpace(marker))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
            File.WriteAllText(
                marker,
                JsonSerializer.Serialize(new
                {
                    rendered = true,
                    title = Title,
                    process_id = Environment.ProcessId,
                }));
        }

        System.Windows.Application.Current.Shutdown();
    }

    protected override void OnClosed(EventArgs e)
    {
        _playback?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _httpClient?.Dispose();
        base.OnClosed(e);
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) =>
        await RefreshConnectionAsync();

    private async Task RefreshConnectionAsync()
    {
        SetBusy(true, "Checking the local service…");
        try
        {
            RebuildClient();
            var coordinator = new OnboardingCoordinator(GetClient());
            _onboarding = await coordinator.CheckAsync();
            ShowOnboarding(_onboarding);
            if (_onboarding.State is ConnectionState.Ready or ConnectionState.BackendDegraded)
            {
                await RefreshLibraryAsync();
            }
        }
        catch (ReaderClientConfigurationException exception)
        {
            _onboarding = new OnboardingResult(ConnectionState.Error, exception.Message, SuggestedAction.Retry);
            ShowOnboarding(_onboarding);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void RebuildClient()
    {
        _playback?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _httpClient?.Dispose();
        _httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        var tokenProvider = new FileTokenProvider(_settings.EffectiveTokenSource.Path);
        _client = new ReaderServiceClient(
            _httpClient,
            _settings.ServiceBaseUrl,
            tokenProvider);
        _library = new LibraryPager(_client);
        _editor = new DocumentEditor(_client);
        _playback = new ReaderPlaybackCoordinator(
            _client,
            new ReaderStreamClient(_settings.ServiceBaseUrl, tokenProvider),
            new WasapiAudioOutput());
        _playback.StateChanged += Playback_StateChanged;
        _playback.HighlightChanged += Playback_HighlightChanged;
        DocumentsGrid.ItemsSource = _library.Documents;
        UpdatePlaybackControls();
    }

    private IReaderServiceClient GetClient()
    {
        if (_client is null)
        {
            RebuildClient();
        }

        return _client ?? throw new InvalidOperationException("Reader client initialization failed.");
    }

    private void ShowOnboarding(OnboardingResult result)
    {
        StatusText.Text = result.Message;
        StatusBorder.Background = result.IsReady
            ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(222, 245, 228))
            : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(255, 244, 214));
        ActionButton.Visibility = result.Action == SuggestedAction.None ? Visibility.Collapsed : Visibility.Visible;
        ActionButton.Content = result.Action switch
        {
            SuggestedAction.StartService => "Start service",
            SuggestedAction.ChooseTokenFile => "Choose token file",
            SuggestedAction.CheckVoiceModels => "Voice setup help",
            SuggestedAction.EnableReader => "Reader setup help",
            _ => "Retry",
        };
        FooterText.Text = result.State.ToString();
    }

    private async void ActionButton_Click(object sender, RoutedEventArgs e)
    {
        switch (_onboarding.Action)
        {
            case SuggestedAction.StartService:
                ScheduledServiceController.TryStart(out var message);
                StatusText.Text = message;
                break;
            case SuggestedAction.ChooseTokenFile:
                BrowseForToken();
                break;
            case SuggestedAction.CheckVoiceModels:
                MessageBox.Show(
                    "Run `tts setup-local`, verify the configured voice manifest, then restart the local service.",
                    "Voice setup",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                break;
            case SuggestedAction.EnableReader:
                MessageBox.Show(
                    "Set [reader] enabled = true in config/config.toml, then restart the local service.",
                    "Reader setup",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                break;
            default:
                await RefreshConnectionAsync();
                break;
        }
    }

    private void BrowseTokenButton_Click(object sender, RoutedEventArgs e) => BrowseForToken();

    private void BrowseForToken()
    {
        var dialog = new OpenFileDialog
        {
            Title = "Choose the local TTS service token file",
            Filter = "Token files (*.txt)|*.txt|All files (*.*)|*.*",
            CheckFileExists = true,
        };
        if (dialog.ShowDialog(this) == true)
        {
            TokenPathTextBox.Text = dialog.FileName;
        }
    }

    private async void SaveSettingsButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var normalizedUrl = ServiceBaseUrl.Parse(ServiceUrlTextBox.Text).AbsoluteUri;
            _settings = _settings with
            {
                ServiceBaseUrl = normalizedUrl,
                TokenSource = new TokenSourceSettings("file", TokenPathTextBox.Text.Trim()),
            };
            await _settingsStore.SaveAsync(_settings);
            FooterText.Text = $"Settings saved to {_settingsStore.SettingsPath}";
            await RefreshConnectionAsync();
        }
        catch (Exception exception) when (exception is ReaderClientConfigurationException or IOException or UnauthorizedAccessException)
        {
            StatusText.Text = $"Settings were not saved: {exception.Message}";
        }
    }

    private async void SearchButton_Click(object sender, RoutedEventArgs e) => await RefreshLibraryAsync();

    private async Task RefreshLibraryAsync()
    {
        if (_library is null)
        {
            return;
        }

        try
        {
            await _library.RefreshAsync(SearchTextBox.Text.Trim());
            LoadMoreButton.IsEnabled = _library.HasMore;
            FooterText.Text = $"{_library.Documents.Count} document(s) loaded";
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Library: {exception.Message}";
        }
    }

    private async void LoadMoreButton_Click(object sender, RoutedEventArgs e)
    {
        if (_library is null)
        {
            return;
        }

        try
        {
            await _library.LoadMoreAsync();
            LoadMoreButton.IsEnabled = _library.HasMore;
            FooterText.Text = $"{_library.Documents.Count} document(s) loaded";
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Library: {exception.Message}";
        }
    }

    private async void DocumentsGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_editor is null || DocumentsGrid.SelectedItem is not ReaderDocument document)
        {
            return;
        }

        if (_editor.HasUnsavedChanges)
        {
            var result = MessageBox.Show(
                "Discard the unsaved local edit and open another document?",
                "Unsaved edit",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);
            if (result != MessageBoxResult.Yes)
            {
                DocumentsGrid.SelectedItem = _editor.Document;
                return;
            }
        }

        try
        {
            if (_playback?.IsActive == true)
            {
                await _playback.StopAsync();
            }
            await _editor.LoadAsync(document);
            await LoadReadingWindowAsync(document, 0);
            _updatingEditor = true;
            DocumentTitleText.Text = document.Title;
            EditorTextBox.Text = _editor.WorkingText;
            EditorTextBox.IsReadOnly = !_editor.IsEditable;
            EditorHintText.Text = _editor.IsEditable
                ? "Editing the selected text block. Save uses the document row version; conflicts preserve this local text."
                : "Structured imports are read-only. A later milestone can duplicate them as editable text.";
            UpdateEditorButtons();
            UpdatePlaybackControls();
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Document: {exception.Message}";
        }
        finally
        {
            _updatingEditor = false;
        }
    }

    private void EditorTextBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_updatingEditor || _editor is null)
        {
            return;
        }

        _editor.SetWorkingText(EditorTextBox.Text);
        UpdateEditorButtons();
    }

    private async void SaveEditButton_Click(object sender, RoutedEventArgs e)
    {
        if (_editor is null)
        {
            return;
        }

        var result = await _editor.SaveAsync();
        FooterText.Text = result.Saved ? "Edit saved" : result.Message ?? "No changes to save";
        UpdateEditorButtons();
        if (result.Saved)
        {
            await RefreshLibraryAfterMutationAsync();
        }
    }

    private void RevertEditButton_Click(object sender, RoutedEventArgs e)
    {
        if (_editor is null)
        {
            return;
        }

        _editor.RevertLocalChanges();
        _updatingEditor = true;
        EditorTextBox.Text = _editor.WorkingText;
        _updatingEditor = false;
        FooterText.Text = "Local changes reverted";
        UpdateEditorButtons();
    }

    private async void UndoButton_Click(object sender, RoutedEventArgs e) => await ApplyHistoryAsync(true);

    private async void RedoButton_Click(object sender, RoutedEventArgs e) => await ApplyHistoryAsync(false);

    private async Task ApplyHistoryAsync(bool undo)
    {
        if (_editor is null)
        {
            return;
        }

        var result = undo ? await _editor.UndoAsync() : await _editor.RedoAsync();
        FooterText.Text = result.Saved ? (undo ? "Saved edit undone" : "Saved edit redone") : result.Message ?? "No history change";
        if (result.Saved)
        {
            _updatingEditor = true;
            EditorTextBox.Text = _editor.WorkingText;
            _updatingEditor = false;
            await RefreshLibraryAfterMutationAsync();
        }

        UpdateEditorButtons();
    }

    private async Task RefreshLibraryAfterMutationAsync()
    {
        if (_library is null || _editor?.Document is null)
        {
            return;
        }

        var selectedId = _editor.Document.Id;
        await _library.RefreshAsync(SearchTextBox.Text.Trim());
        DocumentsGrid.SelectedItem = _library.Documents.FirstOrDefault(item => item.Id == selectedId);
        LoadMoreButton.IsEnabled = _library.HasMore;
    }

    private void UpdateEditorButtons()
    {
        var editable = _editor?.IsEditable == true;
        var playbackActive = _playback?.IsActive == true;
        EditorTextBox.IsReadOnly = playbackActive || !editable;
        SaveEditButton.IsEnabled = editable && !playbackActive && _editor!.HasUnsavedChanges;
        RevertEditButton.IsEnabled = editable && !playbackActive && _editor!.HasUnsavedChanges;
        UndoButton.IsEnabled = editable && !playbackActive && !_editor!.HasUnsavedChanges;
        RedoButton.IsEnabled = editable && !playbackActive && !_editor!.HasUnsavedChanges;
    }

    private async void PlayPauseButton_Click(object sender, RoutedEventArgs e) =>
        await TogglePlaybackAsync();

    private async Task TogglePlaybackAsync()
    {
        if (_playback is null || _editor?.Document is null)
        {
            return;
        }
        if (_playback.IsActive)
        {
            await _playback.PauseAsync();
            return;
        }
        if (_editor.HasUnsavedChanges)
        {
            FooterText.Text = "Save or revert the local edit before playback.";
            return;
        }

        try
        {
            await _playback.PlayAsync(_editor.Document);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderStreamProtocolException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Playback: {exception.Message}";
        }
    }

    private async void StopButton_Click(object sender, RoutedEventArgs e)
    {
        if (_playback is not null)
        {
            await _playback.StopAsync();
        }
    }

    private async void PreviousSectionButton_Click(object sender, RoutedEventArgs e) =>
        await NavigateSectionAsync(next: false);

    private async void NextSectionButton_Click(object sender, RoutedEventArgs e) =>
        await NavigateSectionAsync(next: true);

    private async Task NavigateSectionAsync(bool next)
    {
        if (_playback is null || _client is null || _editor?.Document is not ReaderDocument document)
        {
            return;
        }
        if (_editor.HasUnsavedChanges)
        {
            FooterText.Text = "Save or revert the local edit before changing playback position.";
            return;
        }

        var currentOrdinal = _playback.LastFullyPlayedCursor?.BlockOrdinal ?? 0;
        var startOrdinal = next ? currentOrdinal : Math.Max(0, currentOrdinal - 63);
        var page = await _client.GetBlocksAsync(
            document.Id,
            afterOrdinal: startOrdinal - 1,
            limit: 64);
        var current = page.Blocks.FirstOrDefault(item => item.Ordinal == currentOrdinal)
            ?? page.Blocks.FirstOrDefault();
        if (current is null)
        {
            return;
        }

        ReaderBlock? target;
        if (next)
        {
            target = page.Blocks.FirstOrDefault(item =>
                item.Ordinal > currentOrdinal &&
                !string.Equals(item.SectionId, current.SectionId, StringComparison.Ordinal));
        }
        else
        {
            var prior = page.Blocks.LastOrDefault(item =>
                item.Ordinal < currentOrdinal &&
                !string.Equals(item.SectionId, current.SectionId, StringComparison.Ordinal));
            target = prior;
            if (prior is not null)
            {
                target = page.Blocks.First(item =>
                    item.Ordinal <= prior.Ordinal &&
                    string.Equals(item.SectionId, prior.SectionId, StringComparison.Ordinal));
            }
        }

        if (target is null)
        {
            FooterText.Text = next ? "No next section in the current window." : "No previous section in the current window.";
            return;
        }

        await _playback.SeekAsync(
            document,
            new ReaderCursor(
                document.Id,
                target.Id,
                target.Ordinal,
                0,
                document.ContentRevision));
    }

    private async Task LoadReadingWindowAsync(ReaderDocument document, int startOrdinal)
    {
        if (_client is null)
        {
            return;
        }

        var page = await _client.GetBlocksAsync(
            document.Id,
            afterOrdinal: Math.Max(-1, startOrdinal - 1),
            limit: 64);
        _readingBlocks.Clear();
        foreach (var block in page.Blocks)
        {
            _readingBlocks.Add(new ReaderBlockDisplay(block));
        }
    }

    private void Playback_StateChanged(object? sender, PlaybackStateChanged change)
    {
        Dispatcher.BeginInvoke(new Action(() =>
        {
            PlaybackStatusText.Text = change.Message is null
                ? change.State.ToString()
                : $"{change.State}: {change.Message}";
            FooterText.Text = change.Message ?? $"Playback {change.State.ToString().ToLowerInvariant()}";
            UpdatePlaybackControls();
            UpdateEditorButtons();
        }));
    }

    private void Playback_HighlightChanged(object? sender, PlaybackHighlight highlight)
    {
        Dispatcher.BeginInvoke(new Action(async () => await ShowHighlightAsync(highlight)));
    }

    private async Task ShowHighlightAsync(PlaybackHighlight highlight)
    {
        if (_editor?.Document is not ReaderDocument document ||
            !string.Equals(document.Id, highlight.DocumentId, StringComparison.Ordinal) ||
            highlight.SourceSpans.Count == 0)
        {
            return;
        }

        var firstSpan = highlight.SourceSpans[0];
        if (_readingBlocks.All(item => !string.Equals(item.Id, firstSpan.BlockId, StringComparison.Ordinal)))
        {
            await LoadReadingWindowAsync(document, firstSpan.BlockOrdinal);
        }

        foreach (var block in _readingBlocks)
        {
            block.HighlightStart = -1;
            block.HighlightLength = 0;
        }
        foreach (var group in highlight.SourceSpans.GroupBy(item => item.BlockId))
        {
            var block = _readingBlocks.FirstOrDefault(item =>
                string.Equals(item.Id, group.Key, StringComparison.Ordinal));
            if (block is null)
            {
                continue;
            }
            var start = group.Min(item => item.StartOffset);
            var end = group.Max(item => item.EndOffset);
            block.HighlightStart = start;
            block.HighlightLength = Math.Max(0, end - start);
            ReadingBlocksList.SelectedItem = block;
            ReadingBlocksList.ScrollIntoView(block);
        }
    }

    private void UpdatePlaybackControls()
    {
        var hasDocument = _editor?.Document is not null;
        var active = _playback?.IsActive == true;
        PlayPauseButton.Content = active ? "Pause" : "Play";
        PlayPauseButton.IsEnabled = hasDocument;
        StopButton.IsEnabled = hasDocument && _playback?.State is not ReaderPlaybackState.Stopped;
        PreviousSectionButton.IsEnabled = hasDocument;
        NextSectionButton.IsEnabled = hasDocument;
        ReadingBlocksList.Visibility = active ? Visibility.Visible : Visibility.Collapsed;
        EditorTextBox.Visibility = active ? Visibility.Collapsed : Visibility.Visible;
    }

    private async void MainWindow_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape && _playback?.State is not ReaderPlaybackState.Stopped)
        {
            e.Handled = true;
            await _playback!.StopAsync();
            return;
        }
        if (e.Key == Key.Space && Keyboard.FocusedElement is not TextBox)
        {
            e.Handled = true;
            await TogglePlaybackAsync();
        }
    }

    private void SetBusy(bool busy, string? text = null)
    {
        RefreshButton.IsEnabled = !busy;
        ActionButton.IsEnabled = !busy;
        if (text is not null)
        {
            StatusText.Text = text;
        }
    }
}
