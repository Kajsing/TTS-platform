using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record EditorSaveResult(
    bool Saved,
    bool Conflict,
    string? Message = null,
    ContinuousRangeDeletion? AppliedRangeDeletion = null);

public sealed class DocumentEditor(IReaderServiceClient client)
{
    public ReaderDocument? Document { get; private set; }
    public ReaderBlock? Block { get; private set; }
    public string OriginalText { get; private set; } = string.Empty;
    public string WorkingText { get; private set; } = string.Empty;
    public ContinuousRangeDeletion? PendingRangeDeletion { get; private set; }
    public string? LastError { get; private set; }
    public bool IsEditable => Document?.IsEditable == true && Block is not null;
    public bool HasUnsavedChanges => IsEditable && (
        PendingRangeDeletion is not null ||
        !string.Equals(WorkingText, OriginalText, StringComparison.Ordinal));

    public async Task LoadAsync(ReaderDocument document, CancellationToken cancellationToken = default)
    {
        var page = await client.GetBlocksAsync(document.Id, limit: 1, cancellationToken: cancellationToken)
            .ConfigureAwait(false);
        LoadBlock(document, page.Blocks.FirstOrDefault());
    }

    public void LoadBlock(ReaderDocument document, ReaderBlock? block)
    {
        if (block is not null && !string.Equals(block.DocumentId, document.Id, StringComparison.Ordinal))
        {
            throw new ArgumentException("The selected block does not belong to the document.", nameof(block));
        }

        Document = document;
        LastError = null;
        Block = block;
        OriginalText = Block?.Text ?? string.Empty;
        WorkingText = OriginalText;
        PendingRangeDeletion = null;
    }

    public void Clear()
    {
        Document = null;
        Block = null;
        OriginalText = string.Empty;
        WorkingText = string.Empty;
        PendingRangeDeletion = null;
        LastError = null;
    }

    public async Task<EditorSaveResult> RenameAsync(
        string title,
        CancellationToken cancellationToken = default)
    {
        if (Document is null)
        {
            return new EditorSaveResult(false, false, "Select a document before renaming it.");
        }

        var normalized = title.Trim();
        if (normalized.Length is < 1 or > 500)
        {
            return new EditorSaveResult(false, false, "The title must contain 1 to 500 characters.");
        }
        if (string.Equals(normalized, Document.Title, StringComparison.Ordinal))
        {
            return new EditorSaveResult(false, false);
        }

        try
        {
            Document = await client.UpdateDocumentAsync(
                Document.Id,
                new UpdateDocumentRequest(Document.RowVersion, Title: normalized),
                cancellationToken).ConfigureAwait(false);
            LastError = null;
            return new EditorSaveResult(true, false);
        }
        catch (ReaderApiException exception) when (exception.ErrorType == "reader_revision_conflict")
        {
            LastError = "The document changed elsewhere. Reload it before renaming.";
            return new EditorSaveResult(false, true, LastError);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            LastError = exception.Message;
            return new EditorSaveResult(false, false, LastError);
        }
    }

    public void SetWorkingText(string text)
    {
        if (!IsEditable)
        {
            return;
        }

        WorkingText = text;
        PendingRangeDeletion = null;
    }

    public void SetRangeDeletion(ContinuousRangeDeletion deletion)
    {
        ArgumentNullException.ThrowIfNull(deletion);
        if (!IsEditable || Block is null ||
            !string.Equals(Block.Id, deletion.StartBlock.Id, StringComparison.Ordinal))
        {
            return;
        }

        PendingRangeDeletion = deletion;
        WorkingText = deletion.ResultingStartBlockText;
    }

    public void RevertLocalChanges()
    {
        WorkingText = OriginalText;
        PendingRangeDeletion = null;
        LastError = null;
    }

    public async Task<EditorSaveResult> SaveAsync(CancellationToken cancellationToken = default)
    {
        if (Document is null || Block is null || !Document.IsEditable)
        {
            return new EditorSaveResult(false, false, "This document source is read-only.");
        }

        if (!HasUnsavedChanges)
        {
            return new EditorSaveResult(false, false);
        }

        try
        {
            var rangeDeletion = PendingRangeDeletion;
            var response = await client.ReplaceContentAsync(
                Document.Id,
                new ReplaceContentRequest(
                    Document.RowVersion,
                    Block.Id,
                    rangeDeletion?.StartOffset ?? 0,
                    rangeDeletion?.EndOffset ?? OriginalText.Length,
                    rangeDeletion is null ? WorkingText : string.Empty,
                    rangeDeletion?.EndBlock.Id),
                cancellationToken).ConfigureAwait(false);
            Document = response.Document;
            Block = Block with
            {
                Text = WorkingText,
                CharacterCount = WorkingText.Length,
                RowVersion = Block.RowVersion + 1,
            };
            OriginalText = WorkingText;
            PendingRangeDeletion = null;
            LastError = null;
            return new EditorSaveResult(
                true,
                false,
                AppliedRangeDeletion: rangeDeletion);
        }
        catch (ReaderApiException exception) when (exception.ErrorType == "reader_revision_conflict")
        {
            LastError = "The document changed elsewhere. Your unsaved text is preserved; reload before retrying.";
            return new EditorSaveResult(false, true, LastError);
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            LastError = exception.Message;
            return new EditorSaveResult(false, false, LastError);
        }
    }

    public Task<EditorSaveResult> UndoAsync(CancellationToken cancellationToken = default) =>
        ApplyHistoryAsync(undo: true, cancellationToken);

    public Task<EditorSaveResult> RedoAsync(CancellationToken cancellationToken = default) =>
        ApplyHistoryAsync(undo: false, cancellationToken);

    private async Task<EditorSaveResult> ApplyHistoryAsync(bool undo, CancellationToken cancellationToken)
    {
        if (Document is null || Block is null || !Document.IsEditable)
        {
            return new EditorSaveResult(false, false, "This document source is read-only.");
        }

        if (HasUnsavedChanges)
        {
            return new EditorSaveResult(
                false,
                false,
                "Save or revert the current local edit before using document Undo or Redo.");
        }

        try
        {
            var request = new ExpectedVersionRequest(Document.RowVersion);
            var mutation = undo
                ? await client.UndoAsync(Document.Id, request, cancellationToken).ConfigureAwait(false)
                : await client.RedoAsync(Document.Id, request, cancellationToken).ConfigureAwait(false);
            var page = await client.GetBlocksAsync(Document.Id, limit: 1, cancellationToken: cancellationToken)
                .ConfigureAwait(false);
            Document = mutation.Document;
            Block = page.Blocks.FirstOrDefault();
            OriginalText = Block?.Text ?? string.Empty;
            WorkingText = OriginalText;
            LastError = null;
            return new EditorSaveResult(true, false);
        }
        catch (ReaderApiException exception) when (exception.ErrorType == "reader_revision_conflict")
        {
            LastError = "The document changed elsewhere. Reload it before using Undo or Redo.";
            return new EditorSaveResult(false, true, LastError);
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            LastError = exception.Message;
            return new EditorSaveResult(false, false, LastError);
        }
    }
}
