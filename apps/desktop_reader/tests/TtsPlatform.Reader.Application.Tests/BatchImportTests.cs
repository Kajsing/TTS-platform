using System.Text;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class BatchImportTests
{
    [Fact]
    public async Task Batch_import_continues_after_file_failure_and_uses_one_folder()
    {
        var client = new BatchClient();
        var runner = new BatchImportRunner(client);
        var inputs = new[]
        {
            Input("one.html"),
            new BatchImportInput(
                "broken.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "broken",
                () => throw new IOException("Unreadable test file.")),
            Input("three.txt"),
        };

        var result = await runner.RunAsync(
            inputs,
            new BatchImportOptions("folder-id"));

        Assert.Equal(2, result.Completed);
        Assert.Equal(1, result.Failed);
        Assert.Equal(0, result.Cancelled);
        Assert.Equal(["folder-id", "folder-id"], client.CommitFolderIds);
        Assert.Equal(["one.html", "three.txt"], client.PreviewedFiles);
        Assert.All(
            result.Files.Where(item => item.Status is BatchImportStatus.Completed),
            item => Assert.Equal("folder-id", item.Document?.FolderId));
    }

    [Fact]
    public async Task Cancelling_batch_keeps_committed_article_and_skips_remaining_files()
    {
        var client = new BatchClient();
        var runner = new BatchImportRunner(client);
        using var cancellation = new CancellationTokenSource();

        var result = await runner.RunAsync(
            [Input("one.txt"), Input("two.txt"), Input("three.txt")],
            new BatchImportOptions(),
            progress =>
            {
                if (progress.Status is BatchImportStatus.Completed)
                {
                    cancellation.Cancel();
                }
            },
            cancellation.Token);

        Assert.Equal(1, result.Completed);
        Assert.Equal(2, result.Cancelled);
        Assert.Single(client.CommitFolderIds);
        Assert.Single(client.PreviewedFiles);
    }

    private static BatchImportInput Input(string fileName) =>
        new(
            fileName,
            fileName.EndsWith(".html", StringComparison.OrdinalIgnoreCase)
                ? "text/html"
                : "text/plain",
            Path.GetFileNameWithoutExtension(fileName),
            () => new MemoryStream(Encoding.UTF8.GetBytes("Readable text.")));

    private sealed class BatchClient : IReaderServiceClient
    {
        public List<string> PreviewedFiles { get; } = [];
        public List<string?> CommitFolderIds { get; } = [];

        public Task<ReaderImportPreview> PreviewImportAsync(
            ImportDocumentRequest request,
            Stream content,
            CancellationToken cancellationToken = default)
        {
            PreviewedFiles.Add(request.FileName);
            var id = $"preview-{PreviewedFiles.Count}";
            return Task.FromResult(
                new ReaderImportPreview(
                    id,
                    request.Title ?? request.FileName,
                    request.FileName.EndsWith(".html", StringComparison.OrdinalIgnoreCase)
                        ? "html"
                        : "text_file",
                    request.FileName,
                    1,
                    1,
                    14,
                    request.FileName.EndsWith(".html", StringComparison.OrdinalIgnoreCase)
                        ? [new ReaderImportWarning("html_navigation_ignored", "Navigation ignored.", 1)]
                        : [],
                    [],
                    [],
                    false,
                    null,
                    600));
        }

        public Task<ReaderDocument> CommitImportToFolderAsync(
            string previewId,
            bool allowDuplicate = false,
            string? folderId = null,
            CancellationToken cancellationToken = default)
        {
            CommitFolderIds.Add(folderId);
            return Task.FromResult(Document(previewId, folderId));
        }

        public Task CancelImportAsync(
            string previewId,
            CancellationToken cancellationToken = default) => Task.CompletedTask;

        public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<ReaderCapabilities> GetCapabilitiesAsync(
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<ReaderDocument> CreateDocumentAsync(
            CreateDocumentRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DocumentPage> GetDocumentsAsync(
            int limit = 50,
            string? cursor = null,
            string? query = null,
            string? state = null,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<BlockPage> GetBlocksAsync(
            string documentId,
            int afterOrdinal = -1,
            int limit = 200,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> ReplaceContentAsync(
            string documentId,
            ReplaceContentRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> AppendContentAsync(
            string documentId,
            AppendContentRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> UndoAsync(
            string documentId,
            ExpectedVersionRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> RedoAsync(
            string documentId,
            ExpectedVersionRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition?> GetPositionAsync(
            string documentId,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderPosition> SavePositionAsync(
            string documentId,
            SavePositionRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<byte[]> SynthesizeAsync(
            EphemeralSynthesisRequest request,
            CancellationToken cancellationToken = default) => throw new NotSupportedException();

        private static ReaderDocument Document(string id, string? folderId) =>
            new(
                id,
                id,
                "text_file",
                null,
                null,
                null,
                null,
                "inbox",
                DateTimeOffset.UtcNow,
                DateTimeOffset.UtcNow,
                DateTimeOffset.UtcNow,
                null,
                1,
                1,
                1,
                1,
                14,
                JsonDocument.Parse("{}").RootElement.Clone(),
                folderId);
    }
}
