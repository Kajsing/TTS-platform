namespace TtsPlatform.Reader.Client;

public sealed record ReaderAgentGrant(
    string Id,
    string FolderId,
    string Name,
    IReadOnlyList<string> Operations,
    DateTimeOffset CreatedAt,
    DateTimeOffset? RevokedAt)
{
    public string Status => RevokedAt is null ? "Active" : "Revoked";
}

public sealed record ReaderAgentGrantPage(IReadOnlyList<ReaderAgentGrant> Grants);

public sealed record ReaderAgentGrantRequest(string FolderId, string Name);

public sealed record ReaderAgentProvisionResult(ReaderAgentGrant Grant, string Credential)
{
    public override string ToString() => $"ReaderAgentProvisionResult {{ GrantId = {Grant.Id}, Credential = [protected] }}";
}
