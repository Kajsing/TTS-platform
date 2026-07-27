using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public sealed record EditorSaveResult(bool Saved, bool Conflict, string? Message = null);

public sealed class DocumentEditor(IReaderServiceClient client)
{
    public ReaderDocument? Document { get; private set; }
    public ReaderBlock? Block { get; private set; }
    public string OriginalText { get; private set; } = string.Empty;
    public string WorkingText { get; private set; } = string.Empty;
    public string? LastError { get; private set; }
    public bool IsEditable => Document?.IsEditable == true && Block is not null;
    public bool HasUnsavedChanges => IsEditable && !string.Equals(WorkingText, OriginalText, StringComparison.Ordinal);

    public async Task LoadAsync(ReaderDocument document, CancellationToken cancellationToken = default)
    {
        Document = document;
        LastError = null;
        var page = await client.GetBlocksAsync(document.Id, cancellationToken: cancellationToken)
            .ConfigureAwait(false);
        Block = page.Blocks.FirstOrDefault();
        OriginalText = Block?.Text ?? string.Empty;
        WorkingText = OriginalText;
    }

    public void SetWorkingText(string text)
    {
        if (!IsEditable)
        {
            return;
        }

        WorkingText = text;
    }

    public void RevertLocalChanges()
    {
        WorkingText = OriginalText;
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
            var response = await client.ReplaceContentAsync(
                Document.Id,
                new ReplaceContentRequest(
                    Document.RowVersion,
                    Block.Id,
                    0,
                    OriginalText.Length,
                    WorkingText),
                cancellationToken).ConfigureAwait(false);
            Document = response.Document;
            Block = Block with
            {
                Text = WorkingText,
                CharacterCount = WorkingText.Length,
                RowVersion = Block.RowVersion + 1,
            };
            OriginalText = WorkingText;
            LastError = null;
            return new EditorSaveResult(true, false);
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
            var page = await client.GetBlocksAsync(Document.Id, cancellationToken: cancellationToken)
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
