using System.Runtime.InteropServices;
using System.Xml.Linq;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class UserStartupRegistrationTests
{
    private const string Sid = "S-1-5-21-100-200-300-1001";
    private const string Executable = @"C:\Reader & voices\Læser\TtsPlatform.Reader.App.exe";
    private static readonly XNamespace Ns = "http://schemas.microsoft.com/windows/2004/02/mit/task";
    private sealed class Tasks : IUserStartupTasks
    {
        public Dictionary<string, StartupTaskRecord> Items = [];
        public int Creates, Removes, Changes;
        public bool FailCreate, FailRemove, FailRead, FailLegacyRead;
        public Action? BeforeCreate;
        public StartupTaskRecord? Read(string name)
        {
            if (FailRead || (FailLegacyRead && name == ScheduledServiceController.TaskName)) throw new COMException("Denied", unchecked((int)0x80070005));
            return Items.GetValueOrDefault(name);
        }
        public void Create(string name, string xml, string userSid)
        {
            BeforeCreate?.Invoke();
            if (FailCreate) throw new COMException("Denied", unchecked((int)0x80070005));
            Creates++;
            if (!Items.TryAdd(name, new(name, xml, (bool)XDocument.Parse(xml).Root!.Element(Ns + "Settings")!.Element(Ns + "Enabled")!)))
                throw new InvalidOperationException("No overwrites allowed");
        }
        public void SetEnabled(StartupTaskRecord expected, bool enabled)
        {
            Assert.Equal(expected, Items[expected.Name]);
            Changes++;
            var xml = XDocument.Parse(expected.Xml);
            xml.Root!.Element(Ns + "Settings")!.Element(Ns + "Enabled")!.Value = enabled ? "true" : "false";
            Items[expected.Name] = expected with { Xml = xml.ToString(), Enabled = enabled };
        }
        public void Remove(StartupTaskRecord expected)
        {
            Assert.Equal(expected, Items[expected.Name]);
            if (FailRemove) throw new COMException("Denied", unchecked((int)0x80070005));
            Removes++;
            Items.Remove(expected.Name);
        }
    }

    [Fact]
    public void Autostart_activation_is_distinct_from_reader_and_background_opening()
    {
        Assert.Equal(ReaderActivation.OpenReader, ReaderActivationArguments.Parse([]));
        Assert.Equal(ReaderActivation.Background, ReaderActivationArguments.Parse(["--background"]));
        Assert.Equal(ReaderActivation.OpenServiceCenter, ReaderActivationArguments.Parse(["--service-center"]));
        Assert.Equal(ReaderActivation.Autostart, ReaderActivationArguments.Parse(["--autostart"]));
        Assert.Equal(ReaderActivation.Autostart, ReaderActivationArguments.Parse(["--smoke-test", "--activation-probe", "--autostart"]));
    }

    [Fact]
    public async Task Default_read_does_not_register_and_repeated_enable_disable_is_idempotent()
    {
        var tasks = new Tasks(); var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true);
        Assert.False((await manager.ReadAsync()).Enabled);
        Assert.Empty(tasks.Items);
        Assert.True((await manager.SetEnabledAsync(true)).Enabled);
        Assert.True((await manager.SetEnabledAsync(true)).Enabled);
        Assert.Equal(1, tasks.Creates);
        Assert.False((await manager.SetEnabledAsync(false)).Enabled);
        Assert.False((await manager.SetEnabledAsync(false)).Enabled);
        Assert.Equal(1, tasks.Removes);
        Assert.Empty(tasks.Items);
    }

    [Fact]
    public void Definition_has_separate_escaped_paths_current_user_and_no_password_or_elevation()
    {
        var text = UserStartupRegistration.BuildDefinition(Executable, Sid);
        var root = XDocument.Parse(text).Root!;
        Assert.Equal(Executable, (string?)root.Element(Ns + "Actions")!.Element(Ns + "Exec")!.Element(Ns + "Command"));
        Assert.Equal("--autostart", (string?)root.Element(Ns + "Actions")!.Element(Ns + "Exec")!.Element(Ns + "Arguments"));
        Assert.Equal(Sid, (string?)root.Element(Ns + "Triggers")!.Element(Ns + "LogonTrigger")!.Element(Ns + "UserId"));
        Assert.Contains("InteractiveToken", text);
        Assert.Contains("LeastPrivilege", text);
        Assert.DoesNotContain("Password", text);
        Assert.DoesNotContain("HighestAvailable", text);
        Assert.True(UserStartupRegistration.MatchesDefinition(text, Executable, Sid));
        Assert.NotEqual(UserStartupRegistration.NameForUser(Sid), UserStartupRegistration.NameForUser(Sid + "2"));
    }

    [Theory]
    [InlineData("executable")]
    [InlineData("user")]
    [InlineData("arguments")]
    [InlineData("trigger")]
    [InlineData("elevation")]
    [InlineData("condition")]
    [InlineData("malformed")]
    public async Task Changed_or_foreign_task_is_never_overwritten_or_removed(string change)
    {
        var tasks = new Tasks(); var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true);
        var xml = XDocument.Parse(UserStartupRegistration.BuildDefinition(Executable, Sid));
        var root = xml.Root!;
        if (change == "executable") root.Descendants(Ns + "Command").Single().Value = @"C:\Other\TtsPlatform.Reader.App.exe";
        if (change == "user") root.Descendants(Ns + "UserId").First().Value = Sid + "2";
        if (change == "arguments") root.Descendants(Ns + "Arguments").Single().Value = "--unrelated";
        if (change == "trigger") root.Element(Ns + "Triggers")!.Add(new XElement(Ns + "BootTrigger"));
        if (change == "elevation") root.Descendants(Ns + "RunLevel").Single().Value = "HighestAvailable";
        if (change == "condition") root.Descendants(Ns + "RunOnlyIfNetworkAvailable").Single().Value = "true";
        var original = new StartupTaskRecord(manager.TaskName, change == "malformed" ? "<bad" : xml.ToString(), true);
        tasks.Items[manager.TaskName] = original;
        Assert.False((await manager.ReadAsync()).CanDisable);
        Assert.False((await manager.SetEnabledAsync(true)).CanEnable);
        await manager.SetEnabledAsync(false);
        Assert.Equal(original, tasks.Items[manager.TaskName]);
        Assert.Equal(0, tasks.Creates + tasks.Removes + tasks.Changes);
    }

    [Fact]
    public async Task Legacy_startup_is_detected_and_left_unchanged()
    {
        var tasks = new Tasks(); var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true);
        var legacy = new StartupTaskRecord(manager.LegacyTaskName, "<legacy />", true);
        tasks.Items[legacy.Name] = legacy;
        var result = await manager.SetEnabledAsync(true);
        Assert.False(result.Enabled);
        Assert.False(result.CanEnable);
        Assert.Equal(legacy, Assert.Single(tasks.Items).Value);
        tasks.Items[legacy.Name] = legacy with { Enabled = false };
        Assert.True((await manager.SetEnabledAsync(true)).Enabled);
        Assert.False(tasks.Items[legacy.Name].Enabled);
        await manager.SetEnabledAsync(false);
        Assert.False(tasks.Items[legacy.Name].Enabled); // Off never silently re-enables a legacy owner.
    }

    [Fact]
    public async Task Custom_named_legacy_discovery_prevents_duplicate_startup_without_changing_task()
    {
        var tasks = new Tasks();
        var custom = new StartupTaskRecord(@"\My tasks\Book reader", "<legacy />", true);
        var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true,
            findLegacyStartup: () => [custom]);
        var result = await manager.SetEnabledAsync(true);
        Assert.False(result.Enabled);
        Assert.False(result.CanEnable);
        Assert.Contains(custom.Name, result.Message);
        Assert.Empty(tasks.Items);
    }

    [Fact]
    public async Task Missing_executable_and_moved_installation_do_not_create_startup()
    {
        var tasks = new Tasks(); var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => false);
        Assert.False((await manager.SetEnabledAsync(true)).CanEnable);
        Assert.Empty(tasks.Items);
        tasks.Create(manager.TaskName, UserStartupRegistration.BuildDefinition(Executable, Sid), Sid);
        Assert.True((await manager.ReadAsync()).Enabled); // Registered, but the missing runtime is explicitly reported.
        Assert.True(manager.State.CanDisable);
        Assert.False(manager.State.CanEnable);
        Assert.False((await manager.SetEnabledAsync(false)).Enabled);
    }

    [Fact]
    public async Task Failure_display_is_read_back_or_unknown_not_the_requested_checkbox_value()
    {
        var tasks = new Tasks { FailCreate = true }; var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true);
        Assert.False((await manager.SetEnabledAsync(true)).Enabled);
        tasks.FailCreate = false;
        await manager.SetEnabledAsync(true);
        tasks.FailRemove = true;
        Assert.True((await manager.SetEnabledAsync(false)).Enabled);
        Assert.Contains("did not confirm", manager.State.Message);
        tasks.FailRead = true;
        Assert.Null((await manager.ReadAsync()).Enabled);
        Assert.False(manager.State.CanEnable);
        Assert.False(manager.State.CanDisable);
    }

    [Fact]
    public async Task Legacy_access_denial_does_not_prevent_removal_of_our_verified_entry()
    {
        var tasks = new Tasks(); var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true);
        await manager.SetEnabledAsync(true);
        tasks.FailLegacyRead = true;
        var before = await manager.ReadAsync();
        Assert.True(before.Enabled);
        Assert.True(before.CanDisable);
        Assert.False(before.CanEnable);
        Assert.False((await manager.SetEnabledAsync(false)).Enabled);
        Assert.Empty(tasks.Items);
    }

    [Fact]
    public async Task Windows_disabled_entry_is_reported_and_can_be_enabled_without_duplicate_creation()
    {
        var tasks = new Tasks(); var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true);
        tasks.Create(manager.TaskName, UserStartupRegistration.BuildDefinition(Executable, Sid, enabled: false), Sid);
        Assert.False((await manager.ReadAsync()).Enabled);
        Assert.True((await manager.SetEnabledAsync(true)).Enabled);
        Assert.Equal(1, tasks.Creates);
        Assert.Equal(1, tasks.Changes);
    }

    [Fact]
    public async Task Observation_timeout_does_not_start_a_duplicate_or_claim_failure_is_terminal()
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var tasks = new Tasks { BeforeCreate = () => { entered.Set(); release.Wait(TimeSpan.FromSeconds(5)); } };
        var manager = new UserStartupRegistration(tasks, Executable, Sid, _ => true,
            observationTimeout: TimeSpan.FromMilliseconds(100));
        try
        {
            var starting = manager.SetEnabledAsync(true);
            Assert.True(entered.Wait(TimeSpan.FromSeconds(2)));
            Assert.Null((await starting).Enabled);
            var pending = await manager.SetEnabledAsync(false);
            Assert.Null(pending.Enabled);
            Assert.Contains("pending", pending.Message);
            Assert.Equal(0, tasks.Removes);
        }
        finally { release.Set(); }
        UserStartupState state = manager.State;
        for (var attempt = 0; attempt < 30 && state.Enabled is null; attempt++)
        {
            await Task.Delay(20);
            state = await manager.ReadAsync();
        }
        Assert.True(state.Enabled);
        Assert.Equal(1, tasks.Creates);
        Assert.Equal(0, tasks.Removes);
    }

    [Fact]
    public void Real_scheduler_roundtrip_uses_only_a_unique_disabled_fixture_task()
    {
        var name = "TTS Platform Test Startup " + Guid.NewGuid().ToString("N");
        var sid = UserStartupRegistration.CurrentUserSid();
        var executable = Path.Combine(AppContext.BaseDirectory, "TtsPlatform.Reader.App.exe");
        var store = new WindowsUserStartupTasks();
        Assert.Null(store.Read(name));
        var created = false;
        try
        {
            store.Create(name, UserStartupRegistration.BuildDefinition(executable, sid, enabled: false), sid);
            created = true;
            var registered = store.Read(name);
            Assert.NotNull(registered);
            Assert.False(registered.Enabled); // This fixture can never run at login or on registration.
            Assert.True(UserStartupRegistration.MatchesDefinition(registered.Xml, executable, sid));
            store.Remove(registered);
            created = false;
            Assert.Null(store.Read(name));
        }
        finally
        {
            if (created && store.Read(name) is { } remaining &&
                UserStartupRegistration.MatchesDefinition(remaining.Xml, executable, sid)) store.Remove(remaining);
        }
    }
}
