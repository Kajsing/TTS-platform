using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class ServiceBaseUrlTests
{
    [Theory]
    [InlineData("http://127.0.0.1:8000", "http://127.0.0.1:8000/")]
    [InlineData("http://localhost:8123/", "http://localhost:8123/")]
    [InlineData("http://localhost", "http://localhost:7777/")]
    public void Parse_accepts_only_explicit_loopback_hosts(string input, string expected)
    {
        Assert.Equal(expected, ServiceBaseUrl.Parse(input).AbsoluteUri);
    }

    [Theory]
    [InlineData("https://localhost:8000/")]
    [InlineData("http://0.0.0.0:8000/")]
    [InlineData("http://[::1]:8000/")]
    [InlineData("http://example.com:8000/")]
    [InlineData("http://user:secret@localhost:8000/")]
    [InlineData("http://localhost:8000/v1")]
    [InlineData("http://localhost:8000/?token=secret")]
    [InlineData("not-a-url")]
    public void Parse_rejects_urls_outside_the_desktop_security_contract(string input)
    {
        Assert.Throws<ReaderClientConfigurationException>(() => ServiceBaseUrl.Parse(input));
    }

    [Theory]
    [InlineData("https://10.8.0.1:7790", "https://10.8.0.1:7790/")]
    [InlineData("https://reader.home.arpa/", "https://reader.home.arpa/")]
    public void ParseRemote_accepts_https_origins(string input, string expected)
    {
        Assert.Equal(expected, ServiceBaseUrl.ParseRemote(input).AbsoluteUri);
    }

    [Theory]
    [InlineData("http://10.8.0.1:7790/")]
    [InlineData("https://user:secret@10.8.0.1:7790/")]
    [InlineData("https://10.8.0.1:7790/v1")]
    [InlineData("https://10.8.0.1:7790/?token=secret")]
    public void ParseRemote_rejects_non_https_origins(string input)
    {
        Assert.Throws<ReaderClientConfigurationException>(() => ServiceBaseUrl.ParseRemote(input));
    }

    [Fact]
    public void Pin_validator_rejects_invalid_pin_shapes()
    {
        Assert.Throws<ReaderClientConfigurationException>(() =>
            new PinnedServerCertificateValidator("sha256/not-base64"));
        Assert.Throws<ReaderClientConfigurationException>(() =>
            new PinnedServerCertificateValidator("sha256/YQ=="));
    }

    [Fact]
    public void Pairing_invitation_uses_the_snake_case_wire_contract()
    {
        var expires = DateTimeOffset.UtcNow.AddMinutes(5);
        var source = new RemotePairingInvitation(
            1,
            "https://10.8.0.1:7790/",
            "sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            Guid.NewGuid().ToString(),
            new string('x', 43),
            expires);

        var json = RemotePairingClient.FormatInvitation(source);
        var parsed = RemotePairingClient.ParseInvitation(json);

        Assert.Contains("\"contract_version\"", json, StringComparison.Ordinal);
        Assert.Contains("\"server_spki_pin\"", json, StringComparison.Ordinal);
        Assert.Equal(source.Endpoint, parsed.Endpoint);
        Assert.Equal(source.TicketId, parsed.TicketId);
    }
}
