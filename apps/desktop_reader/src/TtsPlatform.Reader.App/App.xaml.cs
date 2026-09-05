using System.Globalization;
using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class App : System.Windows.Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        CultureInfo.DefaultThreadCurrentUICulture ??= CultureInfo.CurrentUICulture;
        var smokeTest = e.Args.Contains("--smoke-test", StringComparer.Ordinal);
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
}
