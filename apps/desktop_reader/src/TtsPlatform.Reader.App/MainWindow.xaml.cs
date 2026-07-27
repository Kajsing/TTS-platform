using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
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
        _httpClient?.Dispose();
        _httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        _client = new ReaderServiceClient(
            _httpClient,
            _settings.ServiceBaseUrl,
            new FileTokenProvider(_settings.EffectiveTokenSource.Path));
        _library = new LibraryPager(_client);
        _editor = new DocumentEditor(_client);
        DocumentsGrid.ItemsSource = _library.Documents;
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
            await _editor.LoadAsync(document);
            _updatingEditor = true;
            DocumentTitleText.Text = document.Title;
            EditorTextBox.Text = _editor.WorkingText;
            EditorTextBox.IsReadOnly = !_editor.IsEditable;
            EditorHintText.Text = _editor.IsEditable
                ? "Editing the selected text block. Save uses the document row version; conflicts preserve this local text."
                : "Structured imports are read-only. A later milestone can duplicate them as editable text.";
            UpdateEditorButtons();
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
        SaveEditButton.IsEnabled = editable && _editor!.HasUnsavedChanges;
        RevertEditButton.IsEnabled = editable && _editor!.HasUnsavedChanges;
        UndoButton.IsEnabled = editable && !_editor!.HasUnsavedChanges;
        RedoButton.IsEnabled = editable && !_editor!.HasUnsavedChanges;
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
