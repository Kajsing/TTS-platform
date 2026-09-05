using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
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
    private ReaderPrivacySessionStore? _privacySessions;
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
    private WindowsAudioInterruptionMonitor? _audioInterruptionMonitor;
    private ReaderTrayIcon? _trayIcon;
    private CompactControllerWindow? _compactController;
    private HwndSource? _windowSource;
    private WasapiAudioOutput? _ephemeralAudio;
    private CancellationTokenSource? _ephemeralCancellation;
    private Task? _ephemeralTask;
    private string? _ephemeralReplayText;
    private readonly ObservableCollection<ReaderBlockDisplay> _readingBlocks = [];
    private readonly ObservableCollection<FolderFilterItem> _folderFilters =
    [
        new(null, "All articles", false, true),
    ];
    private readonly SemaphoreSlim _autoAdvanceLock = new(1, 1);
    private readonly SemaphoreSlim _desktopOpenLock = new(1, 1);
    private readonly SemaphoreSlim _documentLoadLock = new(1, 1);
    private readonly SemaphoreSlim _audioInterruptionLock = new(1, 1);
    private readonly DispatcherTimer _desktopOpenTimer = new()
    {
        Interval = DesktopOpenPollInterval,
    };
    private readonly DispatcherTimer _clipboardSnoozeTimer = new()
    {
        Interval = TimeSpan.FromSeconds(1),
    };
    private readonly ClipboardPromptPolicy _clipboardPromptPolicy;
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
    private bool _suppressDocumentSelectionLoad;
    private ContinuousDocumentText? _continuousDocument;
    private ReaderCursor? _textCursor;
    private PlaybackHighlightAdorner? _continuousHighlightAdorner;
    private ArticleFindDocumentLoader? _findLoader;
    private ArticleFindDocument? _findDocument;
    private ArticleFindResult _findResult = ArticleFindResult.Empty;
    private CancellationTokenSource? _findCancellation;
    private int _findMatchIndex = -1;
    private int _findGeneration;
    private bool _findSearchPending;
    private ReaderHighlighterConfiguration? _highlighterConfiguration;
    private ArticleFindDocument? _wordHighlightDocument;
    private WordHighlightResult _wordHighlightResult = WordHighlightResult.Empty;
    private IReadOnlyDictionary<int, IReadOnlyList<ReaderTextHighlight>>
        _wordHighlightsByBlockOrdinal = new Dictionary<int, IReadOnlyList<ReaderTextHighlight>>();
    private int _wordHighlightMatchIndex = -1;
    private int _wordHighlightGeneration;
    private bool _wordHighlightJumpInProgress;
    private bool _refreshingFolders;
    private bool _updatingWorkspaceChoices;
    private bool _audioInterruptionActive;
    private AutomaticPauseKind _automaticPauseKind;
    private string? _automaticPauseSource;

    public MainWindow(
        IDesktopSettingsStore settingsStore,
        DesktopSettings settings,
        bool smokeTest,
        TimeProvider? timeProvider = null,
        ReaderTrayIcon? sharedTray = null)
    {
        _settingsStore = settingsStore;
        _settings = settings;
        _smokeTest = smokeTest;
        _trayIcon = sharedTray;
        _clipboardPromptPolicy = new ClipboardPromptPolicy(timeProvider);
        InitializeComponent();
        ServiceUrlTextBox.Text = settings.ServiceBaseUrl;
        TokenPathTextBox.Text = settings.EffectiveTokenSource.Path;
        RefreshWorkspaceChoices();
        ReadingBlocksList.ItemsSource = _readingBlocks;
        FolderFilterComboBox.ItemsSource = _folderFilters;
        FolderFilterComboBox.SelectedIndex = 0;
        _desktopOpenTimer.Tick += DesktopOpenTimer_Tick;
        _clipboardSnoozeTimer.Tick += ClipboardSnoozeTimer_Tick;
        ContentRendered += MainWindow_ContentRendered;
        Loaded += MainWindow_Loaded;
        SourceInitialized += MainWindow_SourceInitialized;
        Closing += MainWindow_Closing;
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        if (_continuousHighlightAdorner is null)
        {
            _continuousHighlightAdorner = new PlaybackHighlightAdorner(EditorTextBox);
            EditorAdornerDecorator.AdornerLayer.Add(_continuousHighlightAdorner);
        }
        if (!_smokeTest)
        {
            await RefreshConnectionAsync();
        }
    }

    private async void MainWindow_ContentRendered(object? sender, EventArgs e)
    {
        if (!_smokeTest)
        {
            return;
        }

        ContentRendered -= MainWindow_ContentRendered;
        if (Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_LIFECYCLE_SMOKE") == "1") return;
        var agentSmoke = AgentSmokeScenario.LoadFromEnvironment();
        if (agentSmoke is not null)
        {
            try
            {
                await RunAgentSmokeAsync(agentSmoke);
                System.Windows.Application.Current.Shutdown();
            }
            catch (Exception exception)
            {
                File.WriteAllText(agentSmoke.MarkerPath, JsonSerializer.Serialize(new { failed = exception.GetType().Name, message = exception.Message }));
                System.Windows.Application.Current.Shutdown(1);
            }
            return;
        }

        var marker = Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_SMOKE_MARKER");
        if (!string.IsNullOrWhiteSpace(marker) &&
            Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_FOLDER_SMOKE") == "1")
        {
            try
            {
                await RunFolderVisibilitySmokeAsync(marker);
                System.Windows.Application.Current.Shutdown();
            }
            catch (Exception exception)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
                File.WriteAllText(marker, JsonSerializer.Serialize(new { failed = exception.GetType().Name, message = exception.Message }));
                System.Windows.Application.Current.Shutdown(1);
            }
            return;
        }
        if (!string.IsNullOrWhiteSpace(marker))
        {
            var optionsWindow = new OptionsDialog(_settings) { Owner = this };
            optionsWindow.Show();
            optionsWindow.UpdateLayout();
            optionsWindow.Close();
            Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
            File.WriteAllText(
                marker,
                JsonSerializer.Serialize(new
                {
                    rendered = true,
                    options_rendered = true,
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

        _audioInterruptionMonitor = new WindowsAudioInterruptionMonitor();
        _audioInterruptionMonitor.Changed += AudioInterruptionMonitor_Changed;
        _audioInterruptionMonitor.Enabled = _settings.EffectivePauseForCallsAndAlarms;

        _trayIcon?.SetClipboardMonitoring(_settings.ClipboardMonitoringEnabled);
        _trayIcon?.SetStatus("Stopped");

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

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
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
            // Finish the first Closing event before attempting the confirmed
            // close. Stop/save can complete synchronously on an idle Reader.
            Dispatcher.BeginInvoke(new Action(async () => await CloseReaderAsync()), DispatcherPriority.Background);
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

    internal async Task HandleTrayCommandAsync(ReaderTrayCommand command)
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
        }
    }

    internal void OpenMainWindow()
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

    internal async Task<bool> CloseReaderAsync()
    {
        if (_localServiceOperation) return false;
        if (_closed) return true;
        if (_shutdownInProgress)
        {
            return false;
        }
        _shutdownInProgress = true;
        try
        {
            if (_documentLoadLock.CurrentCount == 0 || _clipboardPromptOpen)
            {
                FooterText.Text = "Finish the current document operation before closing Reader.";
                return false;
            }
            if (OwnedWindows.Cast<Window>().Any(window => window != _compactController && window.IsVisible))
            {
                FooterText.Text = "Close the open Reader dialog before closing Reader.";
                return false;
            }
            if (_editor?.HasUnsavedChanges == true)
            {
                OpenMainWindow();
                if (_smokeTest) return false;
                var choice = MessageBox.Show(this,
                    "Save your text changes before closing Reader?\n\nYes: save and close. No: discard changes. Cancel: keep Reader open.",
                    "Unsaved article changes", MessageBoxButton.YesNoCancel, MessageBoxImage.Question);
                if (choice == MessageBoxResult.Cancel) return false;
                if (choice == MessageBoxResult.Yes)
                {
                    IsEnabled = false;
                    var result = await _editor.SaveAsync();
                    if (!result.Saved && _editor.HasUnsavedChanges)
                    {
                        FooterText.Text = result.Message ?? "Changes could not be saved; Reader remains open.";
                        return false;
                    }
                }
            }
            IsEnabled = false;
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
            _exitRequested = true;
            Close();
            return _closed;
        }
        catch (Exception exception) when (exception is IOException or InvalidOperationException or
            ReaderApiException or ReaderServiceUnavailableException or ReaderTokenUnavailableException or
            System.Net.Http.HttpRequestException or OperationCanceledException)
        {
            FooterText.Text = $"Reader remains open because closing could not finish: {exception.Message}";
            return false;
        }
        finally
        {
            _shutdownInProgress = false;
            if (!_closed)
            {
                IsEnabled = true;
                _exitRequested = false;
            }
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
        if (_audioInterruptionMonitor is not null)
        {
            _audioInterruptionMonitor.Changed -= AudioInterruptionMonitor_Changed;
            _audioInterruptionMonitor.Dispose();
        }
        _clipboardListener?.Dispose();
        _trayIcon = null;
        StopEphemeralAsync(clearReplay: true).GetAwaiter().GetResult();
        _ephemeralAudio?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        if (_compactController is not null)
        {
            _compactController.AllowClose = true;
            _compactController.Close();
        }
        _playback?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _playbackPerformance?.Dispose();
        _continuousHighlightAdorner?.Dispose();
        _findCancellation?.Cancel();
        _findCancellation?.Dispose();
        _desktopOpenTimer.Stop();
        _clipboardSnoozeTimer.Stop();
        _autoAdvanceLock.Dispose();
        _audioInterruptionLock.Dispose();
        _httpClient?.Dispose();
        _synthesisHttpClient?.Dispose();
        if (_privacySessions is not null)
        {
            _privacySessions.SessionsChanged -= PrivacySessions_SessionsChanged;
            _privacySessions.Dispose();
        }
        base.OnClosed(e);
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) =>
        await RefreshConnectionAsync();

    private async void StartServiceButton_Click(object sender, RoutedEventArgs e) =>
        await StartLocalServiceAsync();

    private async void StopServiceButton_Click(object sender, RoutedEventArgs e) =>
        await StopLocalServiceAsync();

    internal event EventHandler? ServiceCenterRequested;
    internal event EventHandler? StartupSettingsRequested;
    internal Func<LocalServiceCommand, Task>? LocalServiceCommandHandler { get; set; }
    private bool _localServiceOperation;
    private bool _enabledBeforeServiceOperation;
    private bool _desktopPollingBeforeServiceOperation;

    private void ServiceCenterButton_Click(object sender, RoutedEventArgs e) =>
        ServiceCenterRequested?.Invoke(this, EventArgs.Empty);

    private Task StartLocalServiceAsync() => RunLocalServiceCommandAsync(LocalServiceCommand.Start);
    private Task StopLocalServiceAsync() => RunLocalServiceCommandAsync(LocalServiceCommand.Stop);

    private async Task RunLocalServiceCommandAsync(LocalServiceCommand command)
    {
        if (!_settings.ActiveConnection.IsLocal)
        {
            StatusText.Text = "Use Service Center to manage this computer's local service; remote workspaces are unaffected.";
            return;
        }
        if (LocalServiceCommandHandler is { } handler) await handler(command);
        else FooterText.Text = "Service controls are unavailable in this isolated Reader window.";
    }

    internal async Task<bool> PrepareLocalServiceOperationAsync()
    {
        if (!_settings.ActiveConnection.IsLocal || _closed) return true;
        if (_localServiceOperation || _documentLoadLock.CurrentCount == 0 ||
            _clipboardPromptOpen ||
            OwnedWindows.Cast<Window>().Any(window => window != _compactController && window.IsVisible))
        {
            FooterText.Text = "Finish the open Reader operation before stopping the local service.";
            return false;
        }
        _localServiceOperation = true;
        _enabledBeforeServiceOperation = IsEnabled;
        _desktopPollingBeforeServiceOperation = _desktopOpenTimer.IsEnabled;
        _desktopOpenTimer.Stop();
        IsEnabled = false;
        if (_compactController is not null) _compactController.IsEnabled = false;
        await StopUnifiedPlaybackAsync();
        return true;
    }

    internal void EndLocalServiceOperation()
    {
        if (!_localServiceOperation) return;
        _localServiceOperation = false;
        if (!_closed)
        {
            IsEnabled = _enabledBeforeServiceOperation;
            if (_compactController is not null) _compactController.IsEnabled = true;
            if (_desktopPollingBeforeServiceOperation) _desktopOpenTimer.Start();
        }
    }

    internal async Task RefreshAfterLocalServiceCommandAsync(ServiceDashboard dashboard)
    {
        if (_closed || !_settings.ActiveConnection.IsLocal || _smokeTest) return;
        if (dashboard.State == LocalServiceState.Stopped)
        {
            _desktopPollingBeforeServiceOperation = false;
            _desktopOpenTimer.Stop();
        }
        if (_editor?.HasUnsavedChanges == true || _documentLoadLock.CurrentCount == 0 || _clipboardPromptOpen)
        {
            // A connection/library refresh can rebuild the visible document or
            // relock privacy folders. Keep the draft until its normal save flow.
            ServiceStatusText.Text = $"Service: {dashboard.State.ToString().ToLowerInvariant()}";
            FooterText.Text = "Local service updated. Your unsaved text is kept; save it before refreshing the library.";
            return;
        }
        await RefreshConnectionAsync();
    }

    private async Task RefreshConnectionAsync(bool rebuildClient = false)
    {
        var connection = _settings.ActiveConnection;
        SetBusy(true, connection.IsLocal
            ? "Checking the local service…"
            : $"Connecting to {connection.Name}…");
        try
        {
            var clientWasRebuilt = rebuildClient || _client is null;
            if (clientWasRebuilt)
            {
                RebuildClient();
            }
            var coordinator = new OnboardingCoordinator(GetClient());
            _onboarding = await coordinator.CheckAsync();
            if (_onboarding.State == ConnectionState.ServiceUnavailable)
            {
                _privacySessions?.Clear();
            }
            var preserveConnectedData =
                _onboarding.State == ConnectionState.RateLimited && !clientWasRebuilt;
            if (preserveConnectedData)
            {
                _onboarding = _onboarding with
                {
                    Message = "The Reader service is busy. Current library and voice selection are kept; retry in about a minute.",
                };
            }
            else
            {
                UpdateVoiceOptions(_onboarding.Voices);
            }
            ShowOnboarding(_onboarding);
            if (_onboarding.State is ConnectionState.Ready or ConnectionState.BackendDegraded)
            {
                await RefreshHighlighterConfigurationAsync();
                await RefreshLibraryAsync();
                if (_settings.ActiveConnection.IsLocal)
                {
                    _desktopOpenTimer.Start();
                    await CheckDesktopOpenRequestAsync();
                }
                else
                {
                    _desktopOpenTimer.Stop();
                }
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
        if (_closed || _localServiceOperation || !_desktopOpenLock.Wait(0))
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
        CancelFindWork(clearHighlights: true);
        StopEphemeralAsync(clearReplay: true).GetAwaiter().GetResult();
        _ephemeralAudio?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _playback?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _playback = null;
        _playbackPerformance?.Dispose();
        _httpClient?.Dispose();
        _synthesisHttpClient?.Dispose();
        if (_privacySessions is not null)
        {
            _privacySessions.SessionsChanged -= PrivacySessions_SessionsChanged;
            _privacySessions.Dispose();
        }
        ClearDocumentDisplay();
        var connection = _settings.ActiveConnection;
        PinnedServerCertificateValidator? certificateValidator = null;
        ITokenProvider tokenProvider;
        if (connection.IsLocal)
        {
            _httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
            _synthesisHttpClient = new HttpClient { Timeout = TimeSpan.FromMinutes(2) };
            tokenProvider = new FileTokenProvider(_settings.EffectiveTokenSource.Path);
        }
        else
        {
            certificateValidator = new PinnedServerCertificateValidator(
                connection.ServerSpkiPin ?? throw new ReaderClientConfigurationException(
                    "The remote workspace has no server identity pin."));
            _httpClient = new HttpClient(certificateValidator.CreateHttpClientHandler())
            {
                Timeout = TimeSpan.FromSeconds(10),
            };
            _synthesisHttpClient = new HttpClient(certificateValidator.CreateHttpClientHandler())
            {
                Timeout = TimeSpan.FromMinutes(2),
            };
            tokenProvider = new ProtectedCredentialTokenProvider(
                new DpapiCredentialStore(),
                connection.CredentialId);
        }
        _privacySessions = new ReaderPrivacySessionStore();
        _privacySessions.SessionsChanged += PrivacySessions_SessionsChanged;
        _client = new ReaderServiceClient(
            _httpClient,
            connection.ServiceBaseUrl,
            tokenProvider,
            _privacySessions,
            allowRemote: !connection.IsLocal);
        _synthesisClient = new ReaderServiceClient(
            _synthesisHttpClient,
            connection.ServiceBaseUrl,
            tokenProvider,
            _privacySessions,
            allowRemote: !connection.IsLocal);
        _library = new LibraryPager(_client);
        _library.SetClosedFolders(FolderVisibility.ClosedFolderIds(_settings));
        _readingWindow = new ReadingWindowPager(_client);
        _findLoader = new ArticleFindDocumentLoader(_client);
        _findDocument = null;
        _highlighterConfiguration = null;
        ClearWordHighlights();
        _editor = new DocumentEditor(_client);
        _clipboardCapture = new ClipboardDocumentCapture(_client);
        _ephemeralAudio = new WasapiAudioOutput();
        _playbackPerformance = new JsonlPlaybackPerformanceSink();
        _playback = new ReaderPlaybackCoordinator(
            _client,
            new ReaderStreamClient(
                connection.ServiceBaseUrl,
                tokenProvider,
                _privacySessions,
                certificateValidator),
            new WasapiAudioOutput(),
            _playbackPerformance);
        _playback.StateChanged += Playback_StateChanged;
        _playback.HighlightChanged += Playback_HighlightChanged;
        _playback.RuleWarning += Playback_RuleWarning;
        DocumentsGrid.ItemsSource = _library.Documents;
        UpdatePlaybackControls();
    }

    private void OpenPlaybackLogsButton_Click(object sender, RoutedEventArgs e)
    {
        _ = sender;
        _ = e;
        try
        {
            Directory.CreateDirectory(DesktopPaths.PlaybackLogDirectory);
            Process.Start(new ProcessStartInfo
            {
                FileName = DesktopPaths.PlaybackLogDirectory,
                UseShellExecute = true,
            });
            FooterText.Text = "Opened the privacy-safe playback diagnostics folder.";
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or InvalidOperationException)
        {
            FooterText.Text = $"Playback logs could not be opened: {exception.Message}";
        }
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
        ActionButton.Content = !_settings.ActiveConnection.IsLocal &&
            result.Action is SuggestedAction.StartService or SuggestedAction.ChooseTokenFile
            ? "Retry"
            : result.Action switch
            {
                SuggestedAction.StartService => "Start service",
                SuggestedAction.ChooseTokenFile => "Choose token file",
                SuggestedAction.CheckVoiceModels => "Voice setup help",
                SuggestedAction.EnableReader => "Reader setup help",
                _ => "Retry",
            };
        var serviceUnavailable = result.State == ConnectionState.ServiceUnavailable;
        var localConnection = _settings.ActiveConnection.IsLocal;
        ServiceStatusText.Text = serviceUnavailable
            ? localConnection ? "Service: stopped" : "Remote: offline"
            : result.State is ConnectionState.NotChecked or ConnectionState.Checking
                ? localConnection ? "Service: checking" : "Remote: connecting"
                : localConnection ? "Service: running" : "Remote: connected";
        ServiceStatusDot.Fill = serviceUnavailable
            ? new SolidColorBrush(Color.FromRgb(213, 83, 83))
            : result.State is ConnectionState.NotChecked or ConnectionState.Checking
                ? new SolidColorBrush(Color.FromRgb(224, 165, 43))
                : new SolidColorBrush(Color.FromRgb(52, 199, 138));
        StartServiceButton.IsEnabled = localConnection && serviceUnavailable;
        StopServiceButton.IsEnabled = localConnection &&
            (!serviceUnavailable || ScheduledServiceController.OwnsRunningService);
        WorkspaceSubtitleText.Text = _settings.ActiveConnection.IsLocal
            ? "Local workspace · offline capable"
            : $"Remote workspace · {_settings.ActiveConnection.Name}";
        FooterText.Text = result.State.ToString();
    }

    private async void ActionButton_Click(object sender, RoutedEventArgs e)
    {
        switch (_onboarding.Action)
        {
            case SuggestedAction.StartService:
                if (_settings.ActiveConnection.IsLocal)
                {
                    await StartLocalServiceAsync();
                }
                else
                {
                    await RefreshConnectionAsync();
                }
                break;
            case SuggestedAction.ChooseTokenFile:
                if (_settings.ActiveConnection.IsLocal)
                {
                    BrowseForToken();
                }
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
            var activeProfileId = (WorkspaceComboBox.SelectedItem as ConnectionChoice)?.Id ?? "local";
            var reconnectRequired = DesktopConnectionPolicy.RequiresReconnect(
                _settings,
                normalizedUrl,
                tokenPath,
                activeProfileId);
            _settings = _settings with
            {
                ServiceBaseUrl = normalizedUrl,
                TokenSource = new TokenSourceSettings("file", tokenPath),
                ActiveConnectionProfileId = activeProfileId,
                PreferredVoiceId = SelectedVoiceId() ?? _settings.PreferredVoiceId,
            };
            await _settingsStore.SaveAsync(_settings);
            RefreshWorkspaceChoices();
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

    private async void OptionsButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OptionsDialog(_settings) { Owner = this };
        if (dialog.ShowDialog() != true)
        {
            return;
        }
        try
        {
            var previous = _settings;
            await _settingsStore.SaveAsync(dialog.Settings);
            _settings = dialog.Settings;
            ApplyRuntimeOptions(previous);
            FooterText.Text = "Options saved.";
            if (dialog.OpenStartupRequested) StartupSettingsRequested?.Invoke(this, EventArgs.Empty);
        }
        catch (Exception exception) when (
            exception is ReaderClientConfigurationException or IOException or UnauthorizedAccessException)
        {
            StatusText.Text = $"Options were not saved: {exception.Message}";
        }
    }

    private void ApplyRuntimeOptions(DesktopSettings previous)
    {
        if (_audioInterruptionMonitor is not null)
        {
            _audioInterruptionMonitor.Enabled = _settings.EffectivePauseForCallsAndAlarms;
        }
        if (!_settings.EffectivePauseForCallsAndAlarms)
        {
            _audioInterruptionActive = false;
            CancelAutomaticInterruptionResume();
        }
        if (previous.ClipboardMonitoringEnabled != _settings.ClipboardMonitoringEnabled)
        {
            ApplyClipboardMonitoringRuntime(_settings.ClipboardMonitoringEnabled);
        }
        if (_windowSource is not null)
        {
            RegisterHotkeys(new WindowInteropHelper(this).Handle);
        }
        _trayIcon?.SetClipboardMonitoring(_settings.ClipboardMonitoringEnabled);
        UpdateClipboardStatus();
    }

    private void RefreshWorkspaceChoices()
    {
        _updatingWorkspaceChoices = true;
        try
        {
            WorkspaceComboBox.Items.Clear();
            WorkspaceComboBox.Items.Add(new ConnectionChoice("local", "Local", true));
            foreach (var profile in _settings.EffectiveRemoteConnectionProfiles)
            {
                WorkspaceComboBox.Items.Add(new ConnectionChoice(profile.Id, profile.Name, false));
            }
            WorkspaceComboBox.SelectedItem = WorkspaceComboBox.Items
                .OfType<ConnectionChoice>()
                .FirstOrDefault(choice => string.Equals(
                    choice.Id,
                    _settings.ActiveConnectionProfileId,
                    StringComparison.Ordinal)) ?? WorkspaceComboBox.Items[0];
            UpdateWorkspaceControls();
        }
        finally
        {
            _updatingWorkspaceChoices = false;
        }
    }

    private void WorkspaceComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_updatingWorkspaceChoices)
        {
            UpdateWorkspaceControls();
            FooterText.Text = "Choose Save to switch workspaces.";
        }
    }

    private void UpdateWorkspaceControls()
    {
        var local = (WorkspaceComboBox.SelectedItem as ConnectionChoice)?.IsLocal != false;
        ServiceUrlTextBox.IsEnabled = local;
        TokenPathTextBox.IsEnabled = local;
        BrowseTokenButton.IsEnabled = local;
    }

    private async void RemoteAccessButton_Click(object sender, RoutedEventArgs e)
    {
        var beforeProfile = _settings.ActiveConnectionProfileId;
        var dialog = new RemoteAccessDialog(_settingsStore, _settings) { Owner = this };
        dialog.ShowDialog();
        _settings = dialog.Settings;
        ServiceUrlTextBox.Text = _settings.ServiceBaseUrl;
        TokenPathTextBox.Text = _settings.EffectiveTokenSource.Path;
        RefreshWorkspaceChoices();
        if (!string.Equals(beforeProfile, _settings.ActiveConnectionProfileId, StringComparison.Ordinal))
        {
            await RefreshConnectionAsync(rebuildClient: true);
        }
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

    private async Task SetClipboardMonitoringAsync(bool enabled)
    {
        _settings = _settings with { ClipboardMonitoringEnabled = enabled };
        ApplyClipboardMonitoringRuntime(enabled);
        try
        {
            await _settingsStore.SaveAsync(_settings);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            FooterText.Text = $"Clipboard monitoring preference was not saved: {exception.Message}";
        }
    }

    private void ApplyClipboardMonitoringRuntime(bool enabled)
    {
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
    }

    private void UpdateClipboardStatus()
    {
        var snoozed = _clipboardPromptPolicy.IsSnoozed(
            _settings.ClipboardPromptSnoozedUntilUtc);
        var state = !_settings.ClipboardMonitoringEnabled
            ? "Off"
            : _clipboardListener?.IsRegistered == false
                ? "Unavailable"
                : "On";
        var privacy = _settings.PrivacyMode ? " · Privacy" : string.Empty;
        var snooze = snoozed
            ? $" · Paused until {_settings.ClipboardPromptSnoozedUntilUtc!.Value.ToLocalTime():t}"
            : string.Empty;
        ClipboardStatusText.Text = $"Clipboard prompt: {state}{privacy}{snooze}";
        ResumeClipboardPromptsButton.Visibility = snoozed
            ? Visibility.Visible
            : Visibility.Collapsed;
        if (snoozed && !_clipboardSnoozeTimer.IsEnabled)
        {
            _clipboardSnoozeTimer.Start();
        }
        else if (!snoozed)
        {
            _clipboardSnoozeTimer.Stop();
        }
    }

    private async void ClipboardSnoozeTimer_Tick(object? sender, EventArgs e)
    {
        if (_clipboardPromptPolicy.IsSnoozed(_settings.ClipboardPromptSnoozedUntilUtc))
        {
            return;
        }
        _clipboardSnoozeTimer.Stop();
        if (_settings.ClipboardPromptSnoozedUntilUtc is null)
        {
            return;
        }
        _settings = _settings with { ClipboardPromptSnoozedUntilUtc = null };
        UpdateClipboardStatus();
        await SaveClipboardPromptMetadataAsync("Clipboard prompts resumed.");
    }

    private async void ResumeClipboardPromptsButton_Click(object sender, RoutedEventArgs e)
    {
        _settings = _settings with { ClipboardPromptSnoozedUntilUtc = null };
        UpdateClipboardStatus();
        await SaveClipboardPromptMetadataAsync("Clipboard prompts resumed.");
    }

    private async Task SaveClipboardPromptMetadataAsync(string successMessage)
    {
        try
        {
            await _settingsStore.SaveAsync(_settings);
            FooterText.Text = successMessage;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            FooterText.Text = $"Clipboard prompt preference was not saved: {exception.Message}";
        }
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
            _clipboardPromptPolicy.IsSnoozed(_settings.ClipboardPromptSnoozedUntilUtc) ||
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

        var promptDecision = _clipboardPromptPolicy.Evaluate(
            text,
            _settings.ClipboardPromptMinimumCharacters,
            _settings.ClipboardPromptSnoozedUntilUtc);
        if (!promptDecision.ShouldPrompt)
        {
            if (promptDecision.SuppressionReason == ClipboardPromptSuppressionReason.BelowMinimumLength)
            {
                FooterText.Text =
                    $"Clipboard prompt ignored ({promptDecision.TrimmedCharacterCount:N0} characters; minimum is {_settings.ClipboardPromptMinimumCharacters + 1:N0}).";
            }
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
            case ClipboardCaptureAction.SnoozeFiveMinutes:
                _settings = _settings with
                {
                    ClipboardPromptSnoozedUntilUtc = _clipboardPromptPolicy.SnoozeUntilUtc(),
                };
                UpdateClipboardStatus();
                await SaveClipboardPromptMetadataAsync(
                    $"Clipboard prompts paused until {_settings.ClipboardPromptSnoozedUntilUtc.Value.ToLocalTime():t}.");
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

        string? refreshFailure = null;
        var previousSelectionSuppression = _suppressDocumentSelectionLoad;
        _suppressDocumentSelectionLoad = result.OpenDocument || previousSelectionSuppression;
        try
        {
            await _library.RefreshAsync(
                SearchTextBox.Text.Trim(),
                SelectedLibraryState(),
                SelectedLibraryFolderId());
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            refreshFailure = exception.Message;
        }
        finally
        {
            _library.ReplaceDocument(result.Document);
            LoadMoreButton.IsEnabled = _library.HasMore;
            if (result.OpenDocument)
            {
                DocumentsGrid.SelectedItem = _library.Documents.FirstOrDefault(item =>
                    string.Equals(item.Id, result.Document.Id, StringComparison.Ordinal));
            }
            _suppressDocumentSelectionLoad = previousSelectionSuppression;
        }
        if (result.OpenDocument)
        {
            await LoadDocumentAsync(result.Document);
        }
        FooterText.Text = refreshFailure is null
            ? result.Message
            : $"{result.Message} Library refresh is delayed: {refreshFailure}";
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

    private void AudioInterruptionMonitor_Changed(
        object? sender,
        AudioInterruptionChangedEventArgs change)
    {
        if (_closed)
        {
            return;
        }
        Dispatcher.BeginInvoke(new Action(async () =>
        {
            await HandleAudioInterruptionAsync(change);
        }));
    }

    private async Task HandleAudioInterruptionAsync(AudioInterruptionChangedEventArgs change)
    {
        var lockAcquired = false;
        try
        {
            await _audioInterruptionLock.WaitAsync();
            lockAcquired = true;
            if (_closed || !_settings.EffectivePauseForCallsAndAlarms)
            {
                _audioInterruptionActive = false;
                CancelAutomaticInterruptionResume();
                return;
            }

            _audioInterruptionActive = change.IsActive;
            if (change.IsActive)
            {
                await PauseForAudioInterruptionAsync(change.Source ?? "an audio interruption");
            }
            else
            {
                await ResumeAfterAudioInterruptionAsync();
            }
        }
        catch (Exception exception)
        {
            CancelAutomaticInterruptionResume();
            if (!_closed)
            {
                FooterText.Text = $"Automatic interruption handling: {exception.Message}";
            }
        }
        finally
        {
            if (lockAcquired)
            {
                _audioInterruptionLock.Release();
            }
        }
    }

    private async Task PauseForAudioInterruptionAsync(string source)
    {
        if (_automaticPauseKind != AutomaticPauseKind.None)
        {
            _automaticPauseSource = source;
            return;
        }
        if (_ephemeralPlaying)
        {
            _automaticPauseKind = AutomaticPauseKind.Clipboard;
            _automaticPauseSource = source;
            await StopEphemeralAsync(clearReplay: false);
            if (_automaticPauseKind == AutomaticPauseKind.Clipboard)
            {
                SetEphemeralState($"Paused for {source}", playing: false);
            }
            return;
        }
        if (_playback?.IsActive == true)
        {
            _automaticPauseKind = AutomaticPauseKind.Document;
            _automaticPauseSource = source;
            await _playback.PauseAsync();
            if (_automaticPauseKind == AutomaticPauseKind.Document)
            {
                PlaybackStatusText.Text = $"Paused for {source}";
                FooterText.Text = $"Reading paused for {source}.";
                _trayIcon?.SetStatus("Paused for interruption");
                UpdateCompactController();
            }
        }
    }

    private async Task ResumeAfterAudioInterruptionAsync()
    {
        var pausedKind = _automaticPauseKind;
        var source = _automaticPauseSource ?? "the interruption";
        CancelAutomaticInterruptionResume();
        switch (pausedKind)
        {
            case AutomaticPauseKind.Clipboard when
                !_ephemeralPlaying && _ephemeralReplayText is string replay:
                await StartEphemeralPlaybackAsync(replay);
                if (_ephemeralPlaying)
                {
                    FooterText.Text = $"Resumed after {source}.";
                }
                break;
            case AutomaticPauseKind.Document when
                _playback?.State == ReaderPlaybackState.Paused && _editor?.Document is not null:
                await TogglePlaybackAsync();
                if (_playback.IsActive)
                {
                    FooterText.Text = $"Resumed after {source}.";
                }
                break;
        }
    }

    private bool PlaybackBlockedByAudioInterruption()
    {
        if (_localServiceOperation)
        {
            FooterText.Text = "Reading is waiting for the local service operation to finish.";
            return true;
        }
        if (!_settings.EffectivePauseForCallsAndAlarms || !_audioInterruptionActive)
        {
            return false;
        }
        FooterText.Text = "Reading is waiting for the current Teams call or Windows alarm to finish.";
        return true;
    }

    private void CancelAutomaticInterruptionResume()
    {
        _automaticPauseKind = AutomaticPauseKind.None;
        _automaticPauseSource = null;
    }

    private async Task StartEphemeralPlaybackAsync(string text)
    {
        if (PlaybackBlockedByAudioInterruption())
        {
            return;
        }
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
        if (PlaybackBlockedByAudioInterruption())
        {
            return;
        }
        CancelAutomaticInterruptionResume();
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
        CancelAutomaticInterruptionResume();
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

    private async void FolderFilterComboBox_SelectionChanged(
        object sender,
        SelectionChangedEventArgs e)
    {
        if (_refreshingFolders)
        {
            return;
        }
        if (FolderFilterComboBox.SelectedItem is FolderFilterItem
            {
                PrivacyLocked: true,
                PrivacyUnlocked: false,
            } lockedFolder)
        {
            await UnlockFolderFilterAsync(lockedFolder);
        }
        else
        {
            await RefreshLibraryAsync();
        }
    }

    private string? SelectedLibraryState()
    {
        var value = (LibraryStateComboBox.SelectedItem as ComboBoxItem)?.Tag as string;
        return string.IsNullOrWhiteSpace(value) ? null : value;
    }

    private string? SelectedLibraryFolderId() =>
        (FolderFilterComboBox.SelectedItem as FolderFilterItem)?.Id;

    private async Task RefreshFoldersAsync()
    {
        var selectedId = SelectedLibraryFolderId();
        _refreshingFolders = true;
        try
        {
            var page = await GetClient().GetFoldersAsync();
            _folderFilters.Clear();
            _folderFilters.Add(new FolderFilterItem(null, "All articles", false, true));
            foreach (var folder in page.Folders.Where(folder => IsFolderOpen(folder.Id)))
            {
                _folderFilters.Add(
                    new FolderFilterItem(
                        folder.Id,
                        folder.PrivacyLocked && !folder.PrivacyUnlocked
                            ? "[Locked] Privacy locked folder"
                            : $"{folder.Name} ({folder.ArticleCount:N0})",
                        folder.PrivacyLocked,
                        folder.PrivacyUnlocked));
            }
            FolderFilterComboBox.SelectedItem = _folderFilters.FirstOrDefault(
                item => string.Equals(item.Id, selectedId, StringComparison.Ordinal));
            FolderFilterComboBox.SelectedItem ??= _folderFilters[0];
        }
        finally
        {
            _refreshingFolders = false;
        }
    }

    private async Task UnlockFolderFilterAsync(FolderFilterItem folder)
    {
        var dialog = new FolderPrivacyDialog(FolderPrivacyDialogMode.Unlock, folder.DisplayName)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() is not true)
        {
            _refreshingFolders = true;
            FolderFilterComboBox.SelectedItem = _folderFilters[0];
            _refreshingFolders = false;
            await RefreshLibraryAsync();
            return;
        }
        try
        {
            await GetClient().UnlockPrivacyLockAsync(
                folder.Id!,
                new ReaderPrivacyUnlockRequest(dialog.PrimarySecret));
            await RefreshFoldersAsync();
            FolderFilterComboBox.SelectedItem = _folderFilters.FirstOrDefault(
                item => string.Equals(item.Id, folder.Id, StringComparison.Ordinal));
            await RefreshLibraryAsync();
            FooterText.Text = "Privacy locked folder unlocked for 15 minutes.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Unlock folder: {exception.Message}";
            _refreshingFolders = true;
            FolderFilterComboBox.SelectedItem = _folderFilters[0];
            _refreshingFolders = false;
            await RefreshLibraryAsync();
        }
    }

    private void PrivacySessions_SessionsChanged(
        object? sender,
        ReaderPrivacySessionsChangedEventArgs e)
    {
        if (e.RemovedFolderIds.Count == 0 || _closed)
        {
            return;
        }
        _ = Dispatcher.InvokeAsync(async () =>
        {
            var currentFolderId = _editor?.Document?.FolderId;
            if (currentFolderId is not null && e.RemovedFolderIds.Contains(currentFolderId))
            {
                await StopUnifiedPlaybackAsync();
                DocumentsGrid.SelectedItem = null;
                ClearDocumentDisplay();
                FooterText.Text = "The Privacy lock session ended. The folder is hidden again.";
            }
            try
            {
                await RefreshFoldersAsync();
                await RefreshLibraryAsync();
            }
            catch (Exception exception) when (
                exception is ReaderApiException or ReaderServiceUnavailableException)
            {
                FooterText.Text = $"Privacy lock refresh: {exception.Message}";
            }
        });
    }

    private async void ImportButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "Import a document",
            Filter = "Reader documents (*.txt;*.md;*.markdown;*.html;*.htm;*.docx;*.epub)|*.txt;*.md;*.markdown;*.html;*.htm;*.docx;*.epub|All files (*.*)|*.*",
            Multiselect = true,
            CheckFileExists = true,
        };
        if (dialog.ShowDialog(this) == true)
        {
            if (dialog.FileNames.Length == 1)
            {
                await ShowImportDialogAsync(dialog.FileName);
            }
            else
            {
                await ShowBatchImportDialogAsync(dialog.FileNames);
            }
        }
    }

    private void MainWindow_DragOver(object sender, DragEventArgs e)
    {
        e.Effects = TryGetImportPaths(e.Data, out _)
            ? DragDropEffects.Copy
            : DragDropEffects.None;
        e.Handled = true;
    }

    private async void MainWindow_Drop(object sender, DragEventArgs e)
    {
        if (TryGetImportPaths(e.Data, out var paths))
        {
            if (paths.Length == 1)
            {
                await ShowImportDialogAsync(paths[0]);
            }
            else
            {
                await ShowBatchImportDialogAsync(paths);
            }
        }
        else
        {
            FooterText.Text =
                "Drop between 1 and 100 TXT, Markdown, HTML, DOCX, or EPUB files.";
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
        var dialog = new ImportPreviewDialog(
            GetClient(),
            filePath,
            SelectedLibraryFolderId())
        { Owner = this };
        if (dialog.ShowDialog() == true && dialog.ImportedDocument is ReaderDocument imported)
        {
            await RefreshLibraryAsync();
            DocumentsGrid.SelectedItem = _library?.Documents.FirstOrDefault(item => item.Id == imported.Id);
            FooterText.Text = $"Imported {imported.TotalBlocks:N0} block(s) to Inbox.";
        }
    }

    private async Task ShowBatchImportDialogAsync(IReadOnlyList<string> filePaths)
    {
        if (_onboarding.State is not (ConnectionState.Ready or ConnectionState.BackendDegraded))
        {
            FooterText.Text = "Connect to the local Reader service before importing.";
            return;
        }
        try
        {
            var folders = await GetClient().GetFoldersAsync();
            var dialog = new BatchImportDialog(
                GetClient(),
                filePaths,
                folders.Folders,
                SelectedLibraryFolderId())
            { Owner = this };
            _ = dialog.ShowDialog();
            if (dialog.ImportedDocuments.Count > 0)
            {
                await RefreshFoldersAsync();
                await RefreshLibraryAsync();
                var last = dialog.ImportedDocuments[^1];
                DocumentsGrid.SelectedItem = _library?.Documents.FirstOrDefault(
                    item => item.Id == last.Id);
                FooterText.Text = $"Imported {dialog.ImportedDocuments.Count:N0} article(s).";
            }
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Batch import: {exception.Message}";
        }
    }

    private static bool TryGetImportPaths(IDataObject data, out string[] paths)
    {
        paths = [];
        if (!data.GetDataPresent(DataFormats.FileDrop) ||
            data.GetData(DataFormats.FileDrop) is not string[] { Length: > 0 and <= 100 } files)
        {
            return false;
        }
        if (files.Any(file =>
            !File.Exists(file) ||
            Path.GetExtension(file).ToLowerInvariant() is not
                (".txt" or ".md" or ".markdown" or ".html" or ".htm" or ".docx" or ".epub")))
        {
            return false;
        }
        paths = files;
        return true;
    }

    private async Task RefreshLibraryAsync()
    {
        if (_library is null)
        {
            return;
        }

        try
        {
            if (_folderFilters.Count == 1)
            {
                await RefreshFoldersAsync();
            }
            await _library.RefreshAsync(
                SearchTextBox.Text.Trim(),
                SelectedLibraryState(),
                SelectedLibraryFolderId());
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
        MoveArticlesButton.IsEnabled = DocumentsGrid.SelectedItems.Count > 0 &&
            _playback?.State is not (ReaderPlaybackState.Playing or ReaderPlaybackState.Paused);
        if (_suppressDocumentSelectionLoad)
        {
            return;
        }
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
                ? ReaderDocumentVersions.PreferNewest(current, document)
                : document;
            await LoadDocumentAsync(selectedDocument);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Document: {exception.Message}";
        }
    }

    private async void ManageFoldersButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new FolderManagerDialog(
            GetClient(),
            IsFolderOpen,
            SetFolderOpenAsync,
            allowPrivacyAdministration: _settings.ActiveConnection.IsLocal)
        {
            Owner = this,
        };
        _ = dialog.ShowDialog();
        if (dialog.Changed)
        {
            await RefreshFoldersAsync();
            await RefreshLibraryAsync();
        }
    }

    private string? _closingFolderId;

    private bool IsFolderOpen(string? folderId) =>
        (folderId is null || folderId != _closingFolderId) && FolderVisibility.IsOpen(_settings, folderId);

    private async Task<bool> SetFolderOpenAsync(ReaderFolder folder, bool isOpen)
    {
        var closesCurrent = !isOpen && _editor?.Document?.FolderId == folder.Id;
        if (_documentReloadInProgress || (closesCurrent &&
            (_editor?.HasUnsavedChanges == true || _playback?.IsActive == true ||
             _playback?.State is ReaderPlaybackState.Paused)))
        {
            return false;
        }
        _closingFolderId = isOpen ? null : folder.Id;
        try
        {
            var updated = FolderVisibility.SetOpen(_settings, folder.Id, isOpen);
            await _settingsStore.SaveAsync(updated);
            _settings = updated;
            if (!isOpen && _editor?.Document?.FolderId == folder.Id)
            {
                DocumentsGrid.SelectedItem = null;
                ClearDocumentDisplay();
            }
            _library?.SetClosedFolders(FolderVisibility.ClosedFolderIds(_settings));
            return true;
        }
        finally
        {
            _closingFolderId = null;
        }
    }

    private async void MoveArticlesButton_Click(object sender, RoutedEventArgs e)
    {
        var documents = DocumentsGrid.SelectedItems.Cast<ReaderDocument>().ToArray();
        if (documents.Length == 0)
        {
            return;
        }
        try
        {
            var folders = await GetClient().GetFoldersAsync();
            var dialog = new MoveArticlesDialog(folders.Folders, documents.Length) { Owner = this };
            if (dialog.ShowDialog() != true)
            {
                return;
            }
            var response = await GetClient().MoveDocumentsAsync(
                new MoveDocumentsRequest(
                    dialog.TargetFolderId,
                    documents.Select(
                        document => new FolderDocumentVersion(document.Id, document.RowVersion)).ToArray()));
            await RefreshFoldersAsync();
            await RefreshLibraryAsync();
            FooterText.Text = $"Moved {response.Documents.Count:N0} article(s).";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            FooterText.Text = $"Move articles: {exception.Message}";
        }
    }

    private bool _documentReloadInProgress;

    private async Task LoadDocumentAsync(ReaderDocument document, ReaderDocument? expectedDisplayedDocument = null)
    {
        if (!IsFolderOpen(document.FolderId))
        {
            FooterText.Text = "This folder is closed. Check Open in Article folders to show its articles.";
            return;
        }
        if (_editor is null)
        {
            return;
        }
        var loadGeneration = ++_documentLoadGeneration;
        for (var attempt = 0; attempt < 2; attempt++)
        {
            var retryRateLimit = false;
            await _documentLoadLock.WaitAsync();
            try
            {
                if (_closed || loadGeneration != _documentLoadGeneration || !IsFolderOpen(document.FolderId))
                {
                    return;
                }
                if (expectedDisplayedDocument is not null && !ReaderDocumentVersions.CanApplyPlaybackRefresh(
                    _editor.Document, expectedDisplayedDocument, _editor.HasUnsavedChanges))
                {
                    FooterText.Text = "The local article changed while refreshing. Your edit has been kept.";
                    return;
                }
                _documentReloadInProgress = true;
                UpdateEditorButtons();
                await LoadDocumentCoreAsync(document);
                return;
            }
            catch (ReaderApiException exception) when (
                exception.ErrorType == "rate_limited" && attempt == 0)
            {
                retryRateLimit = true;
            }
            catch (Exception exception) when (
                exception is ReaderApiException or ReaderServiceUnavailableException)
            {
                FooterText.Text = $"Document: {exception.Message}";
                return;
            }
            finally
            {
                _documentReloadInProgress = false;
                UpdateEditorButtons();
                _documentLoadLock.Release();
            }
            if (retryRateLimit)
            {
                FooterText.Text =
                    "The local service is temporarily busy. The document is not locked; Reader will retry automatically in one minute.";
                await Task.Delay(DocumentRateLimitRetryDelay);
                if (_closed || loadGeneration != _documentLoadGeneration)
                {
                    return;
                }
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
            CancelFindWork(clearHighlights: true);
            _findDocument = null;
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
            ScheduleFindRefresh();
            await RefreshWordHighlightsAsync();
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
        var current = await GetClient().GetDocumentAsync(document.Id);
        if (!ReaderDocumentVersions.AreSame(document, current))
        {
            throw new ReaderApiException("reader_revision_conflict",
                "The article changed while loading. Select it again to load its current revision.", 409);
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
        if (PlaybackBlockedByAudioInterruption())
        {
            return;
        }
        CancelAutomaticInterruptionResume();
        try
        {
            var document = await GetClient().GetDocumentAsync(documentId);
            await LoadDocumentAsync(document);
            if (_editor?.Document?.Id != document.Id || !IsFolderOpen(document.FolderId))
            {
                return;
            }
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
        CancelFindWork(clearHighlights: true);
        _findDocument = null;
        ClearWordHighlights();
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
            if (_editor?.Document?.Id != document.Id || !IsFolderOpen(document.FolderId))
            {
                return;
            }
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
        if (!_updatingEditor)
        {
            ScheduleFindRefresh();
        }
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
            await RefreshWordHighlightsAsync();
            UpdateTextCursorFromContinuousEditor();
            UpdatePlaybackControls();
        }
    }

    private async void RevertEditButton_Click(object sender, RoutedEventArgs e)
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
        await RefreshWordHighlightsAsync();
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
            await RefreshWordHighlightsAsync();
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
            await _library.RefreshAsync(
                SearchTextBox.Text.Trim(),
                SelectedLibraryState(),
                SelectedLibraryFolderId());
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
        var playbackActive = _playback?.IsActive == true || _documentReloadInProgress;
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
        if (PlaybackBlockedByAudioInterruption())
        {
            return;
        }
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
            var (document, _) = await RefreshDocumentForPlaybackAsync(_editor.Document);
            if (document is null)
            {
                return;
            }
            await StopEphemeralAsync(clearReplay: true);
            if (!IsFolderOpen(document.FolderId) || _editor?.Document?.Id != document.Id)
            {
                return;
            }
            await _playback.PlayAsync(document, voice: SelectedVoiceId());
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
        if (PlaybackBlockedByAudioInterruption())
        {
            return;
        }
        CancelAutomaticInterruptionResume();
        if (_playback is null || _editor?.Document is not ReaderDocument document)
        {
            return;
        }
        if (_editor.HasUnsavedChanges)
        {
            FooterText.Text = "Save or revert the local edit before playback.";
            return;
        }

        try
        {
            var (refreshedDocument, reloaded) = await RefreshDocumentForPlaybackAsync(document);
            if (refreshedDocument is null)
            {
                return;
            }
            if (reloaded)
            {
                FooterText.Text =
                    "The article changed and was refreshed. Place the cursor again, then choose Start at cursor.";
                return;
            }

            UpdateTextCursorFromContinuousEditor();
            if (_textCursor is not ReaderCursor cursor)
            {
                FooterText.Text = "Place the text cursor in an editable article first.";
                return;
            }

            await StopEphemeralAsync(clearReplay: true);
            if (!IsFolderOpen(refreshedDocument.FolderId) || _editor?.Document?.Id != refreshedDocument.Id)
            {
                return;
            }
            await _playback.PlayAsync(
                refreshedDocument,
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

    private async Task<(ReaderDocument? Document, bool Reloaded)>
        RefreshDocumentForPlaybackAsync(ReaderDocument displayedDocument)
    {
        var latestDocument = await GetClient().GetDocumentAsync(displayedDocument.Id);
        if (!IsFolderOpen(latestDocument.FolderId))
        {
            FooterText.Text = "This folder is closed. Check Open in Article folders before playback.";
            return (null, false);
        }
        if (!ReaderDocumentVersions.CanApplyPlaybackRefresh(
            _editor?.Document, displayedDocument, _editor?.HasUnsavedChanges == true))
        {
            FooterText.Text = "The local article changed while checking playback. Your edit has been kept.";
            return (null, false);
        }
        if (ReaderDocumentVersions.AreSame(displayedDocument, latestDocument))
        {
            return (displayedDocument, false);
        }

        await LoadDocumentAsync(latestDocument, expectedDisplayedDocument: displayedDocument);
        if (_editor?.Document is ReaderDocument loadedDocument &&
            ReaderDocumentVersions.AreSame(loadedDocument, latestDocument))
        {
            return (loadedDocument, true);
        }
        return (null, true);
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
        ApplyWordHighlightsToReadingBlocks();
        ApplyCurrentFindToReadingBlocks();
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
                _continuousHighlightAdorner?.Clear();
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

    private async void WordHighlighterButton_Click(object sender, RoutedEventArgs e)
    {
        if (_highlighterConfiguration is null)
        {
            await RefreshHighlighterConfigurationAsync();
        }
        if (_highlighterConfiguration is not ReaderHighlighterConfiguration configuration)
        {
            FooterText.Text = "Connect to the Reader service before editing Word Highlighter terms.";
            return;
        }
        await RefreshWordHighlightsAsync();
        var dialog = new WordHighlighterDialog(configuration, _wordHighlightResult.Counts)
        {
            Owner = this,
        };
        dialog.JumpRequested += async (_, termId) => await HandleWordHighlightJumpAsync(termId);
        if (dialog.ShowDialog() != true)
        {
            return;
        }
        try
        {
            _highlighterConfiguration = await GetClient().ReplaceHighlighterAsync(
                new ReplaceHighlighterRequest(configuration.RowVersion, dialog.SavedTerms));
            await RefreshWordHighlightsAsync();
            FooterText.Text =
                $"Word Highlighter saved {_highlighterConfiguration.Terms.Count:N0} global term(s).";
        }
        catch (ReaderApiException exception) when (exception.StatusCode == 409)
        {
            await RefreshHighlighterConfigurationAsync();
            FooterText.Text =
                "The Word Highlighter list changed in another Reader. Reopen it to review the current list.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Word Highlighter: {exception.Message}";
        }
    }

    private async Task RefreshHighlighterConfigurationAsync()
    {
        try
        {
            _highlighterConfiguration = await GetClient().GetHighlighterAsync();
            WordHighlighterButton.IsEnabled = true;
            if (_editor?.Document is not null)
            {
                await RefreshWordHighlightsAsync();
            }
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            _highlighterConfiguration = null;
            WordHighlighterButton.IsEnabled = false;
            ClearWordHighlights();
            FooterText.Text = $"Word Highlighter unavailable: {exception.Message}";
        }
    }

    private async Task RefreshWordHighlightsAsync()
    {
        var generation = ++_wordHighlightGeneration;
        if (_editor?.Document is not ReaderDocument document ||
            _highlighterConfiguration is not ReaderHighlighterConfiguration configuration)
        {
            ClearWordHighlights();
            return;
        }

        try
        {
            ArticleFindDocument? highlightDocument = null;
            string text;
            if (_continuousDocument is not null)
            {
                text = EditorTextBox.Text;
            }
            else
            {
                if (_findLoader is null)
                {
                    return;
                }
                highlightDocument = await _findLoader.LoadAsync(document);
                text = highlightDocument.Text;
            }

            var result = await Task.Run(() =>
                WordHighlighterEngine.Search(text, configuration.Terms));
            var structuredHighlights = highlightDocument is null
                ? new Dictionary<int, IReadOnlyList<ReaderTextHighlight>>()
                : await Task.Run(() => BuildStructuredWordHighlights(
                    highlightDocument,
                    result.Matches));
            if (generation != _wordHighlightGeneration ||
                _editor?.Document is not ReaderDocument current ||
                !string.Equals(current.Id, document.Id, StringComparison.Ordinal) ||
                current.ContentRevision != document.ContentRevision ||
                _highlighterConfiguration?.RowVersion != configuration.RowVersion)
            {
                return;
            }

            _wordHighlightDocument = highlightDocument;
            _wordHighlightResult = result;
            _wordHighlightsByBlockOrdinal = structuredHighlights;
            _wordHighlightMatchIndex = -1;
            ApplyWordHighlights();
            if (result.TimedOut)
            {
                FooterText.Text = "Word Highlighter took too long on this article and was stopped.";
            }
            else if (result.Truncated)
            {
                FooterText.Text =
                    $"Word Highlighter display is limited to {WordHighlighterEngine.MaxMatches:N0} matches for this article.";
            }
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            if (generation == _wordHighlightGeneration)
            {
                ClearWordHighlights();
                FooterText.Text = $"Word Highlighter: {exception.Message}";
            }
        }
    }

    private void ApplyWordHighlights()
    {
        if (_continuousDocument is not null)
        {
            _continuousHighlightAdorner?.ShowWords(
                _wordHighlightResult.Matches
                    .Select(match => new ReaderTextHighlight(
                        match.Start,
                        match.Length,
                        match.Color,
                        match.TermId))
                    .ToArray());
            foreach (var block in _readingBlocks)
            {
                block.WordHighlights = [];
            }
            return;
        }
        _continuousHighlightAdorner?.ShowWords([]);
        ApplyWordHighlightsToReadingBlocks();
    }

    private void ApplyWordHighlightsToReadingBlocks()
    {
        foreach (var block in _readingBlocks)
        {
            block.WordHighlights = [];
        }
        if (_wordHighlightsByBlockOrdinal.Count == 0)
        {
            return;
        }
        foreach (var block in _readingBlocks)
        {
            block.WordHighlights = _wordHighlightsByBlockOrdinal.GetValueOrDefault(block.Ordinal) ?? [];
        }
    }

    private static IReadOnlyDictionary<int, IReadOnlyList<ReaderTextHighlight>>
        BuildStructuredWordHighlights(
            ArticleFindDocument document,
            IReadOnlyList<WordHighlightMatch> matches)
    {
        var blocks = document.Blocks.ToDictionary(block => block.Ordinal);
        var byOrdinal = new Dictionary<int, List<ReaderTextHighlight>>();
        foreach (var match in matches)
        {
            var location = document.Locate(new ArticleFindMatch(match.Start, match.Length));
            for (var ordinal = location.StartCursor.BlockOrdinal;
                 ordinal <= location.EndCursor.BlockOrdinal;
                 ordinal++)
            {
                if (!blocks.TryGetValue(ordinal, out var block))
                {
                    continue;
                }
                var start = ordinal == location.StartCursor.BlockOrdinal
                    ? location.StartCursor.CharacterOffset
                    : 0;
                var end = ordinal == location.EndCursor.BlockOrdinal
                    ? location.EndCursor.CharacterOffset
                    : block.Text.Length;
                start = Math.Clamp(start, 0, block.Text.Length);
                end = Math.Clamp(end, start, block.Text.Length);
                if (end <= start)
                {
                    continue;
                }
                if (!byOrdinal.TryGetValue(ordinal, out var ranges))
                {
                    ranges = [];
                    byOrdinal[ordinal] = ranges;
                }
                ranges.Add(new ReaderTextHighlight(
                    start,
                    end - start,
                    match.Color,
                    match.TermId));
            }
        }
        return byOrdinal.ToDictionary(
            item => item.Key,
            item => (IReadOnlyList<ReaderTextHighlight>)item.Value.ToArray());
    }

    private async Task JumpToNextWordHighlightAsync(string termId)
    {
        _wordHighlightMatchIndex = WordHighlighterNavigator.Move(
            _wordHighlightResult.Matches,
            termId,
            _wordHighlightMatchIndex);
        if (_wordHighlightMatchIndex < 0 ||
            _editor?.Document is not ReaderDocument document)
        {
            return;
        }
        var match = _wordHighlightResult.Matches[_wordHighlightMatchIndex];
        if (_continuousDocument is not null)
        {
            BringContinuousHighlightIntoView(match.Start);
            return;
        }
        if (_wordHighlightDocument is null || _readingWindow is null)
        {
            return;
        }
        var location = _wordHighlightDocument.Locate(
            new ArticleFindMatch(match.Start, match.Length));
        if (!_readingWindow.Current.Blocks.Any(block =>
                block.Ordinal == location.StartCursor.BlockOrdinal))
        {
            var page = await _readingWindow.LoadAsync(
                document.Id,
                Math.Max(0, location.StartCursor.BlockOrdinal - 8));
            await ShowReadingPageAsync(page);
        }
        var blockDisplay = _readingBlocks.FirstOrDefault(block =>
            block.Ordinal == location.StartCursor.BlockOrdinal);
        if (blockDisplay is null)
        {
            return;
        }
        ReadingBlocksList.SelectedItem = blockDisplay;
        ReadingBlocksList.ScrollIntoView(blockDisplay);
        ReadingBlocksList.UpdateLayout();
        if (ReadingBlocksList.ItemContainerGenerator.ContainerFromItem(blockDisplay) is
                DependencyObject container &&
            FindVisualChild<SourceHighlightTextBlock>(container) is { } textBlock)
        {
            _ = textBlock.BringWordTextIntoView(location.StartCursor.CharacterOffset);
        }
    }

    private async Task HandleWordHighlightJumpAsync(string termId)
    {
        if (_wordHighlightJumpInProgress)
        {
            return;
        }
        _wordHighlightJumpInProgress = true;
        try
        {
            await JumpToNextWordHighlightAsync(termId);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            FooterText.Text = $"Word Highlighter navigation: {exception.Message}";
        }
        finally
        {
            _wordHighlightJumpInProgress = false;
        }
    }

    private void ClearWordHighlights()
    {
        ++_wordHighlightGeneration;
        _wordHighlightDocument = null;
        _wordHighlightResult = WordHighlightResult.Empty;
        _wordHighlightsByBlockOrdinal =
            new Dictionary<int, IReadOnlyList<ReaderTextHighlight>>();
        _wordHighlightMatchIndex = -1;
        _continuousHighlightAdorner?.ShowWords([]);
        foreach (var block in _readingBlocks)
        {
            block.WordHighlights = [];
        }
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
            highlight.SourceSpans.Count == 0 ||
            _playback?.IsActive != true)
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
        EditorTextBox.Select(start, 0);
        _updatingEditor = false;
        _continuousHighlightAdorner?.Show(start, Math.Max(0, end - start));
        BringContinuousHighlightIntoView(start);
    }

    private void BringContinuousHighlightIntoView(int characterOffset)
    {
        var line = EditorTextBox.GetLineIndexFromCharacterIndex(characterOffset);
        if (line < 0)
        {
            return;
        }

        EditorTextBox.ScrollToLine(line);
        EditorTextBox.UpdateLayout();
        if (FindVisualChild<ScrollViewer>(EditorTextBox) is not { } scrollViewer)
        {
            return;
        }
        var characterRect = EditorTextBox.GetRectFromCharacterIndex(characterOffset);
        if (characterRect.IsEmpty)
        {
            return;
        }
        var targetOffset = scrollViewer.VerticalOffset + characterRect.Top -
            (scrollViewer.ViewportHeight * 0.32);
        scrollViewer.ScrollToVerticalOffset(Math.Max(0, targetOffset));
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

    private void OpenFindButton_Click(object sender, RoutedEventArgs e) => OpenFindPanel();

    private void OpenFindPanel()
    {
        if (_editor?.Document is null)
        {
            FooterText.Text = "Open an article before using Find.";
            return;
        }

        FindPanel.Visibility = Visibility.Visible;
        if (string.IsNullOrEmpty(FindTextBox.Text) &&
            EditorAdornerDecorator.Visibility == Visibility.Visible &&
            EditorTextBox.SelectionLength > 0)
        {
            var selected = EditorTextBox.SelectedText;
            if (selected.Length <= ArticleFindEngine.MaxPatternCharacters &&
                !selected.Contains('\r') &&
                !selected.Contains('\n'))
            {
                FindTextBox.Text = selected;
            }
        }
        FindTextBox.Focus();
        FindTextBox.SelectAll();
        ScheduleFindRefresh();
    }

    private void CloseFindButton_Click(object sender, RoutedEventArgs e) => CloseFindPanel();

    private void CloseFindPanel()
    {
        FindPanel.Visibility = Visibility.Collapsed;
        CancelFindWork(clearHighlights: true);
        FindStatusText.Text = string.Empty;
    }

    private async void PreviousFindButton_Click(object sender, RoutedEventArgs e) =>
        await NavigateFindAsync(-1);

    private async void NextFindButton_Click(object sender, RoutedEventArgs e) =>
        await NavigateFindAsync(1);

    private async void FindTextBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key != Key.Enter)
        {
            return;
        }
        e.Handled = true;
        await NavigateFindAsync(Keyboard.Modifiers.HasFlag(ModifierKeys.Shift) ? -1 : 1);
    }

    private void FindTextBox_TextChanged(object sender, TextChangedEventArgs e) =>
        ScheduleFindRefresh();

    private void FindOption_Changed(object sender, RoutedEventArgs e) =>
        ScheduleFindRefresh();

    private void ScheduleFindRefresh()
    {
        if (FindPanel.Visibility != Visibility.Visible)
        {
            return;
        }

        CancelFindWork(clearHighlights: true);
        if (_editor?.Document is null)
        {
            FindStatusText.Text = "No article selected";
            return;
        }
        if (FindTextBox.Text.Length == 0)
        {
            FindStatusText.Text = string.Empty;
            return;
        }

        FindStatusText.Text = "Searching…";
        _findSearchPending = true;
        var generation = _findGeneration;
        _findCancellation = new CancellationTokenSource();
        _ = RunFindAfterDelayAsync(generation, _findCancellation.Token);
    }

    private async Task RunFindAfterDelayAsync(int generation, CancellationToken cancellationToken)
    {
        try
        {
            await Task.Delay(TimeSpan.FromMilliseconds(180), cancellationToken);
            await ExecuteFindAsync(generation, cancellationToken);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task RunFindNowAsync()
    {
        CancelFindWork(clearHighlights: true);
        if (_editor?.Document is null || FindTextBox.Text.Length == 0)
        {
            FindStatusText.Text = _editor?.Document is null ? "No article selected" : string.Empty;
            return;
        }

        FindStatusText.Text = "Searching…";
        _findSearchPending = true;
        var generation = _findGeneration;
        _findCancellation = new CancellationTokenSource();
        try
        {
            await ExecuteFindAsync(generation, _findCancellation.Token);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task ExecuteFindAsync(int generation, CancellationToken cancellationToken)
    {
        if (_editor?.Document is not ReaderDocument document)
        {
            return;
        }

        var query = FindTextBox.Text;
        var options = new ArticleFindOptions(
            CaseSensitive: FindCaseSensitiveCheckBox.IsChecked == true,
            WholeWord: FindWholeWordCheckBox.IsChecked == true,
            UseRegex: FindRegexCheckBox.IsChecked == true);
        ArticleFindDocument? findDocument = null;
        string searchText;
        try
        {
            if (_continuousDocument is not null)
            {
                searchText = EditorTextBox.Text;
            }
            else
            {
                if (_findLoader is null)
                {
                    FindStatusText.Text = "Connect to the Reader service to search this article.";
                    return;
                }
                findDocument = await _findLoader.LoadAsync(document, cancellationToken);
                searchText = findDocument.Text;
            }

            var result = await Task.Run(
                () => ArticleFindEngine.Search(searchText, query, options),
                cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            if (generation != _findGeneration ||
                _editor?.Document is not ReaderDocument current ||
                !string.Equals(current.Id, document.Id, StringComparison.Ordinal) ||
                current.ContentRevision != document.ContentRevision)
            {
                return;
            }

            _findDocument = findDocument;
            _findResult = result;
            _findMatchIndex = result.Matches.Count > 0 ? 0 : -1;
            if (!result.Succeeded)
            {
                FindStatusText.Text = DescribeFindFailure(result.Failure);
                ClearFindHighlights();
                return;
            }
            if (result.Matches.Count == 0)
            {
                FindStatusText.Text = "No matches";
                ClearFindHighlights();
                return;
            }

            UpdateFindStatus();
            await ShowCurrentFindMatchAsync();
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            if (generation == _findGeneration)
            {
                FindStatusText.Text = $"Find unavailable: {exception.Message}";
                ClearFindHighlights();
            }
        }
        finally
        {
            if (generation == _findGeneration)
            {
                _findSearchPending = false;
            }
        }
    }

    private async Task NavigateFindAsync(int delta)
    {
        if (FindPanel.Visibility != Visibility.Visible || FindTextBox.Text.Length == 0)
        {
            return;
        }
        if (_findSearchPending || _findResult.Matches.Count == 0)
        {
            await RunFindNowAsync();
            return;
        }

        _findMatchIndex = ArticleFindNavigator.Move(
            _findMatchIndex,
            _findResult.Matches.Count,
            delta);
        UpdateFindStatus();
        await ShowCurrentFindMatchAsync();
    }

    private async Task ShowCurrentFindMatchAsync()
    {
        if (_findMatchIndex < 0 ||
            _findMatchIndex >= _findResult.Matches.Count ||
            _editor?.Document is not ReaderDocument document)
        {
            ClearFindHighlights();
            return;
        }

        var match = _findResult.Matches[_findMatchIndex];
        if (_continuousDocument is not null)
        {
            if (match.End > EditorTextBox.Text.Length)
            {
                ScheduleFindRefresh();
                return;
            }
            foreach (var block in _readingBlocks)
            {
                block.FindStart = -1;
                block.FindLength = 0;
            }
            _continuousHighlightAdorner?.ShowFind(match.Start, match.Length);
            BringContinuousHighlightIntoView(match.Start);
            return;
        }

        if (_findDocument is null || _readingWindow is null)
        {
            ClearFindHighlights();
            return;
        }
        var location = _findDocument.Locate(match);
        var currentPageContainsMatch = _readingWindow.Current.Blocks.Any(block =>
            block.Ordinal == location.StartCursor.BlockOrdinal);
        if (!currentPageContainsMatch)
        {
            var page = await _readingWindow.LoadAsync(
                document.Id,
                Math.Max(0, location.StartCursor.BlockOrdinal - 8));
            await ShowReadingPageAsync(page);
        }
        else
        {
            ApplyCurrentFindToReadingBlocks();
        }

        var firstBlock = _readingBlocks.FirstOrDefault(block =>
            block.Ordinal == location.StartCursor.BlockOrdinal);
        if (firstBlock is not null)
        {
            BringReadingFindIntoView(firstBlock);
        }
    }

    private void ApplyCurrentFindToReadingBlocks()
    {
        foreach (var block in _readingBlocks)
        {
            block.FindStart = -1;
            block.FindLength = 0;
        }
        if (_findDocument is null ||
            _findMatchIndex < 0 ||
            _findMatchIndex >= _findResult.Matches.Count)
        {
            return;
        }

        var location = _findDocument.Locate(_findResult.Matches[_findMatchIndex]);
        foreach (var block in _readingBlocks.Where(block =>
                     block.Ordinal >= location.StartCursor.BlockOrdinal &&
                     block.Ordinal <= location.EndCursor.BlockOrdinal))
        {
            var start = block.Ordinal == location.StartCursor.BlockOrdinal
                ? location.StartCursor.CharacterOffset
                : 0;
            var end = block.Ordinal == location.EndCursor.BlockOrdinal
                ? location.EndCursor.CharacterOffset
                : block.Text.Length;
            start = Math.Clamp(start, 0, block.Text.Length);
            end = Math.Clamp(end, start, block.Text.Length);
            if (end > start)
            {
                block.FindStart = start;
                block.FindLength = end - start;
            }
        }
    }

    private void BringReadingFindIntoView(ReaderBlockDisplay block)
    {
        ReadingBlocksList.SelectedItem = block;
        ReadingBlocksList.ScrollIntoView(block);
        ReadingBlocksList.UpdateLayout();
        if (ReadingBlocksList.ItemContainerGenerator.ContainerFromItem(block) is
                DependencyObject container &&
            FindVisualChild<SourceHighlightTextBlock>(container) is { } textBlock)
        {
            _ = textBlock.BringFindTextIntoView();
        }
    }

    private void UpdateFindStatus()
    {
        if (_findMatchIndex < 0 || _findResult.Matches.Count == 0)
        {
            FindStatusText.Text = "No matches";
            return;
        }
        var suffix = _findResult.Truncated ? "+" : string.Empty;
        FindStatusText.Text =
            $"{_findMatchIndex + 1:N0} of {_findResult.Matches.Count:N0}{suffix}";
    }

    private void CancelFindWork(bool clearHighlights)
    {
        _findGeneration++;
        _findCancellation?.Cancel();
        _findCancellation?.Dispose();
        _findCancellation = null;
        _findSearchPending = false;
        _findResult = ArticleFindResult.Empty;
        _findMatchIndex = -1;
        if (clearHighlights)
        {
            ClearFindHighlights();
        }
    }

    private void ClearFindHighlights()
    {
        _continuousHighlightAdorner?.ClearFind();
        foreach (var block in _readingBlocks)
        {
            block.FindStart = -1;
            block.FindLength = 0;
        }
    }

    private static string DescribeFindFailure(ArticleFindFailure failure) => failure switch
    {
        ArticleFindFailure.PatternTooLong =>
            $"Find text is limited to {ArticleFindEngine.MaxPatternCharacters:N0} characters.",
        ArticleFindFailure.DocumentTooLarge =>
            $"This article exceeds the {ArticleFindEngine.MaxDocumentCharacters:N0}-character Find safety limit.",
        ArticleFindFailure.InvalidRegex => "Invalid regular expression.",
        ArticleFindFailure.RegexTimedOut => "The regular expression took too long and was stopped.",
        _ => string.Empty,
    };

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
        EditorAdornerDecorator.Visibility = showContinuousEditor
            ? Visibility.Visible
            : Visibility.Collapsed;
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
        if (e.Key == Key.F && Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
        {
            e.Handled = true;
            OpenFindPanel();
            return;
        }
        if (e.Key == Key.F3 && FindPanel.Visibility == Visibility.Visible)
        {
            e.Handled = true;
            await NavigateFindAsync(
                Keyboard.Modifiers.HasFlag(ModifierKeys.Shift) ? -1 : 1);
            return;
        }
        if (e.Key == Key.Escape && FindPanel.Visibility == Visibility.Visible)
        {
            e.Handled = true;
            CloseFindPanel();
            return;
        }
        if (e.Key == Key.Escape &&
            (_ephemeralPlaying || _ephemeralReplayText is not null ||
                _playback?.State is not ReaderPlaybackState.Stopped))
        {
            e.Handled = true;
            await StopUnifiedPlaybackAsync();
            return;
        }
        if (e.Key == Key.Space &&
            !FindPanel.IsKeyboardFocusWithin &&
            Keyboard.FocusedElement is not TextBox)
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
            var local = _settings.ActiveConnection.IsLocal;
            var serviceUnavailable = _onboarding.State == ConnectionState.ServiceUnavailable;
            StartServiceButton.IsEnabled = local && serviceUnavailable;
            StopServiceButton.IsEnabled = local && (!serviceUnavailable ||
                ScheduledServiceController.OwnsRunningService);
        }
        if (text is not null)
        {
            StatusText.Text = text;
        }
    }

    private sealed record FolderFilterItem(
        string? Id,
        string DisplayName,
        bool PrivacyLocked,
        bool PrivacyUnlocked);

    private sealed record ConnectionChoice(string Id, string Name, bool IsLocal);

    private enum AutomaticPauseKind
    {
        None,
        Document,
        Clipboard,
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
