using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class LocalServiceProcessControlTests
{
    [Fact]
    public async Task Owned_launcher_tree_obeys_deadline_and_stops_exact_service()
    {
        await using var fixture = new Fixture();
        await fixture.StartAsync();
        Assert.True((await fixture.Control.VerifyOwnerAsync(fixture.Status, CancellationToken.None)).Succeeded);
        var expired = await fixture.Control.StopAsync(fixture.Status, () => false, CancellationToken.None);
        Assert.False(expired.Succeeded);
        Assert.True(await fixture.Control.IsListeningAsync(CancellationToken.None));
        var stopped = await fixture.Control.StopAsync(fixture.Status, () => true, CancellationToken.None);
        Assert.True(stopped.Succeeded, stopped.Message);
        Assert.False(await fixture.Control.IsListeningAsync(CancellationToken.None));
        Assert.False(File.Exists(fixture.LeasePath));
    }

    [Fact]
    public async Task Unrelated_pid_is_not_owned_and_duplicate_start_is_refused()
    {
        await using var fixture = new Fixture();
        await fixture.StartAsync();
        var unrelated = fixture.Status with { Resources = fixture.Status.Resources with { ProcessId = Environment.ProcessId } };
        Assert.False((await fixture.Control.VerifyOwnerAsync(unrelated, CancellationToken.None)).Succeeded);
        Assert.False((await fixture.Control.StopAsync(unrelated, () => true, CancellationToken.None)).Succeeded);
        Assert.False((await fixture.Control.StartAsync(CancellationToken.None)).Succeeded);
        Assert.True(await fixture.Control.IsListeningAsync(CancellationToken.None));
    }

    [Fact]
    public async Task No_ownership_record_means_no_adoption_of_a_listening_service()
    {
        await using var fixture = new Fixture();
        await fixture.StartAsync();
        var unowned = new LocalServiceProcessControl(fixture.Endpoint, fixture.Root, Path.Combine(fixture.Root, "absent-lease.json"));
        Assert.False((await unowned.VerifyOwnerAsync(fixture.Status, CancellationToken.None)).Succeeded);
        Assert.False((await unowned.StopAsync(fixture.Status, () => true, CancellationToken.None)).Succeeded);
        Assert.True(await fixture.Control.IsListeningAsync(CancellationToken.None));
    }

    private sealed class Fixture : IAsyncDisposable
    {
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "tts-service-process-test-" + Guid.NewGuid().ToString("N"));
        public string LeasePath => Path.Combine(Root, "owner.json");
        private string Launcher => Path.Combine(Root, "scripts", "windows", "run_service.ps1");
        private static string PowerShell => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
        public Uri Endpoint { get; }
        public LocalServiceProcessControl Control { get; }
        public LocalServiceStatus Status { get; private set; } = null!;

        public Fixture()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0);
            probe.Start();
            var port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            Endpoint = new Uri($"http://127.0.0.1:{port}/");
            Control = new LocalServiceProcessControl(Endpoint, Root, LeasePath);
            Directory.CreateDirectory(Path.GetDirectoryName(Launcher)!);
            // Synthetic two-process fixture: no Python, models, HTTP credentials,
            // user database, scheduler registration or production port.
            File.WriteAllText(Launcher, """
                param([string]$HostOverride, [int]$Port)
                & "$PSHOME\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'child.ps1') -Port $Port
                """);
            File.WriteAllText(Path.Combine(Path.GetDirectoryName(Launcher)!, "child.ps1"), """
                param([int]$Port)
                $testListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
                $testListener.Start()
                [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'child.pid'), $PID.ToString())
                try { while ($true) { Start-Sleep -Milliseconds 100 } }
                finally { $testListener.Stop() }
                """);
        }

        public async Task StartAsync()
        {
            var result = await Control.StartAsync(CancellationToken.None);
            Assert.True(result.Succeeded, result.Message);
            var pidFile = Path.Combine(Path.GetDirectoryName(Launcher)!, "child.pid");
            for (var attempt = 0; attempt < 100; attempt++)
            {
                if (File.Exists(pidFile) && int.TryParse(await File.ReadAllTextAsync(pidFile), out var pid) &&
                    await Control.IsListeningAsync(CancellationToken.None) == true)
                {
                    Status = new(1, "synthetic", true, true, "test", "test", 1, 1, true,
                        new(0, 0, 0, 0, 0), false, new("service_process", pid, 0, 0, 1, null));
                    return;
                }
                await Task.Delay(100);
            }
            Assert.Fail("Synthetic service did not start in ten seconds.");
        }

        public async ValueTask DisposeAsync()
        {
            // Cleanup can terminate only the process recorded by this isolated fixture.
            var store = new ReaderServiceProcessLeaseStore(LeasePath);
            if (store.TryOpenVerified(Launcher, PowerShell, out var owner, out _))
            {
                using (owner)
                {
                    if (!owner!.HasExited) owner.Kill(entireProcessTree: true);
                    await owner.WaitForExitAsync();
                }
            }
            var resolved = Path.GetFullPath(Root);
            if (!resolved.StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase) ||
                !Path.GetFileName(resolved).StartsWith("tts-service-process-test-", StringComparison.Ordinal))
                throw new InvalidOperationException("Unsafe fixture cleanup target.");
            if (Directory.Exists(resolved)) Directory.Delete(resolved, recursive: true);
        }
    }
}
