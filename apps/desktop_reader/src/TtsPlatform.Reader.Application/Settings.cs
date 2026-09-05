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

public sealed record RemoteConnectionProfileSettings(
    string Id,
    string Name,
    string ServiceBaseUrl,
    string ServerSpkiPin,
    string CredentialId);

public sealed record DesktopConnectionTarget(
    string Id,
    string Name,
    bool IsLocal,
    string ServiceBaseUrl,
    string? ServerSpkiPin,
    string CredentialId);

public sealed record DesktopSettings(
    string ServiceBaseUrl = "http://127.0.0.1:7777/",
    TokenSourceSettings? TokenSource = null,
    string? PreferredVoiceId = null,
    string Theme = "system",
    string ReadingFontFamily = "Segoe UI",
    double ReadingFontSize = 20,
    bool ClipboardMonitoringEnabled = false,
    int ClipboardPromptMinimumCharacters = 50,
    DateTimeOffset? ClipboardPromptSnoozedUntilUtc = null,
    bool CopySelectionAndReadEnabled = false,
    bool PrivacyMode = true,
    bool MinimizeToTrayOnClose = false,
    IReadOnlyList<string>? ClipboardBlockedApplications = null,
    DesktopHotkeys? Hotkeys = null,
    CompactControllerSettings? CompactController = null,
    bool? PauseForCallsAndAlarms = null,
    string ActiveConnectionProfileId = "local",
    IReadOnlyList<RemoteConnectionProfileSettings>? RemoteConnectionProfiles = null,
    IReadOnlyDictionary<string, string[]>? ClosedFolderIdsByWorkspace = null)
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

    [JsonIgnore]
    public bool EffectivePauseForCallsAndAlarms => PauseForCallsAndAlarms ?? true;

    [JsonIgnore]
    public IReadOnlyList<RemoteConnectionProfileSettings> EffectiveRemoteConnectionProfiles =>
        RemoteConnectionProfiles ?? [];

    [JsonIgnore]
    public DesktopConnectionTarget ActiveConnection =>
        EffectiveRemoteConnectionProfiles
            .Where(profile => string.Equals(
                profile.Id,
                ActiveConnectionProfileId,
                StringComparison.Ordinal))
            .Select(profile => new DesktopConnectionTarget(
                profile.Id,
                profile.Name,
                false,
                profile.ServiceBaseUrl,
                profile.ServerSpkiPin,
                profile.CredentialId))
            .FirstOrDefault() ?? new DesktopConnectionTarget(
                "local",
                "Local",
                true,
                ServiceBaseUrl,
                null,
                string.Empty);
}

public enum ClipboardPromptSuppressionReason
{
    None,
    Empty,
    BelowMinimumLength,
    Snoozed,
}

public sealed record ClipboardPromptDecision(
    bool ShouldPrompt,
    ClipboardPromptSuppressionReason SuppressionReason,
    int TrimmedCharacterCount,
    DateTimeOffset? SnoozedUntilUtc = null);

public sealed class ClipboardPromptPolicy(TimeProvider? timeProvider = null)
{
    public static readonly TimeSpan SnoozeDuration = TimeSpan.FromMinutes(5);
    private readonly TimeProvider _timeProvider = timeProvider ?? TimeProvider.System;

    public ClipboardPromptDecision Evaluate(
        string text,
        int minimumCharacters,
        DateTimeOffset? snoozedUntilUtc)
    {
        ArgumentNullException.ThrowIfNull(text);
        if (minimumCharacters < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(minimumCharacters));
        }

        var trimmedLength = text.Trim().Length;
        if (trimmedLength == 0)
        {
            return new ClipboardPromptDecision(
                false,
                ClipboardPromptSuppressionReason.Empty,
                trimmedLength);
        }

        var now = _timeProvider.GetUtcNow();
        if (snoozedUntilUtc is not null && snoozedUntilUtc > now)
        {
            return new ClipboardPromptDecision(
                false,
                ClipboardPromptSuppressionReason.Snoozed,
                trimmedLength,
                snoozedUntilUtc);
        }

        if (minimumCharacters > 0 && trimmedLength <= minimumCharacters)
        {
            return new ClipboardPromptDecision(
                false,
                ClipboardPromptSuppressionReason.BelowMinimumLength,
                trimmedLength);
        }

        return new ClipboardPromptDecision(
            true,
            ClipboardPromptSuppressionReason.None,
            trimmedLength);
    }

    public DateTimeOffset SnoozeUntilUtc() =>
        _timeProvider.GetUtcNow().Add(SnoozeDuration);

    public bool IsSnoozed(DateTimeOffset? snoozedUntilUtc) =>
        snoozedUntilUtc is not null && snoozedUntilUtc > _timeProvider.GetUtcNow();
}

public static class DesktopConnectionPolicy
{
    public static bool RequiresReconnect(
        DesktopSettings current,
        string serviceBaseUrl,
        string tokenPath,
        string? activeConnectionProfileId = null)
    {
        ArgumentNullException.ThrowIfNull(current);
        ArgumentNullException.ThrowIfNull(serviceBaseUrl);
        ArgumentNullException.ThrowIfNull(tokenPath);

        return !string.Equals(
                   current.ServiceBaseUrl,
                   serviceBaseUrl,
                   StringComparison.OrdinalIgnoreCase) ||
               !string.Equals(
                   current.EffectiveTokenSource.Path,
                   tokenPath,
                   StringComparison.OrdinalIgnoreCase) ||
               !string.Equals(
                   current.ActiveConnectionProfileId,
                   activeConnectionProfileId ?? current.ActiveConnectionProfileId,
                   StringComparison.Ordinal);
    }
}

public interface IDesktopSettingsStore
{
    string SettingsPath { get; }
    Task<DesktopSettings> LoadAsync(CancellationToken cancellationToken = default);
    Task SaveAsync(DesktopSettings settings, CancellationToken cancellationToken = default);
}
