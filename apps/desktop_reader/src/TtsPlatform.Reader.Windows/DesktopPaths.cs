namespace TtsPlatform.Reader.Windows;

public static class DesktopPaths
{
    public static string ReaderHome => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "TTSPlatform",
        "Reader");

    public static string SettingsPath => Path.Combine(ReaderHome, "settings.json");

    public static string ServiceProcessLeasePath => Path.Combine(
        ReaderHome,
        "service-process.json");
}
