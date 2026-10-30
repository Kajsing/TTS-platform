using System.Net;
using System.Text;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class ChapterClientTests
{
    [Fact]
    public async Task Chapter_index_is_a_fresh_authenticated_get_with_explicit_codepoint_anchors()
    {
        var calls = 0;
        var handler = new Handler(request =>
        {
            calls++;
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("/v1/reader/documents/doc%2Fid/chapters", request.RequestUri!.AbsolutePath);
            Assert.Equal("?expected_content_revision=7", request.RequestUri.Query);
            Assert.Null(request.Content);
            Assert.Equal("Bearer owner", request.Headers.Authorization!.ToString());
            Assert.Equal("privacy", Assert.Single(request.Headers.GetValues(ReaderPrivacySessionStore.HeaderName)));
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""
                    {"document_id":"doc/id","content_revision":7,"chapters":[
                      {"id":"root","title":"Chapter 😀","block_id":"block/id","block_ordinal":90,"codepoint_offset":2}
                    ]}
                    """, Encoding.UTF8, "application/json")
            };
        });
        using var privacy = new ReaderPrivacySessionStore();
        privacy.Store(new("folder", "privacy", DateTimeOffset.UtcNow.AddMinutes(5), 300));
        using var http = new HttpClient(handler);
        IReaderServiceClient client = new ReaderServiceClient(http, "http://localhost:7777", new Token(), privacy);
        var first = await client.GetChapterIndexAsync("doc/id", 7);
        var second = await client.GetChapterIndexAsync("doc/id", 7);
        Assert.Equal(2, calls);
        Assert.NotSame(first, second);
        Assert.Equal("doc/id", first.DocumentId);
        Assert.Equal(7, first.ContentRevision);
        var anchor = Assert.Single(first.Chapters);
        Assert.Equal(2, anchor.CodepointOffset);
        Assert.Equal(90, anchor.BlockOrdinal);
        Assert.Equal("block/id", anchor.BlockId);
        Assert.Equal("Chapter 😀", anchor.ToString());
    }

    [Theory]
    [InlineData("", 1)]
    [InlineData(" ", 1)]
    [InlineData(null, 1)]
    [InlineData("doc", 0)]
    [InlineData("doc", -1)]
    public async Task Chapter_index_validates_identity_and_positive_revision_before_http(string? documentId, int revision)
    {
        using var http = new HttpClient(new Handler(_ => throw new InvalidOperationException("Unexpected HTTP request.")));
        var client = new ReaderServiceClient(http, "http://localhost:7777", new Token());
        await Assert.ThrowsAnyAsync<ArgumentException>(() => client.GetChapterIndexAsync(documentId!, revision));
    }

    [Fact]
    public async Task Chapter_index_honors_caller_cancellation()
    {
        using var http = new HttpClient(new Handler(_ => throw new InvalidOperationException("Unexpected HTTP request.")));
        var client = new ReaderServiceClient(http, "http://localhost:7777", new Token());
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            client.GetChapterIndexAsync("doc", 7, cancellation.Token));
    }

    private sealed class Handler(Func<HttpRequestMessage, HttpResponseMessage> response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return Task.FromResult(response(request));
        }
    }

    private sealed class Token : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<string?>("owner");
    }
}
