using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Xml;
using System.Xml.Linq;
using Microsoft.Win32.SafeHandles;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Windows;

// Compatibility with the existing per-user CLI tasks. No registration is edited,
// and only an exact running task action can be stopped (never a shared host).
public sealed class LegacyServiceTasks(string startDirectory, string userSid, int port,
    Func<IReadOnlyList<StartupTaskRecord>>? readTasks = null)
{
    private static readonly XNamespace Ns = "http://schemas.microsoft.com/windows/2004/02/mit/task";
    private VerifiedTask? _verified;
    private StartupTaskRecord? _restartTask;
    private sealed record VerifiedTask(StartupTaskRecord Record, string Instance, int LauncherPid,
        long LauncherStart, int ServicePid, long ServiceStart);
    private string? Launcher => ScheduledServiceController.FindLocalServiceLauncher(startDirectory)?.FullName;

    public IReadOnlyList<StartupTaskRecord> ReadStartupConflicts() => ReadKnownTasks()
        .Where(task => task.Enabled && HasAutomaticTrigger(task.Xml)).ToArray();

    private IReadOnlyList<StartupTaskRecord> ReadKnownTasks()
    {
        var launcher = Launcher;
        if (launcher is null) return [];
        return (readTasks?.Invoke() ?? ReadTasks()).Where(task => IsKnownLauncher(task.Xml, launcher, userSid)).ToArray();
    }

    public ServiceCommandResult VerifyOwner(LocalServiceStatus status)
    {
        _verified = null;
        _restartTask = null;
        try
        {
            using var service = Process.GetProcessById(status.Resources.ProcessId);
            _ = service.Handle;
            foreach (var record in ReadKnownTasks().Where(task => IsControllable(task.Xml, Launcher!, userSid, port)))
            {
                var verified = WithTask(record, task => WithInstances<VerifiedTask?>((object)task, instance =>
                {
                    using var owner = OpenActionProcess((object)instance, record.Xml);
                    if (owner is null || !ProcessAncestry.IsDescendant(service, owner)) return null;
                    return new(record, (string)instance.InstanceGuid, owner.Id, owner.StartTime.ToUniversalTime().Ticks,
                        service.Id, service.StartTime.ToUniversalTime().Ticks);
                }));
                if (verified is null) continue;
                if (_verified is not null) { _verified = null; return new(false, "More than one task claims this service. Nothing was adopted."); }
                _verified = verified;
            }
            return _verified is null
                ? new(false, "No verified Reader launcher or compatible current-user scheduled task owns this service. Stop terminal or custom launchers through their original owner.")
                : new(true, "Current-user scheduled service instance verified.");
        }
        catch (Exception exception) when (ExpectedFailure(exception))
        { _verified = null; return new(false, "Scheduled service ownership could not be verified. Nothing was adopted or stopped."); }
    }

    public ServiceCommandResult Stop(LocalServiceStatus status, Func<bool> reservationValid, CancellationToken cancellationToken)
    {
        var expected = _verified;
        if (expected is null || expected.ServicePid != status.Resources.ProcessId)
            return new(false, "No scheduled service instance was verified before confirmation.");
        try
        {
            return WithTask(expected.Record, task => WithInstances<ServiceCommandResult?>((object)task, instance =>
            {
                if ((string)instance.InstanceGuid != expected.Instance) return null;
                using var owner = OpenActionProcess((object)instance, expected.Record.Xml);
                using var service = Process.GetProcessById(expected.ServicePid);
                _ = service.Handle;
                if (owner is null || owner.Id != expected.LauncherPid || owner.StartTime.ToUniversalTime().Ticks != expected.LauncherStart ||
                    service.StartTime.ToUniversalTime().Ticks != expected.ServiceStart || !ProcessAncestry.IsDescendant(service, owner))
                    return new(false, "The scheduled service process changed during confirmation. Nothing was stopped.");
                if (cancellationToken.IsCancellationRequested || !reservationValid())
                    return new(false, "The maintenance reservation expired. Nothing was stopped.");
                RequireUnchanged((object)task, expected.Record);
                if (cancellationToken.IsCancellationRequested || !reservationValid())
                    return new(false, "The maintenance reservation expired. Nothing was stopped.");
                // RunningTask.Stop sends WM_CLOSE and may outlive the reservation
                // without closing descendants. Use the same immediate, verified
                // idle-tree termination as a Reader-owned launcher instead. The
                // action must itself be powershell.exe, never taskeng/svchost.
                owner.Kill(entireProcessTree: true);
                if (!owner.WaitForExit(5000) || !service.WaitForExit(5000))
                    return new(false, "The scheduled service did not finish stopping. Restart was not attempted.");
                _restartTask = expected.Record;
                _verified = null;
                return new(true, "The verified scheduled service was stopped. Its startup registration is unchanged.");
            }) ?? new(false, "The verified scheduled service instance no longer exists. Refresh status."));
        }
        catch (Exception exception) when (ExpectedFailure(exception))
        { return new(false, "Scheduled service shutdown could not be confirmed. No unrelated process was terminated."); }
    }

    // Null means no registered legacy owner exists; the caller may use its own
    // launcher. A refusal must not fall through to a duplicate direct launch.
    public ServiceCommandResult? Start(CancellationToken cancellationToken)
    {
        try
        {
            var known = ReadKnownTasks();
            if (known.Count == 0 && _restartTask is null) return null;
            foreach (var record in known)
                if (WithTask(record, task => WithInstances<bool?>((object)task, instance => true)) == true)
                    return new(false, "A legacy service task is already starting or running. No duplicate was launched.");
            var candidates = known.Where(task => task.Enabled && IsControllable(task.Xml, Launcher!, userSid, port)).ToArray();
            if (!known.Any(task => task.Enabled) && _restartTask is null) return null;
            var selected = _restartTask ?? (candidates.Length == 1 ? candidates[0] : null);
            if (selected is null)
                return new(false, "A legacy service task exists, but no single compatible enabled owner can be chosen. Review it in Windows Task Scheduler; no second launcher was started.");
            return WithTask(selected, task =>
            {
                if (!(bool)task.Enabled) return new ServiceCommandResult(false, "The legacy service task is disabled. Its registration was left unchanged.");
                if (WithInstances<bool?>((object)task, instance => true) == true)
                    return new(false, "The scheduled service is already starting or running. No duplicate was launched.");
                RequireUnchanged((object)task, selected);
                cancellationToken.ThrowIfCancellationRequested();
                object? started = task.Run(null);
                WindowsUserStartupTasks.Release(started);
                _restartTask = null;
                return new(true, "The verified legacy task was started. Waiting for service readiness.");
            });
        }
        catch (Exception exception) when (ExpectedFailure(exception))
        { return new(false, "The legacy service task could not be started safely. No fallback or duplicate launcher was used."); }
    }

    private Process? OpenActionProcess(object running, string taskXml)
    {
        dynamic instance = running;
        instance.Refresh();
        var pid = (int)instance.EnginePID;
        if (pid <= 0) return null;
        var process = Process.GetProcessById(pid);
        try
        {
            _ = process.Handle;
            if (!process.HasExited && SamePath(process.MainModule?.FileName, LocalServiceProcessControl.PowerShellPath) &&
                OpenProcessToken(process.Handle, 8, out var token)) // TOKEN_QUERY
            {
                using (token)
                using (var identity = new WindowsIdentity(token.DangerousGetHandle()))
                    if (identity.User?.Value == userSid && MatchesRunningCommand(process, taskXml)) return process;
            }
        }
        catch { process.Dispose(); throw; }
        process.Dispose();
        return null; // Older shared taskeng/svchost engines are not safe process owners.
    }

    private static bool MatchesRunningCommand(Process process, string taskXml)
    {
        // A registered definition can be edited while its previous action still
        // runs. Query only this held process identity, never enumerate/log command
        // lines. WMI is a local read; failure means ownership cannot be established.
        object? locator = null; object? services = null; object? item = null;
        object? properties = null; object? property = null;
        try
        {
            locator = Activator.CreateInstance(Type.GetTypeFromProgID("WbemScripting.SWbemLocator")!);
            dynamic connection = locator!;
            services = connection.ConnectServer(".", "root\\cimv2");
            dynamic wmi = services;
            item = wmi.Get("Win32_Process.Handle=\"" + process.Id.ToString(System.Globalization.CultureInfo.InvariantCulture) + "\"");
            dynamic record = item;
            properties = record.Properties_;
            dynamic values = properties;
            property = values.Item("CommandLine", 0);
            dynamic value = property;
            string? command = value.Value;
            if (command is null || process.HasExited) return false;
            var actual = SplitArguments(command);
            var expected = SplitArguments((string?)UserStartupRegistration.ReadXml(taskXml).Root!
                .Element(Ns + "Actions")!.Element(Ns + "Exec")!.Element(Ns + "Arguments") ?? "");
            return actual.Length == expected.Length + 1 && SamePath(actual[0], LocalServiceProcessControl.PowerShellPath) &&
                actual.Skip(1).SequenceEqual(expected, StringComparer.Ordinal);
        }
        finally
        {
            WindowsUserStartupTasks.Release(property); WindowsUserStartupTasks.Release(properties);
            WindowsUserStartupTasks.Release(item); WindowsUserStartupTasks.Release(services); WindowsUserStartupTasks.Release(locator);
        }
    }

    private static T WithTask<T>(StartupTaskRecord expected, Func<dynamic, T> operation) => WindowsUserStartupTasks.WithFolder<T>(folder =>
    {
        object? task = null;
        try
        {
            task = folder.GetTask(expected.Name);
            dynamic current = task;
            RequireUnchanged((object)current, expected);
            return operation(current);
        }
        finally { WindowsUserStartupTasks.Release(task); }
    });

    private static void RequireUnchanged(object registered, StartupTaskRecord expected)
    {
        dynamic current = registered;
        if (!XNode.DeepEquals(UserStartupRegistration.ReadXml((string)current.Xml), UserStartupRegistration.ReadXml(expected.Xml)))
            throw new InvalidOperationException("The scheduled task definition changed.");
    }

    private static T? WithInstances<T>(object registered, Func<dynamic, T?> match)
    {
        dynamic task = registered;
        object? instances = null;
        try
        {
            instances = task.GetInstances(0);
            dynamic values = instances;
            if ((int)values.Count > 32) throw new InvalidOperationException("Too many running task instances.");
            for (var index = 1; index <= (int)values.Count; index++)
            {
                object? instance = null;
                try { instance = values.Item[index]; var result = match(instance); if (result is not null) return result; }
                finally { WindowsUserStartupTasks.Release(instance); }
            }
            return default;
        }
        finally { WindowsUserStartupTasks.Release(instances); }
    }

    public static IReadOnlyList<StartupTaskRecord> ReadTasks() => WindowsUserStartupTasks.WithFolder<IReadOnlyList<StartupTaskRecord>>(root =>
    {
        var result = new List<StartupTaskRecord>();
        var folderCount = 0;
        void Visit(dynamic folder, int depth)
        {
            if (++folderCount > 512 || depth > 20) throw new InvalidOperationException("Task discovery limit exceeded.");
            object? tasks = null; object? folders = null;
            try
            {
                tasks = folder.GetTasks(1); // Include hidden tasks; only accessible definitions are returned.
                dynamic values = tasks;
                if (result.Count + (int)values.Count > 8192) throw new InvalidOperationException("Task discovery limit exceeded.");
                for (var i = 1; i <= (int)values.Count; i++)
                {
                    object? item = null;
                    try { item = values.Item[i]; dynamic task = item; result.Add(new((string)task.Path, (string)task.Xml, (bool)task.Enabled)); }
                    finally { WindowsUserStartupTasks.Release(item); }
                }
                folders = folder.GetFolders(0);
                dynamic children = folders;
                for (var i = 1; i <= (int)children.Count; i++)
                {
                    object? child = null;
                    try { child = children.Item[i]; Visit(child, depth + 1); }
                    finally { WindowsUserStartupTasks.Release(child); }
                }
            }
            finally { WindowsUserStartupTasks.Release(tasks); WindowsUserStartupTasks.Release(folders); }
        }
        Visit(root, 0);
        return result;
    });

    public static bool IsKnownLauncher(string xml, string directLauncher, string userSid)
    {
        try
        {
            var root = UserStartupRegistration.ReadXml(xml).Root;
            var principal = root?.Element(Ns + "Principals")?.Elements().SingleOrDefault();
            if (principal?.Name != Ns + "Principal" || !UserStartupRegistration.SameUser((string?)principal.Element(Ns + "UserId"), userSid)) return false;
            var action = root?.Element(Ns + "Actions")?.Elements().SingleOrDefault();
            if (action?.Name != Ns + "Exec" || !SamePath((string?)action.Element(Ns + "Command"), LocalServiceProcessControl.PowerShellPath)) return false;
            var args = SplitArguments((string?)action.Element(Ns + "Arguments") ?? "");
            var file = Array.FindIndex(args, arg => arg.Equals("-File", StringComparison.OrdinalIgnoreCase));
            if (file < 0 || file + 1 >= args.Length) return false;
            var scheduled = Path.Combine(Path.GetDirectoryName(directLauncher)!, "run_scheduled_service.ps1");
            return SamePath(args[file + 1], directLauncher) || SamePath(args[file + 1], scheduled);
        }
        catch (Exception exception) when (ExpectedFailure(exception)) { return false; }
    }

    public static bool IsControllable(string xml, string directLauncher, string userSid, int port)
    {
        if (!IsKnownLauncher(xml, directLauncher, userSid)) return false;
        try
        {
            var root = UserStartupRegistration.ReadXml(xml).Root!;
            var principal = root.Element(Ns + "Principals")!.Elements().Single();
            if ((string?)principal.Element(Ns + "LogonType") != "InteractiveToken" ||
                ((string?)principal.Element(Ns + "RunLevel") ?? "LeastPrivilege") != "LeastPrivilege") return false;
            if (root.Element(Ns + "Settings")?.Element(Ns + "RestartOnFailure") is not null) return false;
            if (root.Element(Ns + "Triggers")?.Elements().Any(trigger => trigger.Name != Ns + "LogonTrigger" ||
                trigger.Element(Ns + "Repetition") is not null) == true) return false;
            var args = SplitArguments((string?)root.Element(Ns + "Actions")!.Element(Ns + "Exec")!.Element(Ns + "Arguments") ?? "");
            var prefix = new[] { "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File" };
            if (args.Length < 9 || !args.Take(6).SequenceEqual(prefix, StringComparer.OrdinalIgnoreCase) ||
                !SamePath(args[6], Path.Combine(Path.GetDirectoryName(directLauncher)!, "run_scheduled_service.ps1")) ||
                !args[7].Equals("-LogPath", StringComparison.OrdinalIgnoreCase) || !Path.IsPathFullyQualified(args[8])) return false;
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (var index = 9; index < args.Length; index += 2)
            {
                if (index + 1 >= args.Length || !seen.Add(args[index])) return false;
                if (args[index].Equals("-HostOverride", StringComparison.OrdinalIgnoreCase))
                { if (args[index + 1] != "127.0.0.1" && !args[index + 1].Equals("localhost", StringComparison.OrdinalIgnoreCase)) return false; }
                else if (args[index].Equals("-Port", StringComparison.OrdinalIgnoreCase))
                { if (!int.TryParse(args[index + 1], out var configured) || configured != port) return false; }
                else return false;
            }
            return true;
        }
        catch (Exception exception) when (ExpectedFailure(exception)) { return false; }
    }

    private static bool HasAutomaticTrigger(string xml) => UserStartupRegistration.ReadXml(xml).Root?
        .Element(Ns + "Triggers")?.Elements().Any(trigger => (bool?)trigger.Element(Ns + "Enabled") != false) == true;

    private static bool SamePath(string? value, string expected) => value is not null && Path.IsPathFullyQualified(value) &&
        string.Equals(Path.GetFullPath(value), Path.GetFullPath(expected), StringComparison.OrdinalIgnoreCase);

    private static string[] SplitArguments(string arguments)
    {
        if (arguments.Length > 32768 || arguments.Contains('\0')) throw new ArgumentException("Invalid task arguments.");
        var pointer = CommandLineToArgvW("tts-task.exe " + arguments, out var count);
        if (pointer == IntPtr.Zero) throw new Win32Exception();
        try
        {
            if (count > 64) throw new ArgumentException("Too many task arguments.");
            return Enumerable.Range(1, count - 1).Select(index => Marshal.PtrToStringUni(Marshal.ReadIntPtr(pointer, index * IntPtr.Size))!).ToArray();
        }
        finally { LocalFree(pointer); }
    }

    private static bool ExpectedFailure(Exception exception) => exception is COMException or IOException or UnauthorizedAccessException or
        ArgumentException or InvalidOperationException or Win32Exception or XmlException or FormatException or NotSupportedException;
    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(IntPtr processHandle, uint desiredAccess, out SafeAccessTokenHandle token);
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CommandLineToArgvW(string command, out int count);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr pointer);
}
