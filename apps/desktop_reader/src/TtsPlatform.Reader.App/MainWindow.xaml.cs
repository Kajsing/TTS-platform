using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using Microsoft.Win32;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class MainWindow : Window
{
    private static readonly TimeSpan DesktopOpenPollInterval = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan DesktopOpenRateLimitBackoff = TimeSpan.FromMinutes(1);
    private static readonly TimeSpan DocumentRateLimitRetryDelay = TimeSpan.FromSeconds(61);
    private const int ContinuousEditorMaxCharacters = 1_000_000;
    private const int ContinuousEditorMaxBlocks = 20_000;

    private readonly IDesktopSettingsStore _settingsStore;
    private readonly bool _smokeTest;
    private DesktopSettings _settings;
    private HttpClient? _httpClient;
    private HttpClient? _synthesisHttpClient;
    private IReaderServiceClient? _client;
    private IReaderServiceClient? _synthesisClient;
    private LibraryPager? _library;
    private ReadingWindowPager? _readingWindow;
    private DocumentEditor? _editor;
    private ReaderPlaybackCoordinator? _playback;
    private JsonlPlaybackPerformanceSink? _playbackPerformance;
    private ClipboardDocumentCapture? _clipboardCapture;
    private readonly WindowsClipboardAdapter _clipboard = new();
    private readonly ForegroundApplicationReader _foregroundApplication = new();
    private readonly DefaultDesktopSecurityGuard _desktopSecurity = new();
    private ClipboardListener? _clipboardListener;
    private CopySelectionHelper? _copySelection;
    private GlobalHotkeyManager? _hotkeys;
    private ReaderTrayIcon? _trayIcon;
    private CompactControllerWindow? _compactController;
    private HwndSource? _windowSource;
    private WasapiAudioOutput? _ephemeralAudio;
    private CancellationTokenSource? _ephemeralCancellation;
    private Task? _ephemeralTask;
    private string? _ephemeralReplayText;
    private readonly ObservableCollection<ReaderBlockDisplay> _readingBlocks = [];
    private readonly SemaphoreSlim _autoAdvanceLock = new(1, 1);
    private readonly SemaphoreSlim _desktopOpenLock = new(1, 1);
    private readonly DispatcherTimer _desktopOpenTimer = new()
    {
        Interval = DesktopOpenPollInterval,
    };
    private OnboardingResult _onboarding = new(
        ConnectionState.NotChecked,
        "Connection has not been checked.",
        SuggestedAction.Retry);
    private bool _updatingEditor;
    private bool _copySelectionInProgress;
    private bool _clipboardPromptOpen;
    private bool _ephemeralPlaying;
    private bool _exitRequested;
    private bool _shutdownInProgress;
    private bool _closed;
    private int _documentLoadGeneration;
    private ContinuousDocumentText? _continuousDocument;
    private ReaderCursor? _textCursor;

    public MainWindow(IDesktopSettingsStore settingsStore, DesktopSettings settings, bool smokeTest)
    {
        _settingsStore = settingsStore;
        _settings = settings;
        _smokeTest = smokeTest;
        InitializeComponent();
        ServiceUrlTextBox.Text = settings.ServiceBaseUrl;
        TokenPathTextBox.Text = settings.EffectiveTokenSource.Path;
        ApplySettingsToControls(settings);
        ReadingBlocksList.ItemsSource = _readingBlocks;
        _desktopOpenTimer.Tick += DesktopOpenTimer_Tick;
        ContentRendered += MainWindow_ContentRendered;
        Loaded += MainWindow_Loaded;
        SourceInitialized += MainWindow_SourceInitialized;
        Closing += MainWindow_Closing;
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

    private void MainWindow_SourceInitialized(object? sender, EventArgs e)
    {
        if (_smokeTest)
        {
            return;
        }

        var handle = new WindowInteropHelper(this).Handle;
        _windowSource = HwndSource.FromHwnd(handle);
        _windowSource?.AddHook(WindowMessageHook);

        _clipboardListener = new ClipboardListener(_foregroundApplication);
        _clipboardListener.ClipboardChanged += ClipboardListener_ClipboardChanged;
        var clipboardRegistered = !_settings.ClipboardMonitoringEnabled ||
            _clipboardListener.Register(handle);
        _copySelection = new CopySelectionHelper(
            _clipboard,
            new WindowsCopyKeySender(),
            _foregroundApplication,
            _desktopSecurity);

        _hotkeys = new GlobalHotkeyManager();
        _hotkeys.Pressed += Hotkeys_Pressed;
        RegisterHotkeys(handle);

        _trayIcon = new ReaderTrayIcon();
        _trayIcon.Command += TrayIcon_Command;
        _trayIcon.SetClipboardMonitoring(_settings.ClipboardMonitoringEnabled);
        _trayIcon.SetStatus("Stopped");

        if (_settings.ClipboardMonitoringEnabled && !clipboardRegistered)
        {
            HotkeyStatusText.Text = string.Join(
                " ",
                HotkeyStatusText.Text,
                _clipboardListener.RegistrationError);
        }
        UpdateClipboardStatus();
        if (_settings.EffectiveCompactController.Enabled)
        {
            ShowCompactController();
        }
    }

    private async void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (!_exitRequested && _settings.MinimizeToTrayOnClose)
        {
            e.Cancel = true;
            Hide();
            if (_settings.EffectiveCompactController.Enabled)
            {
                ShowCompactController();
            }
            return;
        }
        if (!_exitRequested)
        {
            e.Cancel = true;
            await ExitApplicationAsync();
        }
    }

    private IntPtr WindowMessageHook(
        IntPtr window,
        int message,
        IntPtr wordParameter,
        IntPtr longParameter,
        ref bool handled)
    {
        _ = window;
        _ = longParameter;
        if (_hotkeys?.ProcessWindowMessage(message, wordParameter) == true)
        {
            handled = true;
        }
        if (_clipboardListener?.ProcessWindowMessage(message) == true)
        {
            handled = true;
        }
        return IntPtr.Zero;
    }

    private void RegisterHotkeys(IntPtr handle)
    {
        if (_hotkeys is null)
        {
            return;
        }
        var configured = _settings.EffectiveHotkeys;
        var bindings = new List<GlobalHotkeyBinding>
        {
            new(GlobalHotkeyCommand.ReadClipboard, configured.ReadClipboard),
            new(GlobalHotkeyCommand.PlayPause, configured.PlayPause),
            new(GlobalHotkeyCommand.Stop, configured.Stop),
        };
        if (_settings.CopySelectionAndReadEnabled)
        {
            bindings.Add(new(
                GlobalHotkeyCommand.CopySelectionAndRead,
                configured.CopySelectionAndRead));
        }
        var results = _hotkeys.Register(handle, bindings);
        var failures = results.Where(item => !item.Registered).ToArray();
        HotkeyStatusText.Text = failures.Length == 0
            ? $"{results.Count} global hotkey(s) registered."
            : $"{failures.Length} hotkey(s) unavailable: {string.Join(", ", failures.Select(item => item.Gesture))}. Other controls remain available.";
    }

    private async void Hotkeys_Pressed(object? sender, GlobalHotkeyCommand command)
    {
        switch (command)
        {
            case GlobalHotkeyCommand.ReadClipboard:
                await ReadClipboardAsync();
                break;
            case GlobalHotkeyCommand.CopySelectionAndRead:
                await CopySelectionAndReadAsync();
                break;
            case GlobalHotkeyCommand.PlayPause:
                await ToggleUnifiedPlaybackAsync();
                break;
            case GlobalHotkeyCommand.Stop:
                await StopUnifiedPlaybackAsync();
                break;
        }
    }

    private async void TrayIcon_Command(object? sender, ReaderTrayCommand command)
    {
        switch (command)
        {
            case ReaderTrayCommand.OpenReader:
                OpenMainWindow();
                break;
            case ReaderTrayCommand.OpenCompactController:
                ShowCompactController();
                break;
            case ReaderTrayCommand.PlayPause:
                await ToggleUnifiedPlaybackAsync();
                break;
            case ReaderTrayCommand.Stop:
                await StopUnifiedPlaybackAsync();
                break;
            case ReaderTrayCommand.ReadClipboard:
                await ReadClipboardAsync();
                break;
            case ReaderTrayCommand.ToggleClipboardMonitoring:
                await SetClipboardMonitoringAsync(!_settings.ClipboardMonitoringEnabled);
                break;
            case ReaderTrayCommand.ServiceStatus:
                OpenMainWindow();
                await RefreshConnectionAsync();
                break;
            case ReaderTrayCommand.Exit:
                await ExitApplicationAsync();
                break;
        }
    }

    private void OpenMainWindow()
    {
        Show();
        WindowState = WindowState.Normal;
        Activate();
    }

    private void ShowCompactController()
    {
        if (_compactController is null)
        {
            var compactSettings = _settings.EffectiveCompactController;
            _compactController = new CompactControllerWindow
            {
                Owner = this,
                Topmost = compactSettings.AlwaysOnTop,
            };
            if (compactSettings.Left is double left && compactSettings.Top is double top)
            {
                _compactController.WindowStartupLocation = WindowStartupLocation.Manual;
                _compactController.Left = left;
                _compactController.Top = top;
            }
            _compactController.PlayPauseRequested += async (_, _) =>
                await ToggleUnifiedPlaybackAsync();
            _compactController.StopRequested += async (_, _) =>
                await StopUnifiedPlaybackAsync();
            _compactController.OpenReaderRequested += (_, _) => OpenMainWindow();
        }
        UpdateCompactController();
        _compactController.Show();
        _compactController.Activate();
    }

    private async Task ExitApplicationAsync()
    {
        if (_shutdownInProgress)
        {
            return;
        }
        _shutdownInProgress = true;
        _exitRequested = true;
        try
        {
            await StopUnifiedPlaybackAsync();
            if (_compactController is not null)
            {
                var compact = _settings.EffectiveCompactController;
                _settings = _settings with
                {
                    CompactController = compact with
                    {
                        Left = _compactController.Left,
                        Top = _compactController.Top,
                    },
                };
                try
                {
                    await _settingsStore.SaveAsync(_settings);
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    FooterText.Text = $"Compact position was not saved: {exception.Message}";
                }
            }
        }
        finally
        {
            System.Windows.Application.Current.Shutdown();
        }
    }

    protected override void OnClosed(EventArgs e)
    {
        if (_closed)
        {
            return;
        }
        _closed = true;
        _windowSource?.RemoveHook(WindowMessageHook);
        _hotkeys?.Dispose();
        _clipboardListener?.Dispose();
        _trayIcon?.Dispose();
        StopEphemeralAsync(clearReplay: true).GetAwaiter().GetResult();
        _ephemeralAudio?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        if (_compactController is not null)
        {
            _compactController.AllowClose = true;
            _compactController.Close();
        }
        _playback?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _playbackPerformance?.Dispose();
        _desktopOpenTimer.Stop();
        _autoAdvanceLock.Dispose();
        _httpClient?.Dispose();
        _synthesisHttpClient?.Dispose();
        base.OnClosed(e);
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) =>
        await RefreshConnectionAsync();

    private async void StartServiceButton_Click(object sender, RoutedEventArgs e) =>
        await StartLocalServiceAsync();

    private async void StopServiceButton_Click(object sender, RoutedEventArgs e) =>
        await StopLocalServiceAsync();

    private async Task StartLocalServiceAsync()
    {
        SetBusy(true, "Starting the local serviceâ€¦");
        try
        {
            if (!ScheduledServiceController.TryStart(out var message))
            {
                StatusText.Text = message;
                FooterText.Text = "Service start failed";
                return;
            }

            StatusText.Text = message;
            ServiceStatusText.Text = "Service: starting";
            ServiceStatusDot.Fill = new SolidColorBrush(Color.FromRgb(224, 165, 43));
            await WaitForServiceAvailabilityAsync(shouldBeAvailable: true);
            await RefreshConnectionAsync();
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task StopLocalServiceAsync()
    {
        var confirmation = MessageBox.Show(
            "Stop the local TTS service? Current Reader and browser playback will be interrupted.",
            "Stop local service",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);
        if (confirmation != MessageBoxResult.Yes)
        {
            return;
        }

        SetBusy(true, "Stopping the local serviceâ€¦");
        try
        {
            await StopUnifiedPlaybackAsync();
            if (!ScheduledServiceController.TryStop(out var message))
            {
                StatusText.Text = message;
                FooterText.Text = "Service stop was refused safely";
                return;
            }

            StatusText.Text = message;
            ServiceStatusText.Text = "Service: stopping";
            ServiceStatusDot.Fill = new SolidColorBrush(Color.FromRgb(224, 165, 43));
            await WaitForServiceAvailabilityAsync(shouldBeAvailable: false);
            await RefreshConnectionAsync();
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task WaitForServiceAvailabilityAsync(bool shouldBeAvailable)
    {
        for (var attempt = 0; attempt < 30; attempt++)
        {
            var available = false;
            try
            {
                _ = await GetClient().GetHealthAsync();
                available = true;
            }
            catch (Exception exception) when (
                exception is ReaderServiceUnavailableException or
                    ReaderTokenUnavailableException or
                    ReaderApiException)
            {
                // A transition is expected while the local process starts or stops.
            }

            if (available == shouldBeAvailable)
            {
                return;
            }
            await Task.Delay(250);
        }
    }

    private async Task RefreshConnectionAsync(bool rebuildClient = false)
    {
        SetBusy(true, "Checking the local service…");
        try
        {
            var clientWasRebuilt = rebuildClient || _client is null;
            if (clientWasRebuilt)
            {
                RebuildClient();
            }
            var coordinator = new OnboardingCoordinator(GetClient());
            _onboarding = await coordinator.CheckAsync();
            var preserveConnectedData =
                _onboarding.State == ConnectionState.RateLimited && !clientWasRebuilt;
            if (preserveConnectedData)
            {
                _onboarding = _onboarding with
                {
                    Message = "The local service is busy. Current library and voice selection are kept; retry in about a minute.",
                };
            }
            else
            {
                UpdateVoiceOptions(_onboarding.Voices);
            }
            ShowOnboarding(_onboarding);
            if (_onboarding.State is ConnectionState.Ready or ConnectionState.BackendDegraded)
            {
                await RefreshLibraryAsync();
                _desktopOpenTimer.Start();
                await CheckDesktopOpenRequestAsync();
            }
            else
            {
                _desktopOpenTimer.Stop();
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

    private async void DesktopOpenTimer_Tick(object? sender, EventArgs e) =>
        await CheckDesktopOpenRequestAsync();

    private async Task CheckDesktopOpenRequestAsync()
    {
        if (_closed || !_desktopOpenLock.Wait(0))
        {
            return;
        }
        try
        {
            var openRequest = await GetClient().GetNextDesktopOpenRequestAsync();
            _desktopOpenTimer.Interval = DesktopOpenPollInterval;
            if (openRequest is null)
            {
                return;
            }
            if (_editor?.HasUnsavedChanges == true)
            {
                FooterText.Text = "A browser document is waiting. Save or discard the current edit to open it.";
                return;
            }
            if (_playback?.IsActive == true)
            {
                FooterText.Text = "A browser document is waiting and will open after playback stops.";
                return;
            }

            var document = await GetClient().GetDocumentAsync(openRequest.DocumentId);
            await RefreshLibraryAsync();
            await LoadDocumentAsync(document);
            if (_editor?.Document?.Id != document.Id)
            {
                return;
            }
            await GetClient().AcknowledgeDesktopOpenRequestAsync(openRequest.Id);
            OpenMainWindow();
            FooterText.Text = "Opened a document saved from the browser.";
        }
        catch (ReaderApiException exception) when (exception.ErrorType == "rate_limited")
        {
            _desktopOpenTimer.Interval = DesktopOpenRateLimitBackoff;
            FooterText.Text = "Browser handoff is waiting for the local service rate limit.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Browser handoff: {exception.Message}";
        }
        finally
        {
            _desktopOpenLock.Release();
        }
    }

    private void RebuildClient()
    {
        StopEphemeralAsync(clearReplay: true).GetAwaiter().GetResult();
        _ephemeralAudio?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _playback?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _playbackPerformance?.Dispose();
        _httpClient?.Dispose();
        _synthesisHttpClient?.Dispose();
        _httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        _synthesisHttpClient = new HttpClient { Timeout = TimeSpan.FromMinutes(2) };
        var tokenProvider = new FileTokenProvider(_settings.EffectiveTokenSource.Path);
        _client = new ReaderServiceClient(
            _httpClient,
            _settings.ServiceBaseUrl,
            tokenProvider);
        _synthesisClient = new ReaderServiceClient(
            _synthesisHttpClient,
            _settings.ServiceBaseUrl,
            tokenProvider);
        _library = new LibraryPager(_client);
        _readingWindow = new ReadingWindowPager(_client);
        _editor = new DocumentEditor(_client);
        _clipboardCapture = new ClipboardDocumentCapture(_client);
        _ephemeralAudio = new WasapiAudioOutput();
        _playbackPerformance = new JsonlPlaybackPerformanceSink();
        _playback = new ReaderPlaybackCoordinator(
            _client,
            new ReaderStreamClient(_settings.ServiceBaseUrl, tokenProvider),
            new WasapiAudioOutput(),
            _playbackPerformance);
        _playback.StateChanged += Playback_StateChanged;
        _playback.HighlightChanged += Playback_HighlightChanged;
        _playback.RuleWarning += Playback_RuleWarning;
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
        var serviceUnavailable = result.State == ConnectionState.ServiceUnavailable;
        ServiceStatusText.Text = serviceUnavailable
            ? "Service: stopped"
            : result.State is ConnectionState.NotChecked or ConnectionState.Checking
                ? "Service: checking"
                : "Service: running";
        ServiceStatusDot.Fill = serviceUnavailable
            ? new SolidColorBrush(Color.FromRgb(213, 83, 83))
            : result.State is ConnectionState.NotChecked or ConnectionState.Checking
                ? new SolidColorBrush(Color.FromRgb(224, 165, 43))
                : new SolidColorBrush(Color.FromRgb(52, 199, 138));
        StartServiceButton.IsEnabled = serviceUnavailable;
        StopServiceButton.IsEnabled = !serviceUnavailable || ScheduledServiceController.OwnsRunningService;
        FooterText.Text = result.State.ToString();
    }

    private async void ActionButton_Click(object sender, RoutedEventArgs e)
    {
        switch (_onboarding.Action)
        {
            case SuggestedAction.StartService:
                await StartLocalServiceAsync();
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
            var tokenPath = TokenPathTextBox.Text.Trim();
            var reconnectRequired = DesktopConnectionPolicy.RequiresReconnect(
                _settings,
                normalizedUrl,
                tokenPath);
            _settings = _settings with
            {
                ServiceBaseUrl = normalizedUrl,
                TokenSource = new TokenSourceSettings("file", tokenPath),
                PreferredVoiceId = SelectedVoiceId() ?? _settings.PreferredVoiceId,
                ClipboardMonitoringEnabled = ClipboardMonitoringCheckBox.IsChecked == true,
                CopySelectionAndReadEnabled = CopySelectionCheckBox.IsChecked == true,
                PrivacyMode = PrivacyModeCheckBox.IsChecked == true,
                MinimizeToTrayOnClose = MinimizeToTrayCheckBox.IsChecked == true,
                ClipboardBlockedApplications = ParseBlockedApplications(
                    BlockedApplicationsTextBox.Text),
                Hotkeys = new DesktopHotkeys(
                    ReadClipboardHotkeyTextBox.Text.Trim(),
                    CopySelectionHotkeyTextBox.Text.Trim(),
                    PlayPauseHotkeyTextBox.Text.Trim(),
                    StopHotkeyTextBox.Text.Trim()),
                CompactController = _settings.EffectiveCompactController with
                {
                    Enabled = CompactEnabledCheckBox.IsChecked == true,
                },
            };
            await _settingsStore.SaveAsync(_settings);
            FooterText.Text = $"Settings saved to {_settingsStore.SettingsPath}";
            if (reconnectRequired || _client is null)
            {
                await RefreshConnectionAsync(rebuildClient: true);
            }
            if (_windowSource is not null)
            {
                RegisterHotkeys(new WindowInteropHelper(this).Handle);
            }
            if (_clipboardListener is not null)
            {
                if (_settings.ClipboardMonitoringEnabled)
                {
                    _ = _clipboardListener.Register(new WindowInteropHelper(this).Handle);
                }
                else
                {
                    _clipboardListener.Unregister();
                }
            }
            _trayIcon?.SetClipboardMonitoring(_settings.ClipboardMonitoringEnabled);
            UpdateClipboardStatus();
        }
        catch (Exception exception) when (exception is ReaderClientConfigurationException or IOException or UnauthorizedAccessException)
        {
            StatusText.Text = $"Settings were not saved: {exception.Message}";
        }
    }

    private void ApplySettingsToControls(DesktopSettings settings)
    {
        ClipboardMonitoringCheckBox.IsChecked = settings.ClipboardMonitoringEnabled;
        CopySelectionCheckBox.IsChecked = settings.CopySelectionAndReadEnabled;
        PrivacyModeCheckBox.IsChecked = settings.PrivacyMode;
        MinimizeToTrayCheckBox.IsChecked = settings.MinimizeToTrayOnClose;
        CompactEnabledCheckBox.IsChecked = settings.EffectiveCompactController.Enabled;
        BlockedApplicationsTextBox.Text = string.Join(", ", settings.EffectiveClipboardBlockedApplications);
        ReadClipboardHotkeyTextBox.Text = settings.EffectiveHotkeys.ReadClipboard;
        CopySelectionHotkeyTextBox.Text = settings.EffectiveHotkeys.CopySelectionAndRead;
        PlayPauseHotkeyTextBox.Text = settings.EffectiveHotkeys.PlayPause;
        StopHotkeyTextBox.Text = settings.EffectiveHotkeys.Stop;
        UpdateClipboardStatus();
    }

    private void UpdateVoiceOptions(VoicePage? page)
    {
        var requestedVoiceId = SelectedVoiceId() ?? _settings.PreferredVoiceId;
        VoiceComboBox.Items.Clear();
        if (page is null || page.Voices.Count == 0)
        {
            VoiceComboBox.IsEnabled = false;
            VoiceDetailsText.Text = "Connect to load installed voices.";
            return;
        }

        foreach (var voice in page.Voices)
        {
            VoiceComboBox.Items.Add(new VoiceChoice(
                voice,
                string.Equals(voice.Id, page.DefaultVoice, StringComparison.Ordinal)));
        }
        var selected = VoiceSelectionPolicy.Resolve(page, requestedVoiceId);
        VoiceComboBox.SelectedItem = VoiceComboBox.Items
            .OfType<VoiceChoice>()
            .First(item => string.Equals(item.Id, selected!.Id, StringComparison.Ordinal));
        VoiceComboBox.IsEnabled = true;
    }

    private void VoiceComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        VoiceDetailsText.Text = VoiceComboBox.SelectedItem is VoiceChoice selected
            ? selected.Details
            : "Connect to load installed voices.";
    }

    private string? SelectedVoiceId() =>
        (VoiceComboBox.SelectedItem as VoiceChoice)?.Id;

    private static IReadOnlyList<string> ParseBlockedApplications(string value) =>
        value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private async void ClipboardMonitoringCheckBox_Click(object sender, RoutedEventArgs e) =>
        await SetClipboardMonitoringAsync(ClipboardMonitoringCheckBox.IsChecked == true);

    private async Task SetClipboardMonitoringAsync(bool enabled)
    {
        _settings = _settings with { ClipboardMonitoringEnabled = enabled };
        ClipboardMonitoringCheckBox.IsChecked = enabled;
        if (_clipboardListener is not null)
        {
            if (enabled)
            {
                _ = _clipboardListener.Register(new WindowInteropHelper(this).Handle);
            }
            else
            {
                _clipboardListener.Unregister();
            }
        }
        _trayIcon?.SetClipboardMonitoring(enabled);
        UpdateClipboardStatus();
        try
        {
            await _settingsStore.SaveAsync(_settings);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            FooterText.Text = $"Clipboard monitoring preference was not saved: {exception.Message}";
        }
    }

    private void UpdateClipboardStatus()
    {
        var state = !_settings.ClipboardMonitoringEnabled
            ? "Off"
            : _clipboardListener?.IsRegistered == false
                ? "Unavailable"
                : "On";
        var privacy = _settings.PrivacyMode ? " · Privacy" : string.Empty;
        ClipboardStatusText.Text = $"Clipboard prompt: {state}{privacy}";
    }

    private async void ReadClipboardButton_Click(object sender, RoutedEventArgs e) =>
        await ReadClipboardAsync();

    private void CompactButton_Click(object sender, RoutedEventArgs e) =>
        ShowCompactController();

    private async void ClipboardListener_ClipboardChanged(
        object? sender,
        ClipboardChangedEventArgs change)
    {
        if (!_settings.ClipboardMonitoringEnabled ||
            _copySelectionInProgress ||
            _clipboardPromptOpen ||
            IsBlockedApplication(change.SourceExecutable))
        {
            return;
        }

        var clipboard = _clipboard.ReadText();
        if (!clipboard.Succeeded || clipboard.Text is not string text)
        {
            FooterText.Text = clipboard.Message;
            return;
        }

        _clipboardPromptOpen = true;
        try
        {
            var dialog = new ClipboardCaptureDialog(
                text,
                change.SourceExecutable,
                _settings.PrivacyMode)
            {
                Owner = IsActive ? this : null,
            };
            _ = dialog.ShowDialog();
            await HandleClipboardActionAsync(
                dialog.SelectedAction,
                text,
                change.SourceExecutable);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Clipboard capture: {exception.Message}";
        }
        finally
        {
            _clipboardPromptOpen = false;
        }
    }

    private async Task HandleClipboardActionAsync(
        ClipboardCaptureAction action,
        string text,
        string? sourceExecutable)
    {
        switch (action)
        {
            case ClipboardCaptureAction.ReadNow:
                await StartEphemeralPlaybackAsync(text);
                return;
            case ClipboardCaptureAction.AppendToOpenDocument:
                if (_clipboardCapture is null)
                {
                    FooterText.Text = "Connect to the local Reader before appending.";
                    return;
                }
                await ApplyClipboardCaptureResultAsync(
                    await _clipboardCapture.AppendAsync(text, _editor?.Document));
                return;
            case ClipboardCaptureAction.CreateNewDocument:
            case ClipboardCaptureAction.SaveToInbox:
                if (_clipboardCapture is null)
                {
                    FooterText.Text = "Connect to the local Reader before saving.";
                    return;
                }
                var openDocument = action == ClipboardCaptureAction.CreateNewDocument;
                var result = await _clipboardCapture.CreateAsync(text, openDocument);
                if (result.DuplicateDocumentId is not null)
                {
                    result = await ResolveClipboardDuplicateAsync(
                        result.DuplicateDocumentId,
                        text,
                        openDocument);
                }
                await ApplyClipboardCaptureResultAsync(result);
                return;
            case ClipboardCaptureAction.AlwaysIgnoreApplication:
                if (!string.IsNullOrWhiteSpace(sourceExecutable))
                {
                    var blocked = _settings.EffectiveClipboardBlockedApplications
                        .Append(sourceExecutable)
                        .Distinct(StringComparer.OrdinalIgnoreCase)
                        .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
                        .ToArray();
                    _settings = _settings with { ClipboardBlockedApplications = blocked };
                    BlockedApplicationsTextBox.Text = string.Join(", ", blocked);
                    try
                    {
                        await _settingsStore.SaveAsync(_settings);
                        FooterText.Text = $"Clipboard prompts disabled for {sourceExecutable}.";
                    }
                    catch (Exception exception) when (
                        exception is IOException or UnauthorizedAccessException)
                    {
                        FooterText.Text = $"The application block was not saved: {exception.Message}";
                    }
                }
                return;
            case ClipboardCaptureAction.Ignore:
            default:
                FooterText.Text = "Clipboard text ignored.";
                return;
        }
    }

    private async Task<ClipboardCaptureResult> ResolveClipboardDuplicateAsync(
        string documentId,
        string text,
        bool openDocument)
    {
        var dialog = new ClipboardDuplicateDialog
        {
            Owner = IsVisible ? this : null,
        };
        _ = dialog.ShowDialog();
        return dialog.SelectedChoice switch
        {
            ClipboardDuplicateChoice.OpenExisting =>
                await _clipboardCapture!.OpenExistingAsync(documentId),
            ClipboardDuplicateChoice.CreateAnyway =>
                await _clipboardCapture!.CreateAsync(
                    text,
                    openDocument,
                    allowDuplicate: true),
            _ => new ClipboardCaptureResult(false, "Clipboard text was not saved again."),
        };
    }

    private async Task ApplyClipboardCaptureResultAsync(ClipboardCaptureResult result)
    {
        FooterText.Text = result.Message;
        if (!result.Succeeded || result.Document is null || _library is null)
        {
            return;
        }

        try
        {
            await _library.RefreshAsync(SearchTextBox.Text.Trim(), SelectedLibraryState());
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"{result.Message} Library refresh is delayed: {exception.Message}";
            if (result.OpenDocument)
            {
                await LoadDocumentAsync(result.Document);
            }
            return;
        }
        LoadMoreButton.IsEnabled = _library.HasMore;
        if (result.OpenDocument)
        {
            var current = _library.Documents.FirstOrDefault(item => item.Id == result.Document.Id);
            if (current is null)
            {
                await LoadDocumentAsync(result.Document);
                FooterText.Text = result.Message;
                return;
            }
            DocumentsGrid.SelectedItem = current;
            if (_editor is not null &&
                (DocumentsGrid.SelectedItem as ReaderDocument)?.Id == _editor.Document?.Id)
            {
                await LoadDocumentAsync(current);
            }
        }
        FooterText.Text = result.Message;
    }

    private bool IsBlockedApplication(string? executable)
    {
        if (string.IsNullOrWhiteSpace(executable))
        {
            return false;
        }
        var baseName = Path.GetFileNameWithoutExtension(executable);
        return _settings.EffectiveClipboardBlockedApplications.Any(item =>
            string.Equals(item, executable, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(
                Path.GetFileNameWithoutExtension(item),
                baseName,
                StringComparison.OrdinalIgnoreCase));
    }

    private async Task ReadClipboardAsync()
    {
        var result = _clipboard.ReadText();
        if (!result.Succeeded || result.Text is not string text)
        {
            FooterText.Text = result.Message;
            return;
        }
        await StartEphemeralPlaybackAsync(text);
    }

    private async Task CopySelectionAndReadAsync()
    {
        if (!_settings.CopySelectionAndReadEnabled)
        {
            FooterText.Text = "Enable Copy Selection and Read in settings before using its hotkey.";
            return;
        }
        if (_copySelection is null || _clipboardListener is null)
        {
            FooterText.Text = "Windows selection capture is not initialized.";
            return;
        }

        _copySelectionInProgress = true;
        try
        {
            var result = await _copySelection.CaptureAsync(
                _settings.EffectiveClipboardBlockedApplications);
            _clipboardListener.SuppressSequence(_clipboard.SequenceNumber);
            if (!result.Succeeded || result.Text is not string text)
            {
                FooterText.Text = result.Message;
                return;
            }
            await StartEphemeralPlaybackAsync(text);
        }
        finally
        {
            _copySelectionInProgress = false;
        }
    }

    private async Task StartEphemeralPlaybackAsync(string text)
    {
        if (_synthesisClient is null || _ephemeralAudio is null)
        {
            FooterText.Text = "Connect to the local service before reading clipboard text.";
            return;
        }
        if (_playback?.IsActive == true)
        {
            await _playback.StopAsync();
        }
        await StopEphemeralAsync(clearReplay: false);
        _ephemeralReplayText = text;
        _ephemeralCancellation = new CancellationTokenSource();
        _ephemeralPlaying = true;
        SetEphemeralState("Reading clipboard text", playing: true);
        if (_settings.EffectiveCompactController.Enabled)
        {
            ShowCompactController();
        }
        _ephemeralTask = RunEphemeralPlaybackAsync(
            text,
            _ephemeralCancellation,
            _synthesisClient,
            _ephemeralAudio,
            SelectedVoiceId());
    }

    private async Task RunEphemeralPlaybackAsync(
        string text,
        CancellationTokenSource cancellation,
        IReaderServiceClient client,
        WasapiAudioOutput audio,
        string? voiceId)
    {
        var completed = false;
        try
        {
            foreach (var chunk in EphemeralTextChunker.Chunk(text))
            {
                var wave = await client.SynthesizeAsync(
                    new EphemeralSynthesisRequest(chunk, Voice: voiceId),
                    cancellation.Token);
                var decoded = WavePcmDecoder.Decode(wave);
                var frameBytes = Math.Max(
                    2,
                    decoded.Format.SampleRateHz * decoded.Format.Channels * 2 * 40 / 1_000);
                frameBytes -= frameBytes % 2;
                for (var offset = 0; offset < decoded.Bytes.Length; offset += frameBytes)
                {
                    var length = Math.Min(frameBytes, decoded.Bytes.Length - offset);
                    await audio.PlayAsync(
                        decoded.Bytes.AsMemory(offset, length),
                        decoded.Format,
                        cancellation.Token);
                }
                await audio.DrainAsync(cancellation.Token);
            }
            completed = true;
            SetEphemeralState("Clipboard reading completed", playing: false);
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        {
            SetEphemeralState("Clipboard reading paused", playing: false);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException or
                InvalidDataException or
                ArgumentOutOfRangeException or
                InvalidOperationException or
                NotSupportedException)
        {
            SetEphemeralState($"Clipboard playback failed: {exception.Message}", playing: false);
        }
        finally
        {
            if (ReferenceEquals(_ephemeralCancellation, cancellation))
            {
                _ephemeralPlaying = false;
                if (completed)
                {
                    _ephemeralReplayText = null;
                }
            }
        }
    }

    private async Task StopEphemeralAsync(bool clearReplay)
    {
        var cancellation = _ephemeralCancellation;
        var task = _ephemeralTask;
        cancellation?.Cancel();
        if (_ephemeralAudio is not null)
        {
            await _ephemeralAudio.StopAsync();
        }
        if (task is not null)
        {
            try
            {
                await task;
            }
            catch (OperationCanceledException)
            {
                // The requested pause/stop owns the resulting state.
            }
        }
        if (ReferenceEquals(_ephemeralCancellation, cancellation))
        {
            _ephemeralCancellation = null;
            _ephemeralTask = null;
            cancellation?.Dispose();
        }
        _ephemeralPlaying = false;
        if (clearReplay)
        {
            _ephemeralReplayText = null;
        }
    }

    private void SetEphemeralState(string state, bool playing)
    {
        Dispatcher.BeginInvoke(new Action(() =>
        {
            PlaybackStatusText.Text = state;
            FooterText.Text = state;
            _trayIcon?.SetStatus(playing ? "Reading Clipboard" : "Paused");
            UpdatePlaybackControls();
            UpdateCompactController();
        }));
    }

    private async Task ToggleUnifiedPlaybackAsync()
    {
        if (_ephemeralPlaying)
        {
            await StopEphemeralAsync(clearReplay: false);
            SetEphemeralState("Clipboard reading paused", playing: false);
            return;
        }
        if (_playback?.IsActive == true)
        {
            await _playback.PauseAsync();
            return;
        }
        if (_ephemeralReplayText is string replay)
        {
            await StartEphemeralPlaybackAsync(replay);
            return;
        }
        await TogglePlaybackAsync();
    }

    private async Task StopUnifiedPlaybackAsync()
    {
        await StopEphemeralAsync(clearReplay: true);
        if (_playback is not null)
        {
            await _playback.StopAsync();
        }
        SetEphemeralState("Stopped", playing: false);
    }

    private async void SearchButton_Click(object sender, RoutedEventArgs e) => await RefreshLibraryAsync();

    private async void LibraryStateComboBox_SelectionChanged(
        object sender,
        SelectionChangedEventArgs e) => await RefreshLibraryAsync();

    private string? SelectedLibraryState()
    {
        var value = (LibraryStateComboBox.SelectedItem as ComboBoxItem)?.Tag as string;
        return string.IsNullOrWhiteSpace(value) ? null : value;
    }

    private async void ImportButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "Import a document",
            Filter = "Reader documents (*.txt;*.md;*.markdown;*.html;*.htm;*.docx;*.epub)|*.txt;*.md;*.markdown;*.html;*.htm;*.docx;*.epub|All files (*.*)|*.*",
            Multiselect = false,
            CheckFileExists = true,
        };
        if (dialog.ShowDialog(this) == true)
        {
            await ShowImportDialogAsync(dialog.FileName);
        }
    }

    private void MainWindow_DragOver(object sender, DragEventArgs e)
    {
        e.Effects = TryGetSingleImportPath(e.Data, out _)
            ? DragDropEffects.Copy
            : DragDropEffects.None;
        e.Handled = true;
    }

    private async void MainWindow_Drop(object sender, DragEventArgs e)
    {
        if (TryGetSingleImportPath(e.Data, out var path))
        {
            await ShowImportDialogAsync(path);
        }
        else
        {
            FooterText.Text = "Drop one TXT, Markdown, HTML, DOCX, or EPUB file.";
        }
        e.Handled = true;
    }

    private async Task ShowImportDialogAsync(string filePath)
    {
        if (_onboarding.State is not (ConnectionState.Ready or ConnectionState.BackendDegraded))
        {
            FooterText.Text = "Connect to the local Reader service before importing.";
            return;
        }
        var dialog = new ImportPreviewDialog(GetClient(), filePath) { Owner = this };
        if (dialog.ShowDialog() == true && dialog.ImportedDocument is ReaderDocument imported)
        {
            await RefreshLibraryAsync();
            DocumentsGrid.SelectedItem = _library?.Documents.FirstOrDefault(item => item.Id == imported.Id);
            FooterText.Text = $"Imported {imported.TotalBlocks:N0} block(s) to Inbox.";
        }
    }

    private static bool TryGetSingleImportPath(IDataObject data, out string path)
    {
        path = string.Empty;
        if (!data.GetDataPresent(DataFormats.FileDrop) ||
            data.GetData(DataFormats.FileDrop) is not string[] { Length: 1 } files)
        {
            return false;
        }
        var extension = Path.GetExtension(files[0]).ToLowerInvariant();
        if (extension is not (".txt" or ".md" or ".markdown" or ".html" or ".htm" or ".docx" or ".epub"))
        {
            return false;
        }
        path = files[0];
        return File.Exists(path);
    }

    private async Task RefreshLibraryAsync()
    {
        if (_library is null)
        {
            return;
        }

        try
        {
            await _library.RefreshAsync(SearchTextBox.Text.Trim(), SelectedLibraryState());
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
            var selectedDocument = _editor.Document is ReaderDocument current &&
                string.Equals(current.Id, document.Id, StringComparison.Ordinal)
                ? current
                : document;
            await LoadDocumentAsync(selectedDocument);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Document: {exception.Message}";
        }
    }

    private async Task LoadDocumentAsync(ReaderDocument document)
    {
        if (_editor is null)
        {
            return;
        }
        var loadGeneration = ++_documentLoadGeneration;
        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                await LoadDocumentCoreAsync(document);
                return;
            }
            catch (ReaderApiException exception) when (
                exception.ErrorType == "rate_limited" && attempt == 0)
            {
                FooterText.Text =
                    "The local service is temporarily busy. The document is not locked; Reader will retry automatically in one minute.";
                await Task.Delay(DocumentRateLimitRetryDelay);
                if (_closed || loadGeneration != _documentLoadGeneration)
                {
                    return;
                }
            }
            catch (Exception exception) when (
                exception is ReaderApiException or ReaderServiceUnavailableException)
            {
                FooterText.Text = $"Document: {exception.Message}";
                return;
            }
        }
    }

    private async Task LoadDocumentCoreAsync(ReaderDocument document)
    {
        if (_editor is null)
        {
            return;
        }
        try
        {
            if (_playback?.IsActive == true)
            {
                await _playback.StopAsync();
            }

            _continuousDocument = null;
            await LoadContinuousDocumentAsync(document);
            ReadingWindowPage? readingPage = null;
            if (_continuousDocument is not null)
            {
                _editor.LoadBlock(document, _continuousDocument.Blocks.FirstOrDefault());
                readingPage = _readingWindow?.UseLoadedDocument(
                    document.Id,
                    _continuousDocument.Blocks);
            }
            else if (_readingWindow is not null)
            {
                readingPage = await _readingWindow.LoadAsync(document.Id, 0);
                _editor.LoadBlock(document, readingPage.Blocks.FirstOrDefault());
            }
            else
            {
                await _editor.LoadAsync(document);
            }
            if (readingPage is not null)
            {
                await ShowReadingPageAsync(readingPage);
            }

            _textCursor = null;
            _updatingEditor = true;
            DocumentTitleText.Text = document.Title;
            EditorTextBox.Text = _continuousDocument?.Text ?? string.Empty;
            EditorTextBox.IsReadOnly = _continuousDocument is null;
            ReadingRangeText.Text = $"{document.TotalCharacters:N0} characters · {document.TotalBlocks:N0} block(s)";
            EditorHintText.Text = document.IsEditable
                ? _continuousDocument is null
                    ? $"This document is too large for the continuous editor. Reading remains page-based above {ContinuousEditorMaxCharacters:N0} characters."
                    : "Select and copy across the whole document, or click anywhere to edit. Use Start at cursor when you want playback to begin at the caret. Save one paragraph before editing another."
                : DescribeStructuredDocument(document);
            if (_continuousDocument is not null)
            {
                FooterText.Text = "Showing the complete document.";
            }
            UpdateEditorButtons();
            UpdatePlaybackControls();
        }
        finally
        {
            _updatingEditor = false;
        }
    }

    private async Task LoadContinuousDocumentAsync(ReaderDocument document)
    {
        _continuousDocument = null;
        if (!document.IsEditable ||
            document.TotalCharacters > ContinuousEditorMaxCharacters ||
            document.TotalBlocks > ContinuousEditorMaxBlocks)
        {
            return;
        }

        var blocks = new List<ReaderBlock>(document.TotalBlocks);
        var afterOrdinal = -1;
        while (true)
        {
            var page = await GetClient().GetBlocksAsync(
                document.Id,
                afterOrdinal,
                limit: 500);
            blocks.AddRange(page.Blocks);
            if (page.NextAfterOrdinal is not int nextAfterOrdinal)
            {
                break;
            }
            if (nextAfterOrdinal <= afterOrdinal)
            {
                throw new ReaderApiException(
                    "reader_invalid_page",
                    "The service returned a non-advancing document page.",
                    502);
            }
            afterOrdinal = nextAfterOrdinal;
        }
        _continuousDocument = new ContinuousDocumentText(blocks);
    }

    private async void LibraryWorkflowButton_Click(object sender, RoutedEventArgs e)
    {
        var document = _editor?.Document;
        var cursor = _playback?.LastFullyPlayedCursor;
        if (cursor is null && document is not null)
        {
            try
            {
                cursor = (await GetClient().GetPositionAsync(document.Id))?.Cursor;
            }
            catch (Exception exception) when (
                exception is ReaderApiException or ReaderServiceUnavailableException)
            {
                FooterText.Text = $"Position: {exception.Message}";
            }
        }

        var dialog = new LibraryWorkflowDialog(
            GetClient(),
            document,
            cursor,
            SelectedVoiceId())
        {
            Owner = this,
        };
        if (dialog.ShowDialog() == true && dialog.SelectedDocumentId is string documentId)
        {
            await OpenQueuedOrBookmarkedDocumentAsync(documentId, dialog.SelectedCursor);
        }
    }

    private async Task OpenQueuedOrBookmarkedDocumentAsync(
        string documentId,
        ReaderCursor? cursor)
    {
        try
        {
            var document = await GetClient().GetDocumentAsync(documentId);
            await LoadDocumentAsync(document);
            if (_playback is not null)
            {
                await _playback.PlayAsync(
                    document,
                    voice: SelectedVoiceId(),
                    startCursor: cursor);
            }
            FooterText.Text = cursor is null
                ? "Playing the selected queue item."
                : "Playing from the selected bookmark.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderStreamProtocolException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Library workflow: {exception.Message}";
        }
    }

    private async void FinishDocumentButton_Click(object sender, RoutedEventArgs e) =>
        await UpdateDocumentStateAsync("finished");

    private async void ArchiveDocumentButton_Click(object sender, RoutedEventArgs e) =>
        await UpdateDocumentStateAsync("archived");

    private async void RestoreDocumentButton_Click(object sender, RoutedEventArgs e) =>
        await UpdateDocumentStateAsync("inbox");

    private async void DeleteDocumentButton_Click(object sender, RoutedEventArgs e)
    {
        if (_editor?.Document is not ReaderDocument document || _playback?.IsActive == true)
        {
            return;
        }

        var unsavedWarning = _editor.HasUnsavedChanges
            ? "\n\nYour unsaved text changes will also be discarded."
            : string.Empty;
        var choice = MessageBox.Show(
            "Delete this article from the Reader library?\n\n" +
            "It will also be removed from the reading queue. The original imported file will not be deleted." +
            unsavedWarning,
            "Delete article",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (choice != MessageBoxResult.Yes)
        {
            return;
        }

        try
        {
            await GetClient().DeleteDocumentAsync(document.Id, document.RowVersion);
            DocumentsGrid.SelectedItem = null;
            ClearDocumentDisplay();
            await RefreshLibraryAsync();
            if (_library?.Documents.FirstOrDefault() is ReaderDocument next)
            {
                DocumentsGrid.SelectedItem = next;
            }
            FooterText.Text = "Article deleted from the Reader library.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Delete article: {exception.Message}";
        }
    }

    private async void RenameDocumentButton_Click(object sender, RoutedEventArgs e)
    {
        if (_editor?.Document is not ReaderDocument document)
        {
            return;
        }

        var dialog = new RenameDocumentDialog(document.Title) { Owner = this };
        if (dialog.ShowDialog() != true || dialog.NewTitle is not string title)
        {
            return;
        }

        var result = await _editor.RenameAsync(title);
        if (!result.Saved)
        {
            FooterText.Text = result.Message ?? "The title was not changed.";
            return;
        }

        DocumentTitleText.Text = _editor.Document!.Title;
        FooterText.Text = "Document title updated.";
        await RefreshLibraryAfterMutationAsync();
        UpdateEditorButtons();
    }

    private async Task UpdateDocumentStateAsync(string state)
    {
        if (_editor?.Document is not ReaderDocument current)
        {
            return;
        }
        try
        {
            var updated = await GetClient().UpdateDocumentAsync(
                current.Id,
                new UpdateDocumentRequest(current.RowVersion, State: state));
            await _editor.LoadAsync(updated);
            await RefreshLibraryAsync();
            UpdateEditorButtons();
            FooterText.Text = $"Document moved to {state}.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Document state: {exception.Message}";
        }
    }

    private void ClearDocumentDisplay()
    {
        ++_documentLoadGeneration;
        _editor?.Clear();
        _continuousDocument = null;
        _textCursor = null;
        _readingBlocks.Clear();
        _updatingEditor = true;
        try
        {
            DocumentTitleText.Text = "Select a document";
            EditorHintText.Text = "Editable text will appear here.";
            EditorTextBox.Text = string.Empty;
            ReadingRangeText.Text = "No article selected";
        }
        finally
        {
            _updatingEditor = false;
        }
        UpdateEditorButtons();
        UpdatePlaybackControls();
    }

    private async Task AutoAdvanceAsync(string completedDocumentId)
    {
        if (!await _autoAdvanceLock.WaitAsync(0))
        {
            return;
        }
        try
        {
            var next = await GetClient().AdvanceQueueAsync(completedDocumentId);
            if (next is null)
            {
                FooterText.Text = "Queue completed.";
                return;
            }
            var document = await GetClient().GetDocumentAsync(next.DocumentId);
            await LoadDocumentAsync(document);
            if (_playback is not null)
            {
                await _playback.PlayAsync(document, voice: SelectedVoiceId());
            }
            FooterText.Text = "Advanced to the next queue item.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderStreamProtocolException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Queue auto-advance: {exception.Message}";
        }
        finally
        {
            _autoAdvanceLock.Release();
        }
    }

    private void EditorTextBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_updatingEditor ||
            _editor?.Document is not ReaderDocument document ||
            _continuousDocument is null ||
            !document.IsEditable)
        {
            return;
        }

        if (string.Equals(EditorTextBox.Text, _continuousDocument.Text, StringComparison.Ordinal))
        {
            _editor.RevertLocalChanges();
            UpdateTextCursorFromContinuousEditor();
            UpdateEditorButtons();
            UpdatePlaybackControls();
            return;
        }

        if (_continuousDocument.TryMapSingleBlockEdit(EditorTextBox.Text, out var edit) &&
            edit is not null)
        {
            if (_editor.HasUnsavedChanges &&
                _editor.PendingRangeDeletion is null &&
                _editor.Block is ReaderBlock activeBlock &&
                !string.Equals(activeBlock.Id, edit.Block.Id, StringComparison.Ordinal))
            {
                RestoreContinuousWorkingText(
                    "Save or revert the current paragraph before editing another one.");
                return;
            }

            if (_editor.Block is not ReaderBlock loadedBlock ||
                !string.Equals(loadedBlock.Id, edit.Block.Id, StringComparison.Ordinal))
            {
                _editor.LoadBlock(document, edit.Block);
            }
            _editor.SetWorkingText(edit.ReplacementText);
            UpdateTextCursorFromContinuousEditor();
            UpdateEditorButtons();
            UpdatePlaybackControls();
            return;
        }

        if (_continuousDocument.TryMapCrossBlockDeletion(
                EditorTextBox.Text,
                out var rangeDeletion) &&
            rangeDeletion is not null)
        {
            if (_editor.HasUnsavedChanges && _editor.PendingRangeDeletion is null)
            {
                RestoreContinuousWorkingText(
                    "Save or revert the current paragraph before deleting across paragraphs.");
                return;
            }
            if (_editor.Block is not ReaderBlock loadedBlock ||
                !string.Equals(
                    loadedBlock.Id,
                    rangeDeletion.StartBlock.Id,
                    StringComparison.Ordinal))
            {
                _editor.LoadBlock(document, rangeDeletion.StartBlock);
            }
            _editor.SetRangeDeletion(rangeDeletion);
            UpdateTextCursorFromContinuousEditor();
            UpdateEditorButtons();
            UpdatePlaybackControls();
            return;
        }

        RestoreContinuousWorkingText(
            "Selection deletion may span paragraphs. Other saved edits change one paragraph at a time.");
    }

    private void EditorTextBox_SelectionChanged(object sender, RoutedEventArgs e)
    {
        if (!_updatingEditor)
        {
            UpdateTextCursorFromContinuousEditor();
        }
    }

    private void RestoreContinuousWorkingText(string message)
    {
        var caret = EditorTextBox.CaretIndex;
        var text = CurrentContinuousDocument()?.Text ?? string.Empty;
        _updatingEditor = true;
        EditorTextBox.Text = text;
        EditorTextBox.CaretIndex = Math.Clamp(caret, 0, text.Length);
        _updatingEditor = false;
        FooterText.Text = message;
        UpdateTextCursorFromContinuousEditor();
        UpdateEditorButtons();
        UpdatePlaybackControls();
    }

    private ContinuousDocumentText? CurrentContinuousDocument()
    {
        if (_continuousDocument is null || _editor?.HasUnsavedChanges != true)
        {
            return _continuousDocument;
        }
        if (_editor.PendingRangeDeletion is { } rangeDeletion)
        {
            return _continuousDocument.ApplyRangeDeletion(rangeDeletion);
        }
        if (_editor.Block is not ReaderBlock block)
        {
            return _continuousDocument;
        }
        return _continuousDocument.ReplaceBlock(block with
        {
            Text = _editor.WorkingText,
            CharacterCount = _editor.WorkingText.Length,
        });
    }

    private void UpdateTextCursorFromContinuousEditor()
    {
        if (_editor?.Document is not ReaderDocument document ||
            CurrentContinuousDocument() is not ContinuousDocumentText continuousDocument ||
            continuousDocument.Blocks.Count == 0)
        {
            _textCursor = null;
            return;
        }

        _textCursor = continuousDocument.CursorAt(
            document.Id,
            document.ContentRevision,
            EditorTextBox.CaretIndex);
        UpdatePlaybackControls();
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
            var caret = EditorTextBox.CaretIndex;
            if (_editor.Document is ReaderDocument updatedDocument)
            {
                _library?.ReplaceDocument(updatedDocument);
            }
            if (_continuousDocument is not null && _editor.Block is ReaderBlock savedBlock)
            {
                _updatingEditor = true;
                _continuousDocument = result.AppliedRangeDeletion is { } rangeDeletion
                    ? _continuousDocument.ApplyRangeDeletion(rangeDeletion)
                    : _continuousDocument.ReplaceBlock(savedBlock);
                EditorTextBox.Text = _continuousDocument.Text;
                EditorTextBox.CaretIndex = Math.Clamp(caret, 0, EditorTextBox.Text.Length);
                _updatingEditor = false;
                if (_readingWindow is not null && _editor.Document is ReaderDocument document)
                {
                    var page = _readingWindow.UseLoadedDocument(
                        document.Id,
                        _continuousDocument.Blocks,
                        _readingWindow.Current.StartOrdinal);
                    if (result.AppliedRangeDeletion is not null)
                    {
                        await ShowReadingPageAsync(page);
                    }
                }
                if (result.AppliedRangeDeletion is null)
                {
                    _readingBlocks.FirstOrDefault(item =>
                        string.Equals(item.Id, savedBlock.Id, StringComparison.Ordinal))
                        ?.ApplySavedBlock(savedBlock);
                }
            }
            UpdateTextCursorFromContinuousEditor();
            UpdatePlaybackControls();
        }
    }

    private void RevertEditButton_Click(object sender, RoutedEventArgs e)
    {
        if (_editor is null)
        {
            return;
        }

        _editor.RevertLocalChanges();
        var caret = EditorTextBox.CaretIndex;
        _updatingEditor = true;
        EditorTextBox.Text = _continuousDocument?.Text ?? string.Empty;
        EditorTextBox.CaretIndex = Math.Clamp(caret, 0, EditorTextBox.Text.Length);
        _updatingEditor = false;
        FooterText.Text = "Local changes reverted";
        UpdateTextCursorFromContinuousEditor();
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
            var caret = EditorTextBox.CaretIndex;
            if (_editor.Document is ReaderDocument document)
            {
                _library?.ReplaceDocument(document);
                await LoadContinuousDocumentAsync(document);
                if (_readingWindow is not null)
                {
                    var startOrdinal = _readingWindow.Current.StartOrdinal;
                    var page = _continuousDocument is not null
                        ? _readingWindow.UseLoadedDocument(
                            document.Id,
                            _continuousDocument.Blocks,
                            startOrdinal)
                        : await _readingWindow.LoadAsync(document.Id, startOrdinal);
                    await ShowReadingPageAsync(page);
                }
            }
            _updatingEditor = true;
            EditorTextBox.Text = _continuousDocument?.Text ?? string.Empty;
            EditorTextBox.CaretIndex = Math.Clamp(caret, 0, EditorTextBox.Text.Length);
            _updatingEditor = false;
            UpdateTextCursorFromContinuousEditor();
            UpdatePlaybackControls();
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
        try
        {
            await _library.RefreshAsync(SearchTextBox.Text.Trim(), SelectedLibraryState());
            DocumentsGrid.SelectedItem = _library.Documents.FirstOrDefault(item => item.Id == selectedId);
            LoadMoreButton.IsEnabled = _library.HasMore;
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"The change was saved, but the library refresh is delayed: {exception.Message}";
        }
    }

    private async void DuplicateEditableButton_Click(object sender, RoutedEventArgs e)
    {
        if (_client is null || _editor?.Document is not ReaderDocument document || document.IsEditable)
        {
            return;
        }
        try
        {
            var editable = await _client.DuplicateAsEditableTextAsync(document.Id);
            await RefreshLibraryAsync();
            DocumentsGrid.SelectedItem = _library?.Documents.FirstOrDefault(item => item.Id == editable.Id);
            FooterText.Text = "Created an editable plain-text copy.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Duplicate: {exception.Message}";
        }
    }

    private async void PreviousReadingPageButton_Click(object sender, RoutedEventArgs e)
    {
        if (_readingWindow is not null && _editor?.Document is ReaderDocument document)
        {
            if (_editor.HasUnsavedChanges)
            {
                FooterText.Text = "Save or revert changes before changing page.";
                return;
            }
            await ShowReadingPageAsync(await _readingWindow.LoadPreviousAsync(document.Id));
        }
    }

    private async void NextReadingPageButton_Click(object sender, RoutedEventArgs e)
    {
        if (_readingWindow is not null && _editor?.Document is ReaderDocument document)
        {
            if (_editor.HasUnsavedChanges)
            {
                FooterText.Text = "Save or revert changes before changing page.";
                return;
            }
            await ShowReadingPageAsync(await _readingWindow.LoadNextAsync(document.Id));
        }
    }

    private void ReadingBlocksList_SelectionChanged(object sender, SelectionChangedEventArgs e) =>
        UpdateEditorButtons();

    private void UpdateEditorButtons()
    {
        var editable = _editor?.IsEditable == true && _continuousDocument is not null;
        var playbackActive = _playback?.IsActive == true;
        EditorTextBox.IsReadOnly = playbackActive || !editable;
        SaveEditButton.IsEnabled = editable && !playbackActive && _editor!.HasUnsavedChanges;
        RevertEditButton.IsEnabled = editable && !playbackActive && _editor!.HasUnsavedChanges;
        UndoButton.IsEnabled = editable && !playbackActive && !_editor!.HasUnsavedChanges;
        RedoButton.IsEnabled = editable && !playbackActive && !_editor!.HasUnsavedChanges;
        var document = _editor?.Document;
        RenameDocumentButton.IsEnabled = document is not null && !playbackActive;
        DeleteDocumentButton.IsEnabled = document is not null && !playbackActive;
        FinishDocumentButton.IsEnabled = document is not null && document.State != "finished";
        ArchiveDocumentButton.IsEnabled = document is not null && document.State != "archived";
        RestoreDocumentButton.IsEnabled = document is not null &&
            document.State is "archived" or "finished";
    }

    private async void PlayPauseButton_Click(object sender, RoutedEventArgs e) =>
        await ToggleUnifiedPlaybackAsync();

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
            await StopEphemeralAsync(clearReplay: true);
            await _playback.PlayAsync(_editor.Document, voice: SelectedVoiceId());
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

    private async void StopButton_Click(object sender, RoutedEventArgs e) =>
        await StopUnifiedPlaybackAsync();

    private async void PlayFromCursorButton_Click(object sender, RoutedEventArgs e)
    {
        if (_playback is null || _editor?.Document is not ReaderDocument document)
        {
            return;
        }
        if (_editor.HasUnsavedChanges)
        {
            FooterText.Text = "Save or revert the local edit before playback.";
            return;
        }

        UpdateTextCursorFromContinuousEditor();
        if (_textCursor is not ReaderCursor cursor)
        {
            FooterText.Text = "Place the text cursor in an editable article first.";
            return;
        }

        try
        {
            await StopEphemeralAsync(clearReplay: true);
            await _playback.PlayAsync(
                document,
                voice: SelectedVoiceId(),
                startCursor: cursor);
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

    private async void PreviousSectionButton_Click(object sender, RoutedEventArgs e) =>
        await NavigateSectionAsync(next: false);

    private async void NextSectionButton_Click(object sender, RoutedEventArgs e) =>
        await NavigateSectionAsync(next: true);

    private async Task NavigateSectionAsync(bool next)
    {
        if (_playback is null ||
            _readingWindow is null ||
            _editor?.Document is not ReaderDocument document)
        {
            return;
        }
        if (_editor.HasUnsavedChanges)
        {
            FooterText.Text = "Save or revert the local edit before changing playback position.";
            return;
        }

        try
        {
            var currentOrdinal = _playback.LastFullyPlayedCursor?.BlockOrdinal ?? 0;
            FooterText.Text = next
                ? "Finding the next section..."
                : "Finding the previous section...";
            var target = next
                ? await _readingWindow.FindNextSectionAsync(document.Id, currentOrdinal)
                : await _readingWindow.FindPreviousSectionAsync(document.Id, currentOrdinal);
            if (target is null)
            {
                FooterText.Text = next
                    ? "No next section in this article."
                    : "No previous section in this article.";
                return;
            }

            await _playback.SeekAsync(
                document,
                new ReaderCursor(
                    document.Id,
                    target.Id,
                    target.Ordinal,
                    0,
                    document.ContentRevision),
                voice: SelectedVoiceId());
            FooterText.Text = next
                ? "Started the next section."
                : "Started the previous section.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderStreamProtocolException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Section navigation: {exception.Message}";
        }
    }

    private async Task LoadReadingWindowAsync(ReaderDocument document, int startOrdinal)
    {
        if (_readingWindow is null)
        {
            return;
        }
        var page = await _readingWindow.LoadAsync(document.Id, Math.Max(0, startOrdinal));
        await ShowReadingPageAsync(page);
    }

    private Task ShowReadingPageAsync(ReadingWindowPage page)
    {
        _readingBlocks.Clear();
        foreach (var block in page.Blocks)
        {
            _readingBlocks.Add(new ReaderBlockDisplay(block));
        }
        ReadingBlocksList.SelectedItem = _readingBlocks.FirstOrDefault();
        PreviousReadingPageButton.IsEnabled = page.HasPrevious;
        NextReadingPageButton.IsEnabled = page.HasNext;
        var pageNumber = page.StartOrdinal / 64 + 1;
        var document = _editor?.Document;
        ReadingRangeText.Text = page.Blocks.Count == 0
            ? "No readable text"
            : document is null
                ? $"Blocks {page.Blocks[0].Ordinal + 1:N0}–{page.Blocks[^1].Ordinal + 1:N0}"
                : $"Blocks {page.Blocks[0].Ordinal + 1:N0}–{page.Blocks[^1].Ordinal + 1:N0} of {document.TotalBlocks:N0}";
        FooterText.Text = page.Blocks.Count == 0
            ? "This document contains no readable blocks."
            : $"Showing document page {pageNumber:N0}.";
        UpdatePlaybackControls();
        UpdateEditorButtons();
        return Task.CompletedTask;
    }

    private void Playback_StateChanged(object? sender, PlaybackStateChanged change)
    {
        Dispatcher.BeginInvoke(new Action(async () =>
        {
            PlaybackStatusText.Text = change.Message is null
                ? change.State.ToString()
                : $"{change.State}: {change.Message}";
            FooterText.Text = change.Message ?? $"Playback {change.State.ToString().ToLowerInvariant()}";
            _trayIcon?.SetStatus(change.State.ToString());
            UpdatePlaybackControls();
            if (change.State is not ReaderPlaybackState.Playing)
            {
                RestorePausedEditorViewport(change.Cursor);
            }
            UpdateEditorButtons();
            UpdateCompactController();
            if (change.State == ReaderPlaybackState.Completed &&
                AutoAdvanceCheckBox.IsChecked == true &&
                change.DocumentId is not null)
            {
                await AutoAdvanceAsync(change.DocumentId);
            }
        }));
    }

    private void Playback_HighlightChanged(object? sender, PlaybackHighlight highlight)
    {
        Dispatcher.BeginInvoke(new Action(async () => await ShowHighlightAsync(highlight)));
    }

    private void Playback_RuleWarning(object? sender, ReaderStreamWarning warning)
    {
        Dispatcher.BeginInvoke(new Action(() =>
        {
            FooterText.Text = $"Speech rule warning: {warning.Message}";
            PlaybackStatusText.Text = "Playing with a skipped speech rule";
        }));
    }

    private void SpeechRulesButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new RuleEditorDialog(GetClient()) { Owner = this };
        dialog.ShowDialog();
    }

    private void CreateRuleFromSelectionButton_Click(object sender, RoutedEventArgs e)
    {
        var selection = EditorTextBox.SelectedText;
        if (string.IsNullOrWhiteSpace(selection))
        {
            FooterText.Text = "Select text in an editable document before creating a speech rule.";
            return;
        }

        var dialog = new RuleEditorDialog(
            GetClient(),
            selection,
            _editor?.Document?.LanguageHint,
            _editor?.Document?.Id)
        {
            Owner = this,
        };
        dialog.ShowDialog();
    }

    private async Task ShowHighlightAsync(PlaybackHighlight highlight)
    {
        if (_editor?.Document is not ReaderDocument document ||
            !string.Equals(document.Id, highlight.DocumentId, StringComparison.Ordinal) ||
            highlight.SourceSpans.Count == 0)
        {
            return;
        }

        if (document.IsEditable && _continuousDocument is not null)
        {
            ShowContinuousEditorHighlight(document, highlight.SourceSpans);
            return;
        }

        var firstSpan = highlight.SourceSpans[0];
        if (FollowReadingCheckBox.IsChecked == true && _readingWindow is not null)
        {
            var priorStartOrdinal = _readingWindow.Current.StartOrdinal;
            var page = await _readingWindow.FollowPlaybackAsync(
                document.Id,
                firstSpan.BlockOrdinal);
            if (page.StartOrdinal != priorStartOrdinal || _readingBlocks.Count == 0)
            {
                await ShowReadingPageAsync(page);
            }
        }

        foreach (var block in _readingBlocks)
        {
            block.HighlightStart = -1;
            block.HighlightLength = 0;
        }
        ReaderBlockDisplay? followedBlock = null;
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
            if (FollowReadingCheckBox.IsChecked == true &&
                string.Equals(block.Id, firstSpan.BlockId, StringComparison.Ordinal))
            {
                followedBlock = block;
            }
        }
        if (followedBlock is not null)
        {
            BringReadingHighlightIntoView(followedBlock);
        }
    }

    private void ShowContinuousEditorHighlight(
        ReaderDocument document,
        IReadOnlyList<ReaderSourceSpan> sourceSpans)
    {
        if (_continuousDocument is null || sourceSpans.Count == 0)
        {
            return;
        }

        var orderedSpans = sourceSpans
            .OrderBy(span => span.BlockOrdinal)
            .ThenBy(span => span.StartOffset)
            .ToArray();
        var first = orderedSpans[0];
        var last = orderedSpans[^1];
        var startCursor = new ReaderCursor(
            document.Id,
            first.BlockId,
            first.BlockOrdinal,
            first.StartOffset,
            document.ContentRevision);
        var endCursor = new ReaderCursor(
            document.Id,
            last.BlockId,
            last.BlockOrdinal,
            last.EndOffset,
            document.ContentRevision);
        if (!_continuousDocument.TryGetCharacterOffset(startCursor, out var start) ||
            !_continuousDocument.TryGetCharacterOffset(endCursor, out var end))
        {
            return;
        }

        _updatingEditor = true;
        EditorTextBox.Select(start, Math.Max(0, end - start));
        _updatingEditor = false;
        var line = EditorTextBox.GetLineIndexFromCharacterIndex(start);
        if (line >= 0)
        {
            EditorTextBox.ScrollToLine(Math.Max(0, line - 2));
        }
    }

    private void BringReadingHighlightIntoView(ReaderBlockDisplay block)
    {
        ReadingBlocksList.SelectedItem = block;
        ReadingBlocksList.ScrollIntoView(block);
        ReadingBlocksList.UpdateLayout();
        if (ReadingBlocksList.ItemContainerGenerator.ContainerFromItem(block) is
                DependencyObject container &&
            FindVisualChild<SourceHighlightTextBlock>(container) is { } textBlock)
        {
            textBlock.BringHighlightedTextIntoView();
        }
    }

    private void RestorePausedEditorViewport(ReaderCursor? cursor)
    {
        if (cursor is null ||
            _continuousDocument is null ||
            _editor?.Document is not ReaderDocument document ||
            !string.Equals(document.Id, cursor.DocumentId, StringComparison.Ordinal) ||
            !_continuousDocument.TryGetCharacterOffset(cursor, out var characterOffset))
        {
            return;
        }

        _updatingEditor = true;
        EditorTextBox.CaretIndex = Math.Clamp(characterOffset, 0, EditorTextBox.Text.Length);
        EditorTextBox.SelectionLength = 0;
        _updatingEditor = false;
        _textCursor = cursor;
        EditorTextBox.UpdateLayout();
        var line = EditorTextBox.GetLineIndexFromCharacterIndex(EditorTextBox.CaretIndex);
        if (line >= 0)
        {
            EditorTextBox.ScrollToLine(Math.Max(0, line - 2));
        }
    }

    private static T? FindVisualChild<T>(DependencyObject root)
        where T : DependencyObject
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match)
            {
                return match;
            }
            if (FindVisualChild<T>(child) is { } descendant)
            {
                return descendant;
            }
        }
        return null;
    }

    private void UpdatePlaybackControls()
    {
        var hasDocument = _editor?.Document is not null;
        var structuredDocument = hasDocument && _editor?.Document?.IsEditable != true;
        var documentActive = _playback?.IsActive == true;
        var ephemeralPaused = !_ephemeralPlaying && _ephemeralReplayText is not null;
        var hasPlayback = _ephemeralPlaying || ephemeralPaused ||
            (hasDocument && _playback?.State is not ReaderPlaybackState.Stopped);
        var continuousEditableDocument = hasDocument &&
            _editor?.Document?.IsEditable == true &&
            _continuousDocument is not null;
        var pauseVisible = _ephemeralPlaying || documentActive;
        PlayPauseLabel.Text = pauseVisible ? "Pause" : "Play";
        PlayPauseIcon.Data = (Geometry)FindResource(
            pauseVisible ? "PauseGeometry" : "PlayGeometry");
        PlayPauseButton.IsEnabled = hasDocument || _ephemeralPlaying || ephemeralPaused;
        PlayFromCursorButton.IsEnabled = continuousEditableDocument &&
            !documentActive &&
            !_ephemeralPlaying &&
            !ephemeralPaused &&
            _textCursor is not null &&
            _editor?.HasUnsavedChanges != true;
        StopButton.IsEnabled = hasPlayback;
        var showSectionNavigation = _editor?.Document?.TotalSections > 1;
        PreviousSectionButton.Visibility = showSectionNavigation
            ? Visibility.Visible
            : Visibility.Collapsed;
        NextSectionButton.Visibility = showSectionNavigation
            ? Visibility.Visible
            : Visibility.Collapsed;
        PreviousSectionButton.IsEnabled = showSectionNavigation &&
            !_ephemeralPlaying &&
            !ephemeralPaused;
        NextSectionButton.IsEnabled = showSectionNavigation &&
            !_ephemeralPlaying &&
            !ephemeralPaused;
        var showContinuousEditor = continuousEditableDocument;
        var showReadingView = hasDocument && !showContinuousEditor;
        ReadingBlocksList.ItemTemplate = (DataTemplate)FindResource("ReadingBlockTemplate");
        ReadingBlocksList.Visibility = showReadingView ? Visibility.Visible : Visibility.Collapsed;
        EditorTextBox.Visibility = showContinuousEditor ? Visibility.Visible : Visibility.Collapsed;
        FollowReadingCheckBox.Visibility = showReadingView && (documentActive || structuredDocument)
            ? Visibility.Visible
            : Visibility.Collapsed;
        DuplicateEditableButton.IsEnabled = structuredDocument && !documentActive;
        PreviousReadingPageButton.Visibility = showReadingView ? Visibility.Visible : Visibility.Collapsed;
        NextReadingPageButton.Visibility = showReadingView ? Visibility.Visible : Visibility.Collapsed;
        SaveEditButton.Visibility = showContinuousEditor ? Visibility.Visible : Visibility.Collapsed;
        RevertEditButton.Visibility = showContinuousEditor ? Visibility.Visible : Visibility.Collapsed;
    }

    private void UpdateCompactController()
    {
        if (_compactController is null)
        {
            return;
        }

        var documentActive = _playback?.IsActive == true;
        var playing = _ephemeralPlaying || documentActive;
        var state = _ephemeralPlaying
            ? "Reading clipboard"
            : _ephemeralReplayText is not null
                ? "Clipboard paused"
                : _playback?.State.ToString() ?? "Stopped";
        var context = _ephemeralPlaying || _ephemeralReplayText is not null
            ? (_settings.PrivacyMode ? "Private clipboard text" : "Clipboard text")
            : _editor?.Document?.Title ?? "No document selected";
        _compactController.SetState(state, context, playing);
    }

    private async void MainWindow_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape &&
            (_ephemeralPlaying || _ephemeralReplayText is not null ||
                _playback?.State is not ReaderPlaybackState.Stopped))
        {
            e.Handled = true;
            await StopUnifiedPlaybackAsync();
            return;
        }
        if (e.Key == Key.Space && Keyboard.FocusedElement is not TextBox)
        {
            e.Handled = true;
            await ToggleUnifiedPlaybackAsync();
        }
    }

    private void SetBusy(bool busy, string? text = null)
    {
        RefreshButton.IsEnabled = !busy;
        ActionButton.IsEnabled = !busy;
        if (busy)
        {
            StartServiceButton.IsEnabled = false;
            StopServiceButton.IsEnabled = false;
        }
        else
        {
            var serviceUnavailable = _onboarding.State == ConnectionState.ServiceUnavailable;
            StartServiceButton.IsEnabled = serviceUnavailable;
            StopServiceButton.IsEnabled = !serviceUnavailable ||
                ScheduledServiceController.OwnsRunningService;
        }
        if (text is not null)
        {
            StatusText.Text = text;
        }
    }

    private sealed record VoiceChoice(VoiceDescriptor Voice, bool IsServiceDefault)
    {
        public string Id => Voice.Id;
        public string DisplayName => IsServiceDefault
            ? $"{Voice.Name} (service default)"
            : Voice.Name;
        public string Details =>
            $"{Voice.Language} · {Voice.QualityTier} quality · {Voice.Engine}";
        public override string ToString() => DisplayName;
    }

    private static string DescribeStructuredDocument(ReaderDocument document)
    {
        const string baseline = "Structured imports are read-only. Duplicate this document to edit a plain-text copy.";
        if (document.Metadata.ValueKind != JsonValueKind.Object ||
            !document.Metadata.TryGetProperty("import", out var import) ||
            !import.TryGetProperty("warnings", out var warnings) ||
            warnings.ValueKind != JsonValueKind.Array ||
            warnings.GetArrayLength() == 0)
        {
            return baseline;
        }
        var messages = warnings.EnumerateArray()
            .Take(3)
            .Select(item => item.TryGetProperty("message", out var message)
                ? message.GetString()
                : null)
            .Where(message => !string.IsNullOrWhiteSpace(message));
        return $"{baseline} Import warnings: {string.Join(" ", messages)}";
    }
}
