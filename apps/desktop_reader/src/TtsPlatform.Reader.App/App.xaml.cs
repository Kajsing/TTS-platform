using System.Globalization;
using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class App : System.Windows.Application
{
    private ReaderInstanceChannel? _instance;
    private DesktopServiceCenterHost? _serviceCenter;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        CultureInfo.DefaultThreadCurrentUICulture ??= CultureInfo.CurrentUICulture;
        var smokeTest = e.Args.Contains("--smoke-test", StringComparer.Ordinal);
        if (smokeTest && Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_LIFECYCLE_SMOKE") == "1")
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            if (e.Args.Contains("--activation-probe", StringComparer.Ordinal))
            {
                var scope = Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_ACTIVATION_SCOPE");
                var succeeded = scope?.StartsWith("smoke-", StringComparison.Ordinal) == true &&
                    await ReaderInstanceChannel.SendAsync(scope, ReaderActivation.OpenReader);
                Shutdown(succeeded ? 0 : 1);
                return;
            }
            await RunServiceCenterLifecycleSmokeAsync();
            return;
        }
        if (!smokeTest)
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            try
            {
                var activation = e.Args.Contains("--background", StringComparer.Ordinal)
                    ? ReaderActivation.Background
                    : e.Args.Contains("--service-center", StringComparer.Ordinal)
                        ? ReaderActivation.OpenServiceCenter : ReaderActivation.OpenReader;
                if (!ReaderInstanceChannel.TryAcquire(ReaderInstanceChannel.DefaultScope, out _instance))
                {
                    var delivered = await ReaderInstanceChannel.SendAsync(ReaderInstanceChannel.DefaultScope, activation);
                    if (!delivered) MessageBox.Show(
                        "Service Center is already starting or not responding. No second Reader or service was started. Please try opening it again.",
                        "TTS Platform", MessageBoxButton.OK, MessageBoxImage.Information);
                    Shutdown(delivered ? 0 : 1);
                    return;
                }
                _serviceCenter = new DesktopServiceCenterHost(new JsonDesktopSettingsStore());
                _instance!.Listen(_serviceCenter.QueueActivation);
                _serviceCenter.QueueActivation(activation);
            }
            catch (Exception exception)
            {
                MessageBox.Show("Service Center could not start.\n\n" + exception.Message,
                    "TTS Platform", MessageBoxButton.OK, MessageBoxImage.Warning);
                Shutdown(1);
            }
            return;
        }
        var agentSmoke = smokeTest ? AgentSmokeScenario.LoadFromEnvironment() : null;
        var folderSmoke = smokeTest && Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_FOLDER_SMOKE") == "1";
        var folderSettingsPath = folderSmoke
            ? System.IO.Path.Combine(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(
                Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_SMOKE_MARKER")
                    ?? throw new InvalidOperationException("Folder smoke requires an isolated marker path.")))!,
                "folder-smoke-settings.json")
            : null;
        var settingsStore = new JsonDesktopSettingsStore(folderSettingsPath ?? agentSmoke?.SettingsPath);
        DesktopSettings settings;
        try
        {
            settings = folderSmoke ? new DesktopSettings()
                : agentSmoke?.Settings ?? settingsStore.LoadAsync().GetAwaiter().GetResult();
        }
        catch
        {
            settings = new DesktopSettings(TokenSource: new TokenSourceSettings());
        }

        var window = new MainWindow(settingsStore, settings, smokeTest);
        MainWindow = window;
        window.Show();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _instance?.Dispose();
        _serviceCenter?.Dispose();
        base.OnExit(e);
    }
}
