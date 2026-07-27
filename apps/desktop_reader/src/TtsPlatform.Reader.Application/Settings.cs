using System.Text.Json.Serialization;

namespace TtsPlatform.Reader.Application;

public sealed record TokenSourceSettings(string Type = "file", string Path = "");

public sealed record DesktopHotkeys(
    string ReadClipboard = "Ctrl+Alt+Insert",
    string CopySelectionAndRead = "Ctrl+Alt+Space",
    string PlayPause = "Ctrl+Alt+P",
    string Stop = "Ctrl+Alt+S");

public sealed record DesktopSettings(
    string ServiceBaseUrl = "http://127.0.0.1:7777/",
    TokenSourceSettings? TokenSource = null,
    string Theme = "system",
    string ReadingFontFamily = "Segoe UI",
    double ReadingFontSize = 20,
    bool ClipboardMonitoringEnabled = false,
    DesktopHotkeys? Hotkeys = null)
{
    [JsonIgnore]
    public TokenSourceSettings EffectiveTokenSource => TokenSource ?? new TokenSourceSettings();

    [JsonIgnore]
    public DesktopHotkeys EffectiveHotkeys => Hotkeys ?? new DesktopHotkeys();
}

public interface IDesktopSettingsStore
{
    string SettingsPath { get; }
    Task<DesktopSettings> LoadAsync(CancellationToken cancellationToken = default);
    Task SaveAsync(DesktopSettings settings, CancellationToken cancellationToken = default);
}
