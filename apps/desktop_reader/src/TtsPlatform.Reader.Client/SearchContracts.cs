namespace TtsPlatform.Reader.Client;

public sealed record ReaderSearchRequest(int ExpectedContentRevision, string Query,
    bool CaseSensitive = false, bool WholeWord = false, bool UseRegex = false, int MaxResults = 10_000);
public sealed record ReaderHighlightSearchRequest(int ExpectedContentRevision, int ExpectedHighlighterRowVersion);
public sealed record ReaderSearchPageRequest(int Offset = 0, int Limit = 1000);
public sealed record ReaderSearchWindowRequest(int StartOrdinal, int EndOrdinal, int Limit = 2000);
public sealed record ReaderSearchNextRequest(string TermId, int AfterIndex = -1);
public sealed record ReaderSearchSummary(string SearchId, string DocumentId, int ContentRevision,
    string Kind, int TotalMatches, IReadOnlyDictionary<string, int> Counts, bool Truncated,
    string? Failure, string? RegexDialect, int ExpiresInSeconds);
public sealed record ReaderSearchHit(int Index, int Start, int Length, string? TermId,
    ReaderCursor StartCursor, ReaderCursor EndCursor);
public sealed record ReaderSearchPage(string DocumentId, int ContentRevision,
    IReadOnlyList<ReaderSearchHit> Matches, int? NextOffset, int TotalMatches, bool Truncated);
public sealed record ReaderSearchNext(ReaderSearchHit? Match);
