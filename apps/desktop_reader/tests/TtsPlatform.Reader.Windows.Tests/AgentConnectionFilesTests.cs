using System.Text.Json;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class AgentConnectionFilesTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"reader-agent-test-{Guid.NewGuid():N}");

    [Fact]
    public void Connection_contains_no_plaintext_secret_and_DPAPI_roundtrips()
    {
        var files = new AgentConnectionFiles(_directory);
        var provision = Provision();
        Assert.False(files.HasConnection(provision.Grant.Id));
        var path = files.Save(provision, "http://127.0.0.1:7777/");
        Assert.True(files.HasConnection(provision.Grant.Id));
        var json = File.ReadAllText(path);
        Assert.DoesNotContain(provision.Credential, json);
        Assert.DoesNotContain(provision.Credential, provision.ToString());
        Assert.Equal(provision.Credential, new DpapiCredentialStore(_directory).Load(provision.Grant.Id));
        using var payload = JsonDocument.Parse(json);
        Assert.Equal(1, payload.RootElement.GetProperty("version").GetInt32());
        Assert.Equal(provision.Grant.Id, payload.RootElement.GetProperty("grant_id").GetString());
        Assert.Equal(3, payload.RootElement.EnumerateObject().Count());
        Assert.Throws<ReaderClientConfigurationException>(() => files.Save(provision, "http://127.0.0.1:7777/"));
        files.RemoveRevoked(provision.Grant.Id);
        Assert.False(files.HasConnection(provision.Grant.Id));
        files.RemoveRevoked(provision.Grant.Id);
    }

    [Fact]
    public void Client_configuration_uses_argument_array_and_no_token()
    {
        var files = new AgentConnectionFiles(_directory);
        var provision = Provision();
        var connection = files.Save(provision, "http://127.0.0.1:7777/");
        var python = Environment.ProcessPath!; // Existing executable; test only serializes it.
        var configuration = files.ClientConfiguration(provision.Grant.Id, python);
        using var payload = JsonDocument.Parse(configuration);
        var entry = payload.RootElement.GetProperty("mcpServers").GetProperty("tts-platform-reader");
        Assert.Equal(python, entry.GetProperty("command").GetString());
        Assert.Equal(connection, entry.GetProperty("args")[3].GetString());
        Assert.DoesNotContain(provision.Credential, configuration);
        Assert.DoesNotContain("--token", configuration);
    }

    [Fact]
    public void Invalid_identifiers_remote_urls_and_owner_tokens_are_refused()
    {
        var files = new AgentConnectionFiles(_directory);
        Assert.Throws<ReaderClientConfigurationException>(() => files.ConfigurationPath("../escape"));
        Assert.Throws<ReaderClientConfigurationException>(() => files.Save(Provision(), "https://example.com/"));
        Assert.Throws<ReaderClientConfigurationException>(() => files.Save(Provision() with { Credential = "owner-token" }, "http://127.0.0.1:7777/"));
        Assert.False(Directory.Exists(_directory));
    }

    private static ReaderAgentProvisionResult Provision() => new(
        new ReaderAgentGrant(Guid.NewGuid().ToString(), Guid.NewGuid().ToString(), "Test", ["read", "create"], DateTimeOffset.UtcNow, null),
        "rdr_agent_" + new string('a', 43));

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }
}
