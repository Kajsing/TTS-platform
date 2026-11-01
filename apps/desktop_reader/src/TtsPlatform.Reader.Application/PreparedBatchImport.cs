using System.Text.Json;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record PreparedBatchImportOptions(
    int MaxCharacters = 900_000,
    int HeadingLevel = 1,
    string? FolderId = null,
    bool AllowDuplicate = false,
    bool CopySourceFile = false);

public enum PreparedBatchImportStatus
{
    Waiting, Previewing, Ready, Committing, Completed, Failed, Cancelled, OutcomeUnknown,
}

public sealed record PreparedBatchImportFile(
    BatchImportInput Input,
    PreparedBatchImportStatus Status,
    string Message = "",
    ReaderImportPreview? SourcePreview = null,
    ReaderImportPartsPreview? PartsPreview = null,
    IReadOnlyList<ReaderDocument>? ImportedDocuments = null)
{
    public IReadOnlyList<ReaderDocument> Documents => ImportedDocuments ?? [];
}

public sealed record PreparedBatchImportResult(IReadOnlyList<PreparedBatchImportFile> Files)
{
    public IReadOnlyList<ReaderDocument> Documents => Files.SelectMany(file => file.Documents).ToArray();
    public int Completed => Files.Count(file => file.Status == PreparedBatchImportStatus.Completed);
    public int Ready => Files.Count(file => file.Status == PreparedBatchImportStatus.Ready);
    public int Failed => Files.Count(file => file.Status == PreparedBatchImportStatus.Failed);
    public int Cancelled => Files.Count(file => file.Status == PreparedBatchImportStatus.Cancelled);
    public int Unknown => Files.Count(file => file.Status == PreparedBatchImportStatus.OutcomeUnknown);
}

/// <summary>Preparing never saves articles. Only an explicit reviewed commit can write.</summary>
public sealed class PreparedBatchImportRunner(IReaderServiceClient client)
{
    private readonly object _sync = new();
    private PreparedBatchImportFile[] _files = [];
    private PreparedBatchImportOptions? _options;
    private long _generation;
    private bool _busy;
    private bool _reviewed;

    public PreparedBatchImportResult Result
    {
        get { lock (_sync) { return new(_files.ToArray()); } }
    }

    public bool CanCommit(PreparedBatchImportOptions options)
    {
        lock (_sync)
        {
            return CanCommitCore(options);
        }
    }

    public async Task<PreparedBatchImportResult> PrepareAsync(
        IReadOnlyList<BatchImportInput> inputs,
        PreparedBatchImportOptions options,
        Action<PreparedBatchImportFile>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(inputs);
        ValidateOptions(options);
        if (inputs.Count is < 1 or > 100)
        {
            throw new ArgumentOutOfRangeException(nameof(inputs), "Select between 1 and 100 files.");
        }
        lock (_sync)
        {
            if (_busy) throw new InvalidOperationException("A batch operation is already running.");
            _busy = true;
        }
        try
        {
            await DiscardAsync().ConfigureAwait(true);
            long generation;
            lock (_sync)
            {
                var prior = _files;
                _files = inputs.Select(input => prior.FirstOrDefault(file =>
                    ReferenceEquals(file.Input, input) && file.Status is
                        PreparedBatchImportStatus.Completed or PreparedBatchImportStatus.OutcomeUnknown)
                    ?? new PreparedBatchImportFile(input, PreparedBatchImportStatus.Waiting)).ToArray();
                _options = options;
                generation = _generation;
            }
            for (var index = 0; index < inputs.Count; index++)
            {
                var file = Result.Files[index];
                if (file.Status is PreparedBatchImportStatus.Completed or PreparedBatchImportStatus.OutcomeUnknown)
                {
                    progress?.Invoke(file);
                    continue;
                }
                ReaderImportPreview? source = null;
                var retained = false;
                try
                {
                    CheckCurrent(generation, cancellationToken);
                    Publish(index, file with { Status = PreparedBatchImportStatus.Previewing }, progress);
                    await using var content = file.Input.OpenContent();
                    source = await client.PreviewImportAsync(
                        new ImportDocumentRequest(file.Input.FileName, file.Input.ContentType,
                            file.Input.Title, CopySourceFile: options.CopySourceFile),
                        content, cancellationToken).ConfigureAwait(true);
                    CheckCurrent(generation, cancellationToken);
                    var parts = await client.PreviewImportPartsAsync(source.PreviewId,
                        options.MaxCharacters, options.HeadingLevel, cancellationToken).ConfigureAwait(true);
                    CheckCurrent(generation, cancellationToken);
                    if (parts.PreviewId != source.PreviewId || parts.MaxCharacters != options.MaxCharacters ||
                        parts.HeadingLevel != options.HeadingLevel || string.IsNullOrWhiteSpace(parts.PlanKey) ||
                        parts.Parts is null || parts.Issues is null || parts.Parts.Count > 100)
                    {
                        throw new ReaderServiceUnavailableException("The service returned a mismatched preview. Preview parts again.");
                    }
                    file = file with
                    {
                        Status = parts.CanCommit && parts.Parts.Count > 0
                            ? PreparedBatchImportStatus.Ready : PreparedBatchImportStatus.Failed,
                        SourcePreview = source,
                        PartsPreview = parts,
                        Message = DescribePreview(source, parts),
                    };
                    lock (_sync)
                    {
                        if (generation != _generation) throw new OperationCanceledException();
                        _files[index] = file;
                        retained = file.Status == PreparedBatchImportStatus.Ready;
                    }
                    progress?.Invoke(file);
                }
                catch (OperationCanceledException)
                {
                    Publish(index, new(file.Input, PreparedBatchImportStatus.Cancelled,
                        "Preview cancelled or options changed. Nothing was imported."), progress);
                }
                catch (Exception exception) when (IsExpected(exception))
                {
                    Publish(index, new(file.Input, PreparedBatchImportStatus.Failed,
                        DescribeFailure(exception)), progress);
                }
                finally
                {
                    if (source is not null && !retained)
                    {
                        await DiscardOneAsync(source.PreviewId).ConfigureAwait(true);
                    }
                }
            }
            if (cancellationToken.IsCancellationRequested)
            {
                await DiscardAsync().ConfigureAwait(true);
                lock (_sync)
                {
                    _files = _files.Select(file => file.Status == PreparedBatchImportStatus.Waiting
                        ? file with
                        {
                            Status = PreparedBatchImportStatus.Cancelled,
                            Message = "Preview cancelled. Nothing was imported."
                        } : file).ToArray();
                }
            }
            lock (_sync)
            {
                _reviewed = generation == _generation && _files.Any(file =>
                    file.Status == PreparedBatchImportStatus.Ready);
            }
            return Result;
        }
        finally
        {
            lock (_sync) { _busy = false; }
        }
    }

    public async Task<PreparedBatchImportResult> CommitAsync(
        PreparedBatchImportOptions options,
        Action<PreparedBatchImportFile>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ValidateOptions(options);
        long generation;
        lock (_sync)
        {
            if (!CanCommitCore(options))
            {
                throw new InvalidOperationException("Preview the current options and approve duplicate content before importing.");
            }
            _busy = true;
            _reviewed = false;
            generation = _generation;
        }
        var stop = false;
        try
        {
            var files = Result.Files;
            for (var index = 0; index < files.Count; index++)
            {
                var file = files[index];
                if (file.Status != PreparedBatchImportStatus.Ready) continue;
                var sent = false;
                try
                {
                    if (stop || cancellationToken.IsCancellationRequested)
                    {
                        Publish(index, file with
                        {
                            Status = PreparedBatchImportStatus.Cancelled,
                            Message = "Skipped before import. Previously acknowledged articles were kept.",
                            SourcePreview = null,
                            PartsPreview = null
                        }, progress);
                        continue;
                    }
                    CheckCurrent(generation, cancellationToken);
                    Publish(index, file with { Status = PreparedBatchImportStatus.Committing }, progress);
                    CheckCurrent(generation, cancellationToken);
                    sent = true;
                    var result = await client.CommitImportPartsAsync(file.SourcePreview!.PreviewId,
                        file.PartsPreview!.PlanKey, options.MaxCharacters, options.HeadingLevel,
                        options.AllowDuplicate, options.FolderId, cancellationToken).ConfigureAwait(true);
                    if (result.Documents is null || result.Documents.Count != file.PartsPreview.Parts.Count ||
                        result.Documents.Any(document => document is null || string.IsNullOrWhiteSpace(document.Id)) ||
                        result.Documents.Select(document => document.Id).Distinct(StringComparer.Ordinal).Count() != result.Documents.Count)
                    {
                        throw new ReaderServiceUnavailableException("The service response did not acknowledge every reviewed part.");
                    }
                    Publish(index, file with
                    {
                        Status = PreparedBatchImportStatus.Completed,
                        Message = $"Imported {result.Documents.Count:N0} reviewed part(s).",
                        ImportedDocuments = result.Documents,
                        SourcePreview = null,
                        PartsPreview = null
                    }, progress);
                }
                catch (Exception exception) when (exception is OperationCanceledException || IsExpected(exception))
                {
                    var unknown = sent && (exception is OperationCanceledException or IOException or
                        ReaderServiceUnavailableException or HttpRequestException or JsonException ||
                        exception is ReaderApiException { StatusCode: >= 500 });
                    stop |= unknown || exception is OperationCanceledException;
                    Publish(index, file with
                    {
                        Status = unknown ? PreparedBatchImportStatus.OutcomeUnknown :
                            exception is OperationCanceledException ? PreparedBatchImportStatus.Cancelled :
                            PreparedBatchImportStatus.Failed,
                        Message = unknown
                            ? "Import outcome is unknown; this file may already be saved. Refresh the library and check before importing it again."
                            : DescribeFailure(exception),
                        SourcePreview = null,
                        PartsPreview = null,
                    }, progress);
                }
                finally
                {
                    await DiscardOneAsync(file.SourcePreview!.PreviewId).ConfigureAwait(true);
                }
            }
            return Result;
        }
        finally
        {
            lock (_sync) { _busy = false; _options = null; }
        }
    }

    /// <summary>Invalidate synchronously before awaiting cleanup, fencing late preview replies.</summary>
    public async Task DiscardAsync()
    {
        string[] previews;
        lock (_sync)
        {
            _generation++;
            _reviewed = false;
            _options = null;
            previews = _files.Where(file => file.SourcePreview is not null)
                .Select(file => file.SourcePreview!.PreviewId).Distinct(StringComparer.Ordinal).ToArray();
            _files = _files.Select(file => file.Status == PreparedBatchImportStatus.Ready
                ? file with
                {
                    Status = PreparedBatchImportStatus.Waiting,
                    Message = "Options changed. Preview parts again.",
                    SourcePreview = null,
                    PartsPreview = null
                }
                : file with { SourcePreview = null, PartsPreview = null }).ToArray();
        }
        foreach (var preview in previews) await DiscardOneAsync(preview).ConfigureAwait(true);
    }

    private bool CanCommitCore(PreparedBatchImportOptions options) =>
        !_busy && _reviewed && options == _options &&
        _files.Any(file => file.Status == PreparedBatchImportStatus.Ready) &&
        (options.AllowDuplicate || !_files.Any(file => file.Status == PreparedBatchImportStatus.Ready &&
            file.SourcePreview?.DuplicateDocumentId is not null));

    private void CheckCurrent(long generation, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        lock (_sync)
        {
            if (generation != _generation) throw new OperationCanceledException();
        }
    }

    private void Publish(int index, PreparedBatchImportFile file, Action<PreparedBatchImportFile>? progress)
    {
        lock (_sync) { _files[index] = file; }
        progress?.Invoke(file);
    }

    private async Task DiscardOneAsync(string previewId)
    {
        try
        {
            await client.CancelImportAsync(previewId, CancellationToken.None).ConfigureAwait(true);
        }
        catch (Exception exception) when (IsExpected(exception) || exception is OperationCanceledException)
        {
            // Best-effort preview cleanup never changes an acknowledged or uncertain write outcome.
        }
    }

    private static bool IsExpected(Exception exception) => exception is IOException or
        UnauthorizedAccessException or ReaderApiException or ReaderServiceUnavailableException or
        ReaderTokenUnavailableException or HttpRequestException or NotSupportedException or JsonException;

    private static string DescribeFailure(Exception exception) => exception switch
    {
        ReaderApiException { StatusCode: 400 or 404 } =>
            "Preview expired or is no longer available. Preview parts again; update the service if this continues.",
        ReaderApiException { StatusCode: 409 } =>
            "The reviewed plan changed or content already exists. Check the library and preview parts again.",
        NotSupportedException => "Part previews require an updated Reader service.",
        OperationCanceledException => "Skipped before import. Previously acknowledged articles were kept.",
        _ => exception.Message,
    };

    private static string DescribePreview(ReaderImportPreview source, ReaderImportPartsPreview parts)
    {
        var warnings = string.Join(" ", source.Warnings.Take(3).Select(warning => warning.Message));
        var duplicate = source.DuplicateDocumentId is null ? "" : " Duplicate content: explicit approval required.";
        var issues = string.Join(" ", parts.Issues.Take(3));
        return $"{parts.Parts.Count:N0} part(s), {parts.ChapterCount:N0} chapter(s). {warnings}{duplicate} {issues}".Trim();
    }

    private static void ValidateOptions(PreparedBatchImportOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (options.MaxCharacters is < 1 or > 1_000_000)
            throw new ArgumentOutOfRangeException(nameof(options), "Characters per part must be between 1 and 1,000,000.");
        if (options.HeadingLevel is < 1 or > 9)
            throw new ArgumentOutOfRangeException(nameof(options), "Chapter heading level must be between 1 and 9.");
    }
}
