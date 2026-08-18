using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class SettingsTests : IDisposable
{
    private readonly string _temporaryDirectory = Path.Combine(
        Path.GetTempPath(),
        $"tts-reader-settings-{Guid.NewGuid():N}");

    [Fact]
    public async Task Settings_store_persists_token_path_but_has_no_raw_token_field()
    {
        var settingsPath = Path.Combine(_temporaryDirectory, "settings.json");
        var store = new JsonDesktopSettingsStore(settingsPath);
        var settings = new DesktopSettings(
            TokenSource: new TokenSourceSettings("file", @"C:\safe\token.txt"),
            PreferredVoiceId: " voice-id ",
            ClipboardPromptMinimumCharacters: 50,
            ClipboardPromptSnoozedUntilUtc: DateTimeOffset.Parse("2026-08-18T17:05:00Z"));

        await store.SaveAsync(settings);
        var json = await File.ReadAllTextAsync(settingsPath);
        var loaded = await store.LoadAsync();

        Assert.Contains("\"serviceBaseUrl\"", json, StringComparison.Ordinal);
        Assert.Contains("\"tokenSource\"", json, StringComparison.Ordinal);
        Assert.Contains("\"path\"", json, StringComparison.Ordinal);
        Assert.DoesNotContain("\"token\"", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("effectiveTokenSource", json, StringComparison.Ordinal);
        Assert.DoesNotContain("effectiveHotkeys", json, StringComparison.Ordinal);
        Assert.Equal(@"C:\safe\token.txt", loaded.EffectiveTokenSource.Path);
        Assert.Equal("voice-id", loaded.PreferredVoiceId);
        Assert.False(loaded.ClipboardMonitoringEnabled);
        Assert.True(loaded.PrivacyMode);
        Assert.False(loaded.CopySelectionAndReadEnabled);
        Assert.Equal(50, loaded.ClipboardPromptMinimumCharacters);
        Assert.Equal(
            DateTimeOffset.Parse("2026-08-18T17:05:00Z"),
            loaded.ClipboardPromptSnoozedUntilUtc);
        Assert.DoesNotContain("clipboard text", json, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Settings_store_rejects_negative_clipboard_prompt_minimum()
    {
        var store = new JsonDesktopSettingsStore(Path.Combine(_temporaryDirectory, "settings.json"));

        await Assert.ThrowsAsync<ReaderClientConfigurationException>(() =>
            store.SaveAsync(new DesktopSettings(ClipboardPromptMinimumCharacters: -1)));
    }

    [Fact]
    public async Task Settings_store_rejects_non_loopback_service_address()
    {
        var store = new JsonDesktopSettingsStore(Path.Combine(_temporaryDirectory, "settings.json"));

        await Assert.ThrowsAsync<ReaderClientConfigurationException>(() =>
            store.SaveAsync(new DesktopSettings(ServiceBaseUrl: "http://example.com:7777/")));
    }

    [Fact]
    public void Wasapi_output_has_a_hard_ten_second_mono_pcm_limit()
    {
        var format = new PcmAudioFormat(22_050, 1, 16);

        Assert.Equal(441_000, WasapiAudioOutput.MaximumBufferedBytes(format));
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            WasapiAudioOutput.MaximumBufferedBytes(new PcmAudioFormat(22_050, 2, 16)));
    }

    public void Dispose()
    {
        if (Directory.Exists(_temporaryDirectory))
        {
            Directory.Delete(_temporaryDirectory, recursive: true);
        }
    }
}
