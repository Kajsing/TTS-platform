using System.Net;
using System.Text;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class SearchClientTests
{
    [Fact]
    public async Task Search_contracts_keep_patterns_in_protected_post_bodies_and_use_source_mapped_results()
    {
        var requests = new List<(string Path, string Body)>();
        var handler = new Handler(async request =>
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("Bearer owner", request.Headers.Authorization!.ToString());
            Assert.Equal("privacy", Assert.Single(request.Headers.GetValues(ReaderPrivacySessionStore.HeaderName)));
            Assert.Equal("", request.RequestUri!.Query);
            var body = await request.Content!.ReadAsStringAsync();
            requests.Add((request.RequestUri.AbsolutePath, body));
            var result = request.RequestUri.AbsolutePath.EndsWith("/next", StringComparison.Ordinal)
                ? "{\"match\":null}"
                : request.RequestUri.AbsolutePath.EndsWith("/results", StringComparison.Ordinal) ||
                  request.RequestUri.AbsolutePath.EndsWith("/window", StringComparison.Ordinal)
                    ? "{\"document_id\":\"doc/id\",\"content_revision\":7,\"matches\":[],\"next_offset\":null,\"total_matches\":0,\"truncated\":false}"
                    : "{\"search_id\":\"session/id\",\"document_id\":\"doc/id\",\"content_revision\":7,\"kind\":\"find\",\"total_matches\":0,\"counts\":{},\"truncated\":false,\"failure\":null,\"regex_dialect\":\"regex-v0\",\"expires_in_seconds\":300}";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(result, Encoding.UTF8, "application/json") };
        });
        using var privacy = new ReaderPrivacySessionStore();
        privacy.Store(new("folder", "privacy", DateTimeOffset.UtcNow.AddMinutes(5), 300));
        IReaderServiceClient client = new ReaderServiceClient(new HttpClient(handler), "http://localhost:7777", new Token(), privacy);
        var summary = await client.CreateSearchAsync("doc/id", new(7, "private pattern", WholeWord: true, UseRegex: true));
        await client.CreateHighlightSearchAsync("doc/id", new(7, 4));
        await client.GetSearchResultsAsync("doc/id", "session/id", new(1, 20));
        await client.GetSearchWindowAsync("doc/id", "session/id", new(20, 83));
        await client.GetNextSearchMatchAsync("doc/id", "session/id", new("term", 12));
        Assert.Equal("regex-v0", summary.RegexDialect);
        Assert.Contains("\"query\":\"private pattern\"", requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("\"expected_content_revision\":7", requests[0].Body, StringComparison.Ordinal);
        Assert.Contains("\"expected_highlighter_row_version\":4", requests[1].Body, StringComparison.Ordinal);
        Assert.Equal("/v1/reader/documents/doc%2Fid/search", requests[0].Path);
        Assert.EndsWith("/search/session%2Fid/results", requests[2].Path, StringComparison.Ordinal);
        Assert.Contains("\"after_index\":12", requests[4].Body, StringComparison.Ordinal);
    }

    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => response(request);
    }
    private sealed class Token : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<string?>("owner");
    }
}
