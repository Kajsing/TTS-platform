using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Xml.Linq;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class LegacyServiceTasksTests
{
    private static readonly XNamespace Ns = "http://schemas.microsoft.com/windows/2004/02/mit/task";
    private static string PowerShell => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe");

    private static string Definition(string direct, string sid, int port, bool startup = false)
    {
        var xml = XDocument.Parse(UserStartupRegistration.BuildDefinition(PowerShell, sid));
        var root = xml.Root!;
        root.Element(Ns + "RegistrationInfo")!.Element(Ns + "Source")!.Value = "TTS Platform isolated legacy fixture";
        if (!startup) root.Element(Ns + "Triggers")!.RemoveNodes(); // No automatic trigger, including logon.
        var action = root.Element(Ns + "Actions")!.Element(Ns + "Exec")!;
        var script = Path.Combine(Path.GetDirectoryName(direct)!, "run_scheduled_service.ps1");
        action.Element(Ns + "Arguments")!.Value = $"-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"{script}\" -LogPath \"{direct}.log\" -HostOverride 127.0.0.1 -Port {port}";
        root.Element(Ns + "Settings")!.Element(Ns + "ExecutionTimeLimit")!.Value = "PT1M";
        return xml.ToString();
    }

    [Fact]
    public void Exact_cli_action_handles_spaces_unicode_and_rejects_unsafe_variants()
    {
        const string sid = "S-1-5-21-100-200-300-1001";
        const string direct = @"C:\Læser & books\scripts\windows\run_service.ps1";
        var valid = Definition(direct, sid, 23456, startup: true);
        Assert.True(LegacyServiceTasks.IsKnownLauncher(valid, direct, sid));
        Assert.True(LegacyServiceTasks.IsControllable(valid, direct, sid, 23456));
        Assert.False(LegacyServiceTasks.IsControllable(valid, direct, sid, 7777));
        foreach (var mutation in new[]
        {
            valid.Replace(sid, sid + "2", StringComparison.Ordinal),
            valid.Replace("InteractiveToken", "S4U", StringComparison.Ordinal),
            valid.Replace("LeastPrivilege", "HighestAvailable", StringComparison.Ordinal),
            valid.Replace("-NoProfile", "-Command", StringComparison.Ordinal),
            valid.Replace("run_scheduled_service.ps1", "unrelated.ps1", StringComparison.Ordinal),
            valid.Replace("127.0.0.1", "0.0.0.0", StringComparison.Ordinal),
            valid.Replace("-Port 23456", "-Port 23456 -Port 23456", StringComparison.Ordinal),
            valid.Replace("-Port 23456", "-Port 23456 -AllowNonLocalHost", StringComparison.Ordinal),
            "<bad",
        }) Assert.False(LegacyServiceTasks.IsControllable(mutation, direct, sid, 23456));
    }

    [Fact]
    public async Task Slow_native_discovery_keeps_ownership_and_cancels_a_late_launch()
    {
        var root = Path.Combine(Path.GetTempPath(), "tts-legacy-test-" + Guid.NewGuid().ToString("N"));
        var launcher = Path.Combine(root, "scripts", "windows", "run_service.ps1");
        Directory.CreateDirectory(Path.GetDirectoryName(launcher)!);
        File.WriteAllText(launcher, "[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'unexpected.txt'), 'must not launch')");
        var probe = new TcpListener(IPAddress.Loopback, 0); probe.Start();
        var port = ((IPEndPoint)probe.LocalEndpoint).Port; probe.Stop();
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var calls = 0;
        var controller = new LocalServiceProcessControl(new Uri($"http://127.0.0.1:{port}/"), root,
            Path.Combine(root, "owner.json"), TimeSpan.FromMilliseconds(100), () =>
            {
                Interlocked.Increment(ref calls); entered.Set(); release.Wait(TimeSpan.FromSeconds(5)); return [];
            });
        try
        {
            var starting = controller.StartAsync(CancellationToken.None);
            Assert.True(entered.Wait(TimeSpan.FromSeconds(2)));
            Assert.False((await starting).Succeeded);
            var duplicate = await controller.StartAsync(CancellationToken.None);
            Assert.False(duplicate.Succeeded);
            Assert.Contains("still finishing", duplicate.Message);
            Assert.Equal(1, calls);
        }
        finally { release.Set(); }
        await Task.Delay(1000);
        Assert.False(File.Exists(Path.Combine(root, "owner.json")));
        Assert.False(File.Exists(Path.Combine(Path.GetDirectoryName(launcher)!, "unexpected.txt")));
        var resolved = Path.GetFullPath(root);
        if (!resolved.StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase) ||
            !Path.GetFileName(resolved).StartsWith("tts-legacy-test-", StringComparison.Ordinal)) throw new InvalidOperationException();
        Directory.Delete(resolved, true);
    }

    [Fact]
    public void Startup_discovery_uses_current_user_launcher_and_enabled_triggers_not_task_names()
    {
        var root = Path.Combine(Path.GetTempPath(), "tts-legacy-test-" + Guid.NewGuid().ToString("N"));
        var launcher = Path.Combine(root, "scripts", "windows", "run_service.ps1");
        Directory.CreateDirectory(Path.GetDirectoryName(launcher)!);
        File.WriteAllText(launcher, "# Test path marker");
        try
        {
            var sid = UserStartupRegistration.CurrentUserSid();
            var automatic = Definition(launcher, sid, 23456, startup: true);
            var custom = new StartupTaskRecord(@"\Books\Arbitrary name", automatic, true);
            var controller = new LegacyServiceTasks(root, sid, 23456, () =>
            [
                custom,
                new("Disabled", automatic, false),
                new("Manual", Definition(launcher, sid, 23456), true),
                new("Other user", automatic.Replace(sid, sid + "2", StringComparison.Ordinal), true),
                new("Other installation", automatic.Replace("run_scheduled_service.ps1", "other.ps1", StringComparison.Ordinal), true),
            ]);
            Assert.Equal(custom, Assert.Single(controller.ReadStartupConflicts()));
        }
        finally
        {
            var resolved = Path.GetFullPath(root);
            if (!resolved.StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase) ||
                !Path.GetFileName(resolved).StartsWith("tts-legacy-test-", StringComparison.Ordinal)) throw new InvalidOperationException();
            Directory.Delete(resolved, true);
        }
    }

    [Fact]
    public async Task Custom_named_task_is_discovered_started_and_stopped_by_exact_instance()
    {
        await using var fixture = new Fixture();
        Assert.Empty(fixture.Legacy.ReadStartupConflicts()); // Enabled but no automatic trigger.
        await fixture.StartAsync();
        Assert.False((await fixture.Control.StartAsync(CancellationToken.None)).Succeeded);
        var unrelated = fixture.Status with { Resources = fixture.Status.Resources with { ProcessId = Environment.ProcessId } };
        Assert.False((await fixture.Control.VerifyOwnerAsync(unrelated, CancellationToken.None)).Succeeded);
        Assert.True((await fixture.Control.VerifyOwnerAsync(fixture.Status, CancellationToken.None)).Succeeded);
        Assert.False((await fixture.Control.StopAsync(fixture.Status, () => false, CancellationToken.None)).Succeeded);
        Assert.True(await fixture.Control.IsListeningAsync(CancellationToken.None));
        var stopped = await fixture.Control.StopAsync(fixture.Status, () => true, CancellationToken.None);
        Assert.True(stopped.Succeeded, stopped.Message);
        Assert.False(await fixture.Control.IsListeningAsync(CancellationToken.None));
        Assert.NotNull(fixture.Store.Read(fixture.Name)); // Stop is not unregister/disable.
        await fixture.StartAsync(); // Reuses the registered task, not a new direct launcher.
        Assert.False(File.Exists(Path.Combine(fixture.Root, "owner.json")));
        Assert.True((await fixture.Control.VerifyOwnerAsync(fixture.Status, CancellationToken.None)).Succeeded);
        Assert.True((await fixture.Control.StopAsync(fixture.Status, () => true, CancellationToken.None)).Succeeded);
    }

    [Fact]
    public async Task Edited_action_cannot_claim_its_still_running_previous_command()
    {
        await using var fixture = new Fixture();
        await fixture.StartAsync();
        fixture.ChangeDescription(changeAction: true);
        Assert.False((await fixture.Control.VerifyOwnerAsync(fixture.Status, CancellationToken.None)).Succeeded);
        Assert.False((await fixture.Control.StopAsync(fixture.Status, () => true, CancellationToken.None)).Succeeded);
        Assert.True(await fixture.Control.IsListeningAsync(CancellationToken.None));
    }

    [Fact]
    public async Task Task_changed_after_confirmation_is_not_stopped()
    {
        await using var fixture = new Fixture();
        await fixture.StartAsync();
        Assert.True((await fixture.Control.VerifyOwnerAsync(fixture.Status, CancellationToken.None)).Succeeded);
        fixture.ChangeDescription();
        Assert.False((await fixture.Control.StopAsync(fixture.Status, () => true, CancellationToken.None)).Succeeded);
        Assert.True(await fixture.Control.IsListeningAsync(CancellationToken.None));
        Assert.True((await fixture.Control.VerifyOwnerAsync(fixture.Status, CancellationToken.None)).Succeeded);
        Assert.True((await fixture.Control.StopAsync(fixture.Status, () => true, CancellationToken.None)).Succeeded);
    }

    private sealed class Fixture : IAsyncDisposable
    {
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "tts-legacy-test-" + Guid.NewGuid().ToString("N"));
        public string Name { get; } = "TTS Platform Test Legacy " + Guid.NewGuid().ToString("N");
        public WindowsUserStartupTasks Store { get; } = new();
        private string Sid => UserStartupRegistration.CurrentUserSid();
        private string Direct => Path.Combine(Root, "scripts", "windows", "run_service.ps1");
        public LocalServiceProcessControl Control { get; }
        public LegacyServiceTasks Legacy { get; }
        public LocalServiceStatus Status { get; private set; } = null!;
        private Process? _child;
        private readonly int _port;

        public Fixture()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0); probe.Start();
            _port = ((IPEndPoint)probe.LocalEndpoint).Port; probe.Stop();
            Control = new(new Uri($"http://127.0.0.1:{_port}/"), Root, Path.Combine(Root, "owner.json"));
            Legacy = new(Root, Sid, _port);
            Directory.CreateDirectory(Path.GetDirectoryName(Direct)!);
            File.WriteAllText(Direct, "# Fixture discovery marker. Never executed.");
            File.WriteAllText(Path.Combine(Path.GetDirectoryName(Direct)!, "run_scheduled_service.ps1"), """
                param([string]$LogPath, [string]$HostOverride, [int]$Port)
                & "$PSHOME\powershell.exe" -NoProfile -WindowStyle Hidden -File (Join-Path $PSScriptRoot 'child.ps1') -Port $Port
                """);
            File.WriteAllText(Path.Combine(Path.GetDirectoryName(Direct)!, "child.ps1"), """
                param([int]$Port)
                $fixtureListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
                $fixtureListener.Start()
                [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'child.pid'), $PID.ToString())
                try { Start-Sleep -Seconds 50 } finally { $fixtureListener.Stop() }
                """);
            Store.Create(Name, Definition(Direct, Sid, _port), Sid);
        }

        public async Task StartAsync()
        {
            _child?.Dispose(); _child = null;
            var previous = Status?.Resources.ProcessId;
            var started = await Control.StartAsync(CancellationToken.None);
            Assert.True(started.Succeeded, started.Message);
            var pidFile = Path.Combine(Path.GetDirectoryName(Direct)!, "child.pid");
            for (var i = 0; i < 100; i++)
            {
                if (File.Exists(pidFile) && int.TryParse(await File.ReadAllTextAsync(pidFile), out var pid) && pid != previous &&
                    await Control.IsListeningAsync(CancellationToken.None) == true)
                {
                    _child = Process.GetProcessById(pid); _ = _child.Handle;
                    Status = new(1, "synthetic", true, true, "test", "test", 1, 1, true,
                        new(0, 0, 0, 0, 0), false, new("service_process", pid, 0, 0, 1, null));
                    return;
                }
                await Task.Delay(100);
            }
            Assert.Fail("Synthetic scheduled service did not start in ten seconds.");
        }

        public void ChangeDescription(bool changeAction = false)
        {
            var original = Store.Read(Name)!;
            var xml = XDocument.Parse(original.Xml);
            xml.Root!.Element(Ns + "RegistrationInfo")!.Add(new XElement(Ns + "Description", "Concurrent edit test"));
            if (changeAction)
            {
                var args = xml.Root.Element(Ns + "Actions")!.Element(Ns + "Exec")!.Element(Ns + "Arguments")!;
                args.Value = args.Value.Replace(Direct + ".log", Direct + ".other.log", StringComparison.Ordinal);
            }
            WithFolder(folder =>
            {
                object updated = folder.RegisterTask(Name, xml.ToString(), 4, Sid, null, 3, null);
                Marshal.FinalReleaseComObject(updated);
            });
        }

        public ValueTask DisposeAsync()
        {
            // Exact unique test task only. No login trigger or production launcher.
            var record = Store.Read(Name);
            if (record is not null && LegacyServiceTasks.IsControllable(record.Xml, Direct, Sid, _port))
            {
                WithFolder(folder =>
                {
                    object registered = folder.GetTask(Name);
                    try { dynamic task = registered; task.Stop(0); }
                    finally { Marshal.FinalReleaseComObject(registered); }
                });
                if (_child is { HasExited: false })
                {
                    // This held handle belongs only to the synthetic child launched
                    // by this fixture. Scheduler's WM_CLOSE is not reliable cleanup.
                    _child.Kill(entireProcessTree: true);
                    _child.WaitForExit(5000);
                }
                Store.Remove(Store.Read(Name)!);
            }
            _child?.Dispose();
            // Keep fixture files if Windows has not released them yet; no broad delete.
            var resolved = Path.GetFullPath(Root);
            if (!resolved.StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase) ||
                !Path.GetFileName(resolved).StartsWith("tts-legacy-test-", StringComparison.Ordinal))
                throw new InvalidOperationException("Unsafe fixture cleanup target.");
            if (Directory.Exists(resolved)) Directory.Delete(resolved, true);
            return ValueTask.CompletedTask;
        }

        private static void WithFolder(Action<dynamic> operation)
        {
            object scheduler = Activator.CreateInstance(Type.GetTypeFromProgID("Schedule.Service")!)!;
            object? folder = null;
            try { dynamic service = scheduler; service.Connect(); folder = service.GetFolder("\\"); operation(folder); }
            finally { if (folder is not null) Marshal.FinalReleaseComObject(folder); Marshal.FinalReleaseComObject(scheduler); }
        }
    }
}
