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
        var settingsStore = new JsonDesktopSettingsStore(agentSmoke?.SettingsPath);
        DesktopSettings settings;
        try
        {
            settings = agentSmoke?.Settings ?? settingsStore.LoadAsync().GetAwaiter().GetResult();
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
