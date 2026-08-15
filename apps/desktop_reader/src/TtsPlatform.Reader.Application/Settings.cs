using System.Text.Json.Serialization;

namespace TtsPlatform.Reader.Application;

public sealed record TokenSourceSettings(string Type = "file", string Path = "");

public sealed record DesktopHotkeys(
    string ReadClipboard = "Ctrl+Alt+Insert",
    string CopySelectionAndRead = "Ctrl+Alt+Space",
    string PlayPause = "Ctrl+Alt+P",
    string Stop = "Ctrl+Alt+S");

public sealed record CompactControllerSettings(
    bool Enabled = false,
    bool AlwaysOnTop = true,
    double? Left = null,
    double? Top = null);

public sealed record DesktopSettings(
    string ServiceBaseUrl = "http://127.0.0.1:7777/",
    TokenSourceSettings? TokenSource = null,
    string? PreferredVoiceId = null,
    string Theme = "system",
    string ReadingFontFamily = "Segoe UI",
    double ReadingFontSize = 20,
    bool ClipboardMonitoringEnabled = false,
    bool CopySelectionAndReadEnabled = false,
    bool PrivacyMode = true,
    bool MinimizeToTrayOnClose = false,
    IReadOnlyList<string>? ClipboardBlockedApplications = null,
    DesktopHotkeys? Hotkeys = null,
    CompactControllerSettings? CompactController = null)
{
    [JsonIgnore]
    public TokenSourceSettings EffectiveTokenSource => TokenSource ?? new TokenSourceSettings();

    [JsonIgnore]
    public DesktopHotkeys EffectiveHotkeys => Hotkeys ?? new DesktopHotkeys();

    [JsonIgnore]
    public IReadOnlyList<string> EffectiveClipboardBlockedApplications =>
        ClipboardBlockedApplications ?? [];

    [JsonIgnore]
    public CompactControllerSettings EffectiveCompactController =>
        CompactController ?? new CompactControllerSettings();
}

public interface IDesktopSettingsStore
{
    string SettingsPath { get; }
    Task<DesktopSettings> LoadAsync(CancellationToken cancellationToken = default);
    Task SaveAsync(DesktopSettings settings, CancellationToken cancellationToken = default);
}
