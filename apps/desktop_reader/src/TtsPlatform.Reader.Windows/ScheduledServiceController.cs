namespace TtsPlatform.Reader.Windows;

// Installation discovery only. Mutations use the activity-aware coordinator.
public static class ScheduledServiceController
{
    public const string TaskName = "TTS Platform Local Reader";
    public static bool OwnsRunningService
    {
        get
        {
            var launcher = FindLocalServiceLauncher(AppContext.BaseDirectory);
            if (launcher is null) return false;
            var store = new ReaderServiceProcessLeaseStore(DesktopPaths.ServiceProcessLeasePath);
            if (!store.TryOpenVerified(launcher.FullName, LocalServiceProcessControl.PowerShellPath, out var owner, out _))
                return false;
            owner!.Dispose();
            return true;
        }
    }

    public static FileInfo? FindLocalServiceLauncher(string startDirectory)
    {
        if (string.IsNullOrWhiteSpace(startDirectory))
        {
            return null;
        }

        var current = new DirectoryInfo(Path.GetFullPath(startDirectory));
        for (var depth = 0; depth < 12 && current is not null; depth++, current = current.Parent)
        {
            var candidate = new FileInfo(
                Path.Combine(current.FullName, "scripts", "windows", "run_service.ps1"));
            if (candidate.Exists)
            {
                return candidate;
            }
        }
        return null;
    }
}
