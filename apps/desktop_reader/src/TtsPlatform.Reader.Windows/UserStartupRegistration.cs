using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Xml;
using System.Xml.Linq;

namespace TtsPlatform.Reader.Windows;

public sealed record StartupTaskRecord(string Name, string Xml, bool Enabled);
public sealed record UserStartupState(bool? Enabled, bool CanEnable, bool CanDisable, string Message);

// Narrow OS boundary: no free-form process execution, passwords or elevation.
public interface IUserStartupTasks
{
    StartupTaskRecord? Read(string name);
    void Create(string name, string xml, string userSid);
    void SetEnabled(StartupTaskRecord expected, bool enabled);
    void Remove(StartupTaskRecord expected);
}

public sealed class UserStartupRegistration(
    IUserStartupTasks tasks, string executable, string userSid, Func<string, bool>? fileExists = null,
    string? isolatedTaskName = null, string? legacyTaskName = null, TimeSpan? observationTimeout = null,
    Func<IReadOnlyList<StartupTaskRecord>>? findLegacyStartup = null)
{
    private const string Source = "TTS Platform Service Center startup v1";
    private static readonly XNamespace Ns = "http://schemas.microsoft.com/windows/2004/02/mit/task";
    private readonly string _executable = Path.GetFullPath(executable);
    private readonly Func<string, bool> _exists = fileExists ?? File.Exists;
    private readonly SemaphoreSlim _gate = new(1, 1);
    public string TaskName { get; } = isolatedTaskName ?? NameForUser(userSid);
    public string LegacyTaskName { get; } = legacyTaskName ?? ScheduledServiceController.TaskName;
    public UserStartupState State { get; private set; } = new(null, false, false, "Windows startup has not been checked.");

    public static string NameForUser(string sid) => "TTS Platform Service Center " +
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(sid)))[..12];

    public static string CurrentUserSid()
    {
        using var identity = WindowsIdentity.GetCurrent();
        return identity.User?.Value ?? throw new InvalidOperationException("The current Windows user could not be identified.");
    }

    public Task<UserStartupState> ReadAsync(CancellationToken cancellationToken = default) =>
        RunAsync(null, cancellationToken);

    public Task<UserStartupState> SetEnabledAsync(bool enabled, CancellationToken cancellationToken = default) =>
        RunAsync(enabled, cancellationToken);

    private async Task<UserStartupState> RunAsync(bool? enabled, CancellationToken cancellationToken)
    {
        if (!await _gate.WaitAsync(0, cancellationToken))
            return State = new(null, false, false, "A Windows startup operation is still pending. Wait, then refresh; no duplicate operation was started.");
        // Keep ownership until the native call actually finishes. A UI observation
        // timeout is not proof that Windows rejected or finished a registration.
        var operation = Task.Run(() =>
        {
            try { return Perform(enabled, cancellationToken); }
            finally { _gate.Release(); }
        });
        _ = operation.ContinueWith(task => _ = task.Exception, CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        try { return State = await operation.WaitAsync(observationTimeout ?? TimeSpan.FromSeconds(10), cancellationToken); }
        catch (TimeoutException)
        {
            return State = new(null, false, false, "Windows has not confirmed the operation yet. It may still be running. Wait, then refresh to read the actual registration.");
        }
    }

    private UserStartupState Perform(bool? enabled, CancellationToken cancellationToken)
    {
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            var record = tasks.Read(TaskName);
            // Removing this verified entry must not depend on permission
            // to inspect an unrelated legacy task belonging to someone else.
            if (enabled == false && record is not null && MatchesDefinition(record.Xml, _executable, userSid))
            {
                cancellationToken.ThrowIfCancellationRequested();
                tasks.Remove(record);
                return ReadCurrent();
            }
            var state = ReadCurrent(record, ownTaskRead: true);
            if (enabled is null) return state;
            if (enabled == true)
            {
                if (!state.CanEnable) return state;
                cancellationToken.ThrowIfCancellationRequested();
                if (record is null) tasks.Create(TaskName, BuildDefinition(_executable, userSid), userSid);
                else if (!record.Enabled) tasks.SetEnabled(record, true);
            }
            else
            {
                if (record is null) return state;
                if (!state.CanDisable) return state;
                cancellationToken.ThrowIfCancellationRequested();
                tasks.Remove(record);
            }
            // The display always comes from Windows, not the requested checkbox value.
            return ReadCurrent();
        }
        catch (OperationCanceledException)
        {
            return new(null, false, false, "The startup operation was cancelled. Refresh the actual Windows registration before trying again.");
        }
        catch (Exception exception) when (exception is COMException or UnauthorizedAccessException or
            IOException or InvalidOperationException or XmlException or ArgumentException)
        {
            try
            {
                var current = ReadCurrent();
                return current with { Message = "Windows did not confirm the requested operation. Current registration: " + current.Message };
            }
            catch (Exception readError) when (readError is COMException or UnauthorizedAccessException or
                IOException or InvalidOperationException or XmlException or ArgumentException)
            { }
            // Do not claim rollback when readback also fails: the OS may
            // have accepted a mutation. Show unknown, not a false Off state.
            return new(null, false, false,
                "Windows startup could not be verified or changed. No administrator request was made. Refresh to read the actual registration before trying again.");
        }
    }

    private UserStartupState ReadCurrent(StartupTaskRecord? record = null, bool ownTaskRead = false)
    {
        if (!ownTaskRead) record = tasks.Read(TaskName);
        try
        {
            var legacy = tasks.Read(LegacyTaskName);
            if (legacy?.Enabled != true) legacy = findLegacyStartup?.Invoke().FirstOrDefault(task => task.Enabled) ?? legacy;
            return Inspect(record, legacy);
        }
        catch (Exception exception) when (exception is COMException or UnauthorizedAccessException or IOException)
        {
            return Inspect(record, null) with
            {
                CanEnable = false,
                Message = "The legacy startup task could not be inspected. New startup cannot be enabled until this check succeeds; an existing verified Service Center entry can still be removed.",
            };
        }
    }

    private UserStartupState Inspect(StartupTaskRecord? record, StartupTaskRecord? legacy)
    {
        if (record is not null && !MatchesDefinition(record.Xml, _executable, userSid))
            return new(record.Enabled, false, false,
                "A startup task with this name belongs to another installation or has changed. It was not overwritten. Remove or repair that task in Windows Task Scheduler first.");
        var legacyEnabled = legacy?.Enabled == true;
        if (!_exists(_executable))
            return new(record?.Enabled == true, false, record is not null,
                "The published Reader runtime is missing or has moved. Existing registration can be removed, but startup cannot be enabled here.");
        if (record?.Enabled == true)
            return new(true, !legacyEnabled, true, legacyEnabled
                ? "Service Center startup is enabled, but the legacy service task is also enabled. Turn one off to avoid competing startup owners."
                : "On · Service Center and the local service start at Windows login. Reader stays closed.");
        if (legacyEnabled)
            return new(false, false, record is not null,
                $"The legacy startup task '{legacy!.Name}' is enabled. Disable or remove it in Windows Task Scheduler before enabling Service Center startup. It was left unchanged.");
        return new(false, true, record is not null,
            "Off · No Service Center startup will run. Enabling this does not open Reader or start the service right now.");
    }

    public static string BuildDefinition(string executable, string userSid, bool enabled = true)
    {
        var path = Path.GetFullPath(executable);
        // Command, arguments and working directory are separate XML fields. Paths
        // containing spaces, Unicode or '&' never become a shell command string.
        XElement E(string name, object value) => new(Ns + name, value);
        return new XDocument(new XElement(Ns + "Task", new XAttribute("version", "1.2"),
            E("RegistrationInfo", E("Source", Source)),
            E("Triggers", new XElement(Ns + "LogonTrigger", E("Enabled", true), E("UserId", userSid), E("Delay", "PT10S"))),
            E("Principals", new XElement(Ns + "Principal", new XAttribute("id", "ReaderUser"),
                E("UserId", userSid), E("LogonType", "InteractiveToken"), E("RunLevel", "LeastPrivilege"))),
            E("Settings", new object[]
            {
                E("MultipleInstancesPolicy", "IgnoreNew"), E("DisallowStartIfOnBatteries", false),
                E("StopIfGoingOnBatteries", false), E("AllowStartOnDemand", true), E("Enabled", enabled),
                E("RunOnlyIfNetworkAvailable", false), E("RunOnlyIfIdle", false),
                E("ExecutionTimeLimit", "PT0S"),
            }),
            new XElement(Ns + "Actions", new XAttribute("Context", "ReaderUser"),
                E("Exec", new object[] { E("Command", path), E("Arguments", "--autostart"), E("WorkingDirectory", Path.GetDirectoryName(path)!) })))).ToString();
    }

    public static bool MatchesDefinition(string xml, string executable, string userSid)
    {
        try
        {
            var root = ReadXml(xml).Root;
            var principal = root?.Element(Ns + "Principals")?.Elements().SingleOrDefault();
            var trigger = root?.Element(Ns + "Triggers")?.Elements().SingleOrDefault();
            var action = root?.Element(Ns + "Actions")?.Elements().SingleOrDefault();
            var settings = root?.Element(Ns + "Settings");
            return root?.Name == Ns + "Task" &&
                (string?)root.Element(Ns + "RegistrationInfo")?.Element(Ns + "Source") == Source &&
                principal?.Name == Ns + "Principal" && (string?)principal.Attribute("id") == "ReaderUser" &&
                SameUser((string?)principal.Element(Ns + "UserId"), userSid) &&
                (string?)principal.Element(Ns + "LogonType") == "InteractiveToken" &&
                ((string?)principal.Element(Ns + "RunLevel") ?? "LeastPrivilege") == "LeastPrivilege" &&
                trigger?.Name == Ns + "LogonTrigger" && SameUser((string?)trigger.Element(Ns + "UserId"), userSid) &&
                ((bool?)trigger.Element(Ns + "Enabled") ?? true) &&
                trigger.Element(Ns + "Repetition") is null && (string?)trigger.Element(Ns + "Delay") == "PT10S" &&
                action?.Name == Ns + "Exec" &&
                (string?)root.Element(Ns + "Actions")?.Attribute("Context") == "ReaderUser" &&
                PathEquals((string?)action.Element(Ns + "Command"), executable) &&
                (string?)action.Element(Ns + "Arguments") == "--autostart" &&
                PathEquals((string?)action.Element(Ns + "WorkingDirectory"), Path.GetDirectoryName(Path.GetFullPath(executable))!) &&
                (string?)settings?.Element(Ns + "MultipleInstancesPolicy") == "IgnoreNew" &&
                (bool?)settings?.Element(Ns + "DisallowStartIfOnBatteries") == false &&
                (bool?)settings?.Element(Ns + "StopIfGoingOnBatteries") == false &&
                !((bool?)settings?.Element(Ns + "RunOnlyIfNetworkAvailable") ?? false) &&
                !((bool?)settings?.Element(Ns + "RunOnlyIfIdle") ?? false) &&
                (string?)settings?.Element(Ns + "ExecutionTimeLimit") == "PT0S";
        }
        catch (Exception exception) when (exception is XmlException or InvalidOperationException or ArgumentException or FormatException)
        { return false; }
    }

    internal static XDocument ReadXml(string xml)
    {
        if (xml.Length > 1_048_576) throw new XmlException("Startup task XML is too large.");
        using var input = new StringReader(xml);
        using var reader = XmlReader.Create(input, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null });
        return XDocument.Load(reader);
    }

    private static bool PathEquals(string? value, string expected) => value is not null &&
        string.Equals(Path.GetFullPath(value), Path.GetFullPath(expected), StringComparison.OrdinalIgnoreCase);

    internal static bool SameUser(string? value, string expectedSid)
    {
        if (string.Equals(value, expectedSid, StringComparison.Ordinal)) return true;
        // Scheduler may serialize the logon trigger as DOMAIN\name. Match only
        // the current identity; do not resolve arbitrary accounts over a network.
        using var current = WindowsIdentity.GetCurrent();
        return current.User?.Value == expectedSid && string.Equals(current.Name, value, StringComparison.OrdinalIgnoreCase);
    }
}

public sealed class WindowsUserStartupTasks : IUserStartupTasks
{
    public StartupTaskRecord? Read(string name) => WithFolder(folder =>
    {
        object? task = null;
        try
        {
            task = folder.GetTask(name);
            dynamic value = task;
            return new StartupTaskRecord(name, (string)value.Xml, (bool)value.Enabled);
        }
        catch (Exception exception) when (exception is COMException or FileNotFoundException &&
            (uint)exception.HResult == 0x80070002)
        { return null; }
        finally { Release(task); }
    });

    public void Create(string name, string xml, string userSid) => WithFolder<object?>(folder =>
    {
        // TASK_CREATE only: never silently overwrite a concurrently registered task.
        object? registered = folder.RegisterTask(name, xml, 2, userSid, null, 3, null);
        Release(registered);
        return null;
    });

    public void SetEnabled(StartupTaskRecord expected, bool enabled) => WithVerified(expected, (folder, task) => task.Enabled = enabled);
    public void Remove(StartupTaskRecord expected) => WithVerified(expected, (folder, task) => folder.DeleteTask(expected.Name, 0));

    private static void WithVerified(StartupTaskRecord expected, Action<dynamic, dynamic> action) => WithFolder<object?>(folder =>
    {
        object? task = null;
        try
        {
            task = folder.GetTask(expected.Name);
            dynamic current = task;
            if (!XNode.DeepEquals(UserStartupRegistration.ReadXml((string)current.Xml), UserStartupRegistration.ReadXml(expected.Xml)))
                throw new InvalidOperationException("The startup task changed during this operation.");
            action(folder, current);
            return null;
        }
        finally { Release(task); }
    });

    internal static T WithFolder<T>(Func<dynamic, T> operation)
    {
        object? service = null;
        object? folder = null;
        try
        {
            service = Activator.CreateInstance(Type.GetTypeFromProgID("Schedule.Service")
                ?? throw new InvalidOperationException("Windows Task Scheduler is unavailable."));
            dynamic scheduler = service!;
            scheduler.Connect();
            folder = scheduler.GetFolder("\\");
            return operation(folder!);
        }
        finally { Release(folder); Release(service); }
    }

    internal static void Release(object? value)
    { if (value is not null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value); }
}
