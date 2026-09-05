using System.IO;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

// Only used with --smoke-test and an explicit isolated smoke manifest. Never
// loads the user's settings, clipboard, credentials, audio device or database.
internal sealed record AgentSmokeScenario(
    string Root, string ServiceUrl, string Python, string Phase, string FolderId,
    string? GrantId, string? ArticleId, string? ExpectedText)
{
    public string SettingsPath => Path.Combine(Root, "desktop-settings.json");
    public string MarkerPath => Path.Combine(Root, "desktop-result.json");
    public string ConnectionsPath => Path.Combine(Root, "agent-connections");
    public DesktopSettings Settings => new(ServiceUrl,
        new TokenSourceSettings(Path: Path.Combine(Root, "service", "token.txt")));

    public static AgentSmokeScenario? LoadFromEnvironment()
    {
        var path = Environment.GetEnvironmentVariable("TTS_PLATFORM_READER_AGENT_SMOKE");
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }
        using var manifest = JsonDocument.Parse(File.ReadAllText(path));
        var data = manifest.RootElement;
        var root = Path.GetDirectoryName(Path.GetFullPath(path))!;
        var url = ServiceBaseUrl.Parse(data.GetProperty("service_url").GetString()!);
        if (url.Port == 7777 || !File.Exists(Path.Combine(root, "isolated-reader-agent-smoke")))
        {
            throw new InvalidOperationException("Agent smoke requires isolated storage and a non-default loopback port.");
        }
        string? Optional(string key) => data.TryGetProperty(key, out var value) ? value.GetString() : null;
        return new AgentSmokeScenario(root, url.AbsoluteUri,
            data.GetProperty("python").GetString()!, data.GetProperty("phase").GetString()!,
            data.GetProperty("folder_id").GetString()!, Optional("grant_id"), Optional("article_id"), Optional("expected_text"));
    }
}
