using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Windows;

public sealed class JsonDesktopSettingsStore(string? settingsPath = null) : IDesktopSettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
    };

    public string SettingsPath { get; } = settingsPath ?? DesktopPaths.SettingsPath;

    public async Task<DesktopSettings> LoadAsync(CancellationToken cancellationToken = default)
    {
        if (!File.Exists(SettingsPath))
        {
            return new DesktopSettings(TokenSource: new TokenSourceSettings());
        }

        await using var stream = new FileStream(
            SettingsPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            4096,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        var settings = await JsonSerializer.DeserializeAsync<DesktopSettings>(stream, JsonOptions, cancellationToken)
            .ConfigureAwait(false);
        return Validate(settings ?? new DesktopSettings());
    }

    public async Task SaveAsync(DesktopSettings settings, CancellationToken cancellationToken = default)
    {
        settings = Validate(settings);
        var directory = Path.GetDirectoryName(SettingsPath)
            ?? throw new InvalidOperationException("The settings path must have a parent directory.");
        Directory.CreateDirectory(directory);
        var temporaryPath = Path.Combine(directory, $".{Path.GetFileName(SettingsPath)}.{Guid.NewGuid():N}.tmp");
        try
        {
            await using (var stream = new FileStream(
                temporaryPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                4096,
                FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await JsonSerializer.SerializeAsync(stream, settings, JsonOptions, cancellationToken)
                    .ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
            }

            File.Move(temporaryPath, SettingsPath, true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }

    private static DesktopSettings Validate(DesktopSettings settings)
    {
        _ = ServiceBaseUrl.Parse(settings.ServiceBaseUrl);
        var tokenSource = settings.EffectiveTokenSource;
        if (!string.Equals(tokenSource.Type, "file", StringComparison.Ordinal))
        {
            throw new ReaderClientConfigurationException("Only file token sources are supported.");
        }

        if (settings.ReadingFontSize is < 10 or > 72)
        {
            throw new ReaderClientConfigurationException("Reading font size must be between 10 and 72.");
        }

        if (settings.ClipboardPromptMinimumCharacters is < 0 or > 10_000_000)
        {
            throw new ReaderClientConfigurationException(
                "The clipboard prompt minimum must be between 0 and 10,000,000 characters.");
        }

        var preferredVoiceId = string.IsNullOrWhiteSpace(settings.PreferredVoiceId)
            ? null
            : settings.PreferredVoiceId.Trim();
        if (preferredVoiceId?.Length > 256)
        {
            throw new ReaderClientConfigurationException(
                "The preferred voice identifier is too long.");
        }

        var blockedApplications = settings.EffectiveClipboardBlockedApplications
            .Select(item => item.Trim())
            .Where(item => item.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return settings with
        {
            TokenSource = tokenSource,
            PreferredVoiceId = preferredVoiceId,
            Hotkeys = settings.EffectiveHotkeys,
            ClipboardBlockedApplications = blockedApplications,
            CompactController = settings.EffectiveCompactController,
        };
    }
}
