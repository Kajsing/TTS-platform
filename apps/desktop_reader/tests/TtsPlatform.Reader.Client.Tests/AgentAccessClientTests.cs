using System.Net;
using System.Text;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class AgentAccessClientTests
{
    [Fact]
    public async Task Setup_uses_owner_auth_and_explicit_folder_and_no_secret_in_status()
    {
        var requests = new List<(string Method, string Path, string? Body)>();
        using var http = new HttpClient(new Handler(async request =>
        {
            Assert.Equal("Bearer owner-secret", request.Headers.Authorization?.ToString());
            var body = request.Content is null ? null : await request.Content.ReadAsStringAsync();
            requests.Add((request.Method.Method, request.RequestUri!.AbsolutePath, body));
            var grant = """
                {"id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","folder_id":"folder","name":"Agent","operations":["read","create"],"created_at":"2026-09-05T12:00:00Z","revoked_at":null}
                """;
            var json = request.Method == HttpMethod.Get ? "{\"grants\":[" + grant + "]}"
                : request.Method == HttpMethod.Post ? "{\"grant\":" + grant + ",\"credential\":\"protected-secret\"}"
                : "{\"revoked\":true}";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
        }));
        var client = new ReaderServiceClient(http, "http://127.0.0.1:7777/", new TokenProvider());
        var page = await client.GetAgentGrantsAsync();
        Assert.Equal("Active", page.Grants.Single().Status);
        var provision = await client.ProvisionAgentAsync(new ReaderAgentGrantRequest("folder", "Agent"));
        Assert.Equal("protected-secret", provision.Credential);
        Assert.DoesNotContain(provision.Credential, provision.ToString());
        await client.RevokeAgentAsync(provision.Grant.Id);
        Assert.Contains("\"folder_id\":\"folder\"", requests[1].Body);
        Assert.Equal("DELETE", requests[2].Method);
        Assert.EndsWith(provision.Grant.Id, requests[2].Path);
    }

    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => send(request);
    }

    private sealed class TokenProvider : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<string?>("owner-secret");
    }
}
