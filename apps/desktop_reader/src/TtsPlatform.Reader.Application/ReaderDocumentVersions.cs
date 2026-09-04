using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public static class ReaderDocumentVersions
{
    public static bool AreSame(ReaderDocument left, ReaderDocument right)
    {
        ArgumentNullException.ThrowIfNull(left);
        ArgumentNullException.ThrowIfNull(right);
        return string.Equals(left.Id, right.Id, StringComparison.Ordinal) &&
            left.RowVersion == right.RowVersion &&
            left.ContentRevision == right.ContentRevision;
    }

    public static ReaderDocument PreferNewest(
        ReaderDocument current,
        ReaderDocument candidate)
    {
        ArgumentNullException.ThrowIfNull(current);
        ArgumentNullException.ThrowIfNull(candidate);
        if (!string.Equals(current.Id, candidate.Id, StringComparison.Ordinal))
        {
            return candidate;
        }
        if (candidate.RowVersion != current.RowVersion)
        {
            return candidate.RowVersion > current.RowVersion ? candidate : current;
        }
        return candidate.ContentRevision >= current.ContentRevision ? candidate : current;
    }
}
