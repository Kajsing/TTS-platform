using System.Globalization;

namespace TtsPlatform.Reader.Client;

public sealed partial class ReaderServiceClient
{
    public Task<ReaderChapterIndex> GetChapterIndexAsync(string documentId, int expectedContentRevision,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(documentId);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(expectedContentRevision);
        return SendAsync<ReaderChapterIndex>(HttpMethod.Get,
            $"v1/reader/documents/{Uri.EscapeDataString(documentId)}/chapters?expected_content_revision=" +
            expectedContentRevision.ToString(CultureInfo.InvariantCulture), true, null, cancellationToken);
    }
}
