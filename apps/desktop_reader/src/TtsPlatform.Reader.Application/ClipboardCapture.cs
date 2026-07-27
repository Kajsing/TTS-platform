using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public enum ClipboardCaptureAction
{
    ReadNow,
    AppendToOpenDocument,
    CreateNewDocument,
    SaveToInbox,
    Ignore,
    AlwaysIgnoreApplication,
}

public sealed record ClipboardCaptureResult(
    bool Succeeded,
    string Message,
    ReaderDocument? Document = null,
    bool OpenDocument = false,
    string? DuplicateDocumentId = null);

public sealed class ClipboardDocumentCapture(IReaderServiceClient client)
{
    public async Task<ClipboardCaptureResult> AppendAsync(
        string text,
        ReaderDocument? openDocument,
        CancellationToken cancellationToken = default)
    {
        ValidateText(text);
        if (openDocument is null || !openDocument.IsEditable)
        {
            return new ClipboardCaptureResult(
                false,
                "Open an editable text document before appending clipboard text.");
        }

        try
        {
            var mutation = await client.AppendContentAsync(
                openDocument.Id,
                new AppendContentRequest(openDocument.RowVersion, text),
                cancellationToken).ConfigureAwait(false);
            return new ClipboardCaptureResult(
                true,
                "Clipboard text appended as one undoable paragraph.",
                mutation.Document,
                OpenDocument: true);
        }
        catch (ReaderApiException exception) when (exception.ErrorType == "reader_document_locked")
        {
            return new ClipboardCaptureResult(
                false,
                "Pause or stop playback before appending to the open document.");
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            return new ClipboardCaptureResult(false, exception.Message);
        }
    }

    public async Task<ClipboardCaptureResult> CreateAsync(
        string text,
        bool openDocument,
        bool allowDuplicate = false,
        CancellationToken cancellationToken = default)
    {
        ValidateText(text);
        try
        {
            var document = await client.CreateDocumentAsync(
                new CreateDocumentRequest(
                    $"Clipboard {DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}",
                    "clipboard",
                    text,
                    AllowDuplicate: allowDuplicate),
                cancellationToken).ConfigureAwait(false);
            return new ClipboardCaptureResult(
                true,
                openDocument
                    ? "A new editable clipboard document was created."
                    : "Clipboard text was saved to Inbox.",
                document,
                OpenDocument: openDocument);
        }
        catch (ReaderApiException exception) when (
            exception.ErrorType == "reader_duplicate_document")
        {
            exception.Details.TryGetValue("document_id", out var documentId);
            return new ClipboardCaptureResult(
                false,
                "Identical clipboard text is already saved.",
                DuplicateDocumentId: documentId as string);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            return new ClipboardCaptureResult(false, exception.Message);
        }
    }

    public async Task<ClipboardCaptureResult> OpenExistingAsync(
        string documentId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        try
        {
            var document = await client.GetDocumentAsync(documentId, cancellationToken)
                .ConfigureAwait(false);
            return new ClipboardCaptureResult(
                true,
                "Opened the existing clipboard document.",
                document,
                OpenDocument: true);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            return new ClipboardCaptureResult(false, exception.Message);
        }
    }

    private static void ValidateText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            throw new ArgumentException("Clipboard text must not be empty.", nameof(text));
        }
    }
}

public static class EphemeralTextChunker
{
    public const int MaximumCharactersPerRequest = 800;

    public static IReadOnlyList<string> Chunk(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return [];
        }

        var chunks = new List<string>();
        var remaining = text.Trim();
        while (remaining.Length > MaximumCharactersPerRequest)
        {
            var splitAt = remaining.LastIndexOf(
                ' ',
                MaximumCharactersPerRequest - 1,
                MaximumCharactersPerRequest);
            if (splitAt <= 0)
            {
                splitAt = MaximumCharactersPerRequest;
            }
            chunks.Add(remaining[..splitAt].Trim());
            remaining = remaining[splitAt..].TrimStart();
        }
        if (remaining.Length > 0)
        {
            chunks.Add(remaining);
        }
        return chunks;
    }
}
