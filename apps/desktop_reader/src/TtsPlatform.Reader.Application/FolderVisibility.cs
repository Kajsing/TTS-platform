namespace TtsPlatform.Reader.Application;

// Presentation preference only. Never changes service permissions or Privacy locks.
public static class FolderVisibility
{
    private static string WorkspaceKey(DesktopSettings settings) =>
        $"{settings.ActiveConnection.Id}|{new Uri(settings.ActiveConnection.ServiceBaseUrl).AbsoluteUri}";

    public static IReadOnlyList<string> ClosedFolderIds(DesktopSettings settings) =>
        settings.ClosedFolderIdsByWorkspace?.GetValueOrDefault(WorkspaceKey(settings)) ?? [];

    public static bool IsOpen(DesktopSettings settings, string? folderId) =>
        folderId is null || !ClosedFolderIds(settings).Contains(folderId, StringComparer.Ordinal);

    public static DesktopSettings SetOpen(DesktopSettings settings, string folderId, bool isOpen)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folderId);
        var workspaces = new Dictionary<string, string[]>(
            settings.ClosedFolderIdsByWorkspace ?? new Dictionary<string, string[]>(),
            StringComparer.Ordinal);
        var closed = new HashSet<string>(ClosedFolderIds(settings), StringComparer.Ordinal);
        if (isOpen)
        {
            closed.Remove(folderId);
        }
        else
        {
            closed.Add(folderId);
        }
        var key = WorkspaceKey(settings);
        if (closed.Count == 0)
        {
            workspaces.Remove(key);
        }
        else
        {
            workspaces[key] = closed.Order(StringComparer.Ordinal).ToArray();
        }
        return settings with { ClosedFolderIdsByWorkspace = workspaces };
    }
}
