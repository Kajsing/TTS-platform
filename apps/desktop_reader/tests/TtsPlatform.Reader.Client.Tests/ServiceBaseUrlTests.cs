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
}
