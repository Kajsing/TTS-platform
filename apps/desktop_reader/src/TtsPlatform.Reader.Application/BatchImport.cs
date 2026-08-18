using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public enum BatchImportStatus
{
    Waiting,
    Previewing,
    Committing,
    Completed,
    Failed,
    Cancelled,
}

public sealed record BatchImportInput(
    string FileName,
    string ContentType,
    string Title,
    Func<Stream> OpenContent);

public sealed record BatchImportProgress(
    BatchImportInput Input,
    BatchImportStatus Status,
    int WarningCount = 0,
    string Message = "",
    ReaderDocument? Document = null);

public sealed record BatchImportOptions(
    string? FolderId = null,
    bool AllowDuplicate = false,
    bool CopySourceFile = false);

public sealed record BatchImportResult(IReadOnlyList<BatchImportProgress> Files)
{
    public int Completed => Files.Count(item => item.Status is BatchImportStatus.Completed);
    public int Failed => Files.Count(item => item.Status is BatchImportStatus.Failed);
    public int Cancelled => Files.Count(item => item.Status is BatchImportStatus.Cancelled);
}

public sealed class BatchImportRunner(IReaderServiceClient client, int maximumFiles = 100)
{
    public async Task<BatchImportResult> RunAsync(
        IReadOnlyList<BatchImportInput> inputs,
        BatchImportOptions options,
        Action<BatchImportProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(inputs);
        ArgumentNullException.ThrowIfNull(options);
        if (inputs.Count is 0 || inputs.Count > maximumFiles)
        {
            throw new ArgumentOutOfRangeException(
                nameof(inputs),
                $"A batch must contain 1 through {maximumFiles} files.");
        }

        var results = new List<BatchImportProgress>(inputs.Count);
        foreach (var input in inputs)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                AddResult(
                    results,
                    new BatchImportProgress(
                        input,
                        BatchImportStatus.Cancelled,
                        Message: "Cancelled before import."),
                    progress);
                continue;
            }

            ReaderImportPreview? preview = null;
            try
            {
                progress?.Invoke(new BatchImportProgress(input, BatchImportStatus.Previewing));
                await using var content = input.OpenContent();
                preview = await client.PreviewImportAsync(
                    new ImportDocumentRequest(
                        input.FileName,
                        input.ContentType,
                        input.Title,
                        CopySourceFile: options.CopySourceFile),
                    content,
                    cancellationToken).ConfigureAwait(true);
                if (cancellationToken.IsCancellationRequested)
                {
                    await DiscardPreviewAsync(preview.PreviewId).ConfigureAwait(true);
                    AddResult(
                        results,
                        new BatchImportProgress(
                            input,
                            BatchImportStatus.Cancelled,
                            preview.Warnings.Count,
                            "Cancelled before the article was saved."),
                        progress);
                    continue;
                }

                progress?.Invoke(
                    new BatchImportProgress(
                        input,
                        BatchImportStatus.Committing,
                        preview.Warnings.Count,
                        DescribeWarnings(preview)));
                var document = await client.CommitImportToFolderAsync(
                    preview.PreviewId,
                    options.AllowDuplicate,
                    options.FolderId,
                    cancellationToken).ConfigureAwait(true);
                AddResult(
                    results,
                    new BatchImportProgress(
                        input,
                        BatchImportStatus.Completed,
                        preview.Warnings.Count,
                        DescribeWarnings(preview),
                        document),
                    progress);
                preview = null;
            }
            catch (OperationCanceledException)
            {
                if (preview is not null)
                {
                    await DiscardPreviewAsync(preview.PreviewId).ConfigureAwait(true);
                }
                AddResult(
                    results,
                    new BatchImportProgress(
                        input,
                        BatchImportStatus.Cancelled,
                        preview?.Warnings.Count ?? 0,
                        "Cancelled before the article was saved."),
                    progress);
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException or
                    ReaderApiException or ReaderServiceUnavailableException)
            {
                if (preview is not null)
                {
                    await DiscardPreviewAsync(preview.PreviewId).ConfigureAwait(true);
                }
                AddResult(
                    results,
                    new BatchImportProgress(
                        input,
                        BatchImportStatus.Failed,
                        preview?.Warnings.Count ?? 0,
                        exception.Message),
                    progress);
            }
        }
        return new BatchImportResult(results);
    }

    private async Task DiscardPreviewAsync(string previewId)
    {
        try
        {
            await client.CancelImportAsync(previewId, CancellationToken.None).ConfigureAwait(true);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            _ = exception;
        }
    }

    private static void AddResult(
        ICollection<BatchImportProgress> results,
        BatchImportProgress item,
        Action<BatchImportProgress>? progress)
    {
        results.Add(item);
        progress?.Invoke(item);
    }

    private static string DescribeWarnings(ReaderImportPreview preview) =>
        preview.Warnings.Count == 0
            ? "No warnings."
            : string.Join(
                " ",
                preview.Warnings.Take(3).Select(warning => $"{warning.Message} ({warning.Count})"));
}
