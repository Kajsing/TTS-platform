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
    public async Task Settings_store_persists_remote_metadata_without_a_credential()
    {
        var settingsPath = Path.Combine(_temporaryDirectory, "settings.json");
        var profileId = Guid.NewGuid().ToString();
        var credentialId = Guid.NewGuid().ToString();
        var store = new JsonDesktopSettingsStore(settingsPath);
        await store.SaveAsync(new DesktopSettings(
            ActiveConnectionProfileId: profileId,
            RemoteConnectionProfiles:
            [
                new RemoteConnectionProfileSettings(
                    profileId,
                    " Home Reader ",
                    "https://10.8.0.1:7790",
                    "sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                    credentialId),
            ]));

        var json = await File.ReadAllTextAsync(settingsPath);
        var loaded = await store.LoadAsync();

        Assert.Equal(profileId, loaded.ActiveConnectionProfileId);
        Assert.Equal("Home Reader", loaded.ActiveConnection.Name);
        Assert.Equal("https://10.8.0.1:7790/", loaded.ActiveConnection.ServiceBaseUrl);
        Assert.DoesNotContain("rd1.", json, StringComparison.Ordinal);
    }

    [Fact]
    public void Dpapi_store_round_trips_credential_for_the_current_windows_user()
    {
        var directory = Path.Combine(_temporaryDirectory, "credentials");
        var credentialId = Guid.NewGuid().ToString();
        var store = new DpapiCredentialStore(directory);

        store.Save(credentialId, "rd1.device.secret");

        Assert.Equal("rd1.device.secret", store.Load(credentialId));
        Assert.DoesNotContain(
            "rd1.device.secret",
            Convert.ToBase64String(File.ReadAllBytes(Path.Combine(directory, $"{credentialId}.bin"))),
            StringComparison.Ordinal);
        store.Delete(credentialId);
        Assert.Null(store.Load(credentialId));
    }

    [Fact]
    public void Dpapi_store_promotes_a_pending_rotation_only_after_confirmation()
    {
        var directory = Path.Combine(_temporaryDirectory, "rotation-credentials");
        var credentialId = Guid.NewGuid().ToString();
        var store = new DpapiCredentialStore(directory);
        store.Save(credentialId, "rd1.device.old");

        store.SavePending(credentialId, "rd1.device.new");

        Assert.Equal("rd1.device.old", store.Load(credentialId));
        store.PromotePending(credentialId);
        Assert.Equal("rd1.device.new", store.Load(credentialId));
    }

    [Fact]
    public void Firewall_helper_arguments_keep_the_rule_narrow()
    {
        var profileId = Guid.NewGuid().ToString();
        var profile = new RemoteServerProfile(
            1,
            profileId,
            false,
            "10.7.0.1",
            7790,
            null,
            "https://10.7.0.1:7790/",
            "sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "wireguard",
            "10.7.0.2/32",
            "Reader-WireGuard",
            "Public",
            $"TTSPlatform.Reader.Remote.{profileId}",
            @"C:\TTSPlatform\python.exe",
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow);
        var arguments = new WindowsFirewallRuleManager(@"C:\helper.ps1")
            .CreateArguments(profile);

        Assert.Contains("10.7.0.1", arguments);
        Assert.Contains("10.7.0.2/32", arguments);
        Assert.Contains("Reader-WireGuard", arguments);
        Assert.Contains(@"C:\TTSPlatform\python.exe", arguments);
        Assert.DoesNotContain("Any", arguments);
        Assert.DoesNotContain("0.0.0.0", arguments);
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
