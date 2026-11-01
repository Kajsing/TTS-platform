using System.Net;
using System.Text;
using System.Text.Json;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class ImportPartsClientTests
{
    [Fact]
    public async Task Truncated_success_response_is_an_uncertain_result_and_is_not_retried()
    {
        var handler = new BrokenReply();
        var client = new ReaderServiceClient(new HttpClient(handler), "http://127.0.0.1:7777/", new Token());
        await Assert.ThrowsAsync<ReaderServiceUnavailableException>(() =>
            client.CommitImportPartsAsync("preview", "review"));
        Assert.Equal(1, handler.Calls);
    }

    private sealed class BrokenReply : HttpMessageHandler
    {
        public int Calls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.Created)
            { Content = new StringContent("{\"documents\":[", Encoding.UTF8, "application/json") });
        }
    }

    [Fact]
    public async Task Preview_and_commit_send_selected_policy_and_review_identity()
    {
        var handler = new Handler();
        var client = new ReaderServiceClient(new HttpClient(handler), "http://127.0.0.1:7777/", new Token());
        var preview = await client.PreviewImportPartsAsync("preview/id", 900000, 2);
        Assert.Equal("review", preview.PlanKey);
        Assert.Equal(2, preview.HeadingLevel);
        Assert.Equal(1, Assert.Single(preview.Parts).FirstChapter);
        var result = await client.CommitImportPartsAsync("preview/id", preview.PlanKey, 900000, 2, false, "folder");
        Assert.Empty(result.Documents);
        Assert.Equal(2, handler.Requests.Count);
        Assert.Equal("/v1/reader/imports/preview%2Fid/parts-preview", handler.Requests[0].Path);
        Assert.Equal("Bearer owner", handler.Requests[0].Authorization);
        using var body = JsonDocument.Parse(handler.Requests[1].Body);
        Assert.Equal("review", body.RootElement.GetProperty("plan_key").GetString());
        Assert.Equal(900000, body.RootElement.GetProperty("max_characters").GetInt32());
        Assert.Equal(2, body.RootElement.GetProperty("heading_level").GetInt32());
        Assert.Equal("folder", body.RootElement.GetProperty("folder_id").GetString());
        Assert.False(body.RootElement.GetProperty("allow_duplicate").GetBoolean());
    }

    [Theory]
    [InlineData(0, 1)]
    [InlineData(1000001, 1)]
    [InlineData(900000, 0)]
    [InlineData(900000, 10)]
    public async Task Invalid_policy_never_sends_a_request(int maximum, int level)
    {
        var handler = new Handler();
        var client = new ReaderServiceClient(new HttpClient(handler), "http://127.0.0.1:7777/", new Token());
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() => client.PreviewImportPartsAsync("preview", maximum, level));
        Assert.Empty(handler.Requests);
    }

    private sealed class Token : ITokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<string?>("owner");
    }

    private sealed class Handler : HttpMessageHandler
    {
        public List<(string Path, string Authorization, string Body)> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add((request.RequestUri!.AbsolutePath, request.Headers.Authorization!.ToString(), await request.Content!.ReadAsStringAsync(cancellationToken)));
            var json = request.RequestUri.AbsolutePath.EndsWith("parts-preview", StringComparison.Ordinal)
                ? """{"preview_id":"preview/id","plan_key":"review","max_characters":900000,"heading_level":2,"chapter_count":1,"parts":[{"number":1,"title":"Story","first_chapter":1,"last_chapter":1,"chapter_start_title":"One","chapter_end_title":"One","codepoints":30,"utf16_units":31,"blocks":2,"text_sha256":"hash"}],"can_commit":true,"issues":[]}"""
                : """{"documents":[]}""";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
        }
    }
}
