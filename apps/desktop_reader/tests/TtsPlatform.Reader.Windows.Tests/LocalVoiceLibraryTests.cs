using System.Diagnostics;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class LocalVoiceLibraryTests
{
    [Theory]
    [InlineData("next", "restart_required", true)]
    [InlineData("wrong", "restart_required", false)]
    [InlineData("next", "applied", false)]
    public async Task Default_selection_requires_matching_confirmed_deferred_result(string voice, string activation, bool success)
    {
        var payload = JsonSerializer.Serialize(new { contract_version = 1, @event = "result", data = new { voice_id = voice, activation } });
        using var fixture = new Fixture($"[Console]::Out.WriteLine('{payload}')\nexit 0");
        var operation = fixture.Library.SetDefaultAsync("next", Fingerprint, Fingerprint, CancellationToken.None);
        if (success) await operation;
        else await Assert.ThrowsAsync<VoiceLibraryException>(() => operation);
    }

    [Fact]
    public async Task Default_commit_waits_for_actual_exit_even_after_late_cancel()
    {
        var payload = JsonSerializer.Serialize(new { contract_version = 1, @event = "result", data = new { voice_id = "next", activation = "restart_required" } });
        using var fixture = new Fixture($"[Console]::Out.WriteLine('{payload}')\n[Console]::Out.Flush()\n$line = [Console]::ReadLine()\nexit 0");
        using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(1));
        var operation = fixture.Library.SetDefaultAsync("next", Fingerprint, Fingerprint, cancellation.Token);
        await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Library.ListAsync(CancellationToken.None));
        await operation.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.True(cancellation.IsCancellationRequested);
    }

    private const string Fingerprint = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private const string Result = """{"contract_version":1,"event":"result","data":{"checksum_verified":true,"activation":"restart_required"}}""";
    private const string Progress = """{"contract_version":1,"event":"progress","phase":"downloading","completed":5,"total":10,"cancellable":true}""";

    [Fact]
    public async Task Terminal_event_does_not_release_gate_until_process_really_exits()
    {
        using var fixture = new Fixture($"""
            [Console]::Out.WriteLine('{Progress}')
            [Console]::Out.WriteLine('{Result}')
            [Console]::Out.Flush()
            $line = [Console]::ReadLine()
            exit 0
            """);
        using var cancel = new CancellationTokenSource();
        var ready = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var operation = fixture.Library.InstallAsync("new", Fingerprint, true,
            new ImmediateProgress(_ => ready.TrySetResult()), cancel.Token);
        await ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.False(operation.IsCompleted);
        await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Library.ListAsync(CancellationToken.None));
        cancel.Cancel(); // A completed commit wins this late cancellation.
        var outcome = await operation.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.True(outcome.Succeeded);
        Assert.False(outcome.Cancelled);
    }

    [Fact]
    public async Task Cancellation_and_timeout_signal_stdin_but_do_not_kill_installer()
    {
        using var fixture = new Fixture($$"""
            [Console]::Out.WriteLine('{{Progress}}')
            [Console]::Out.Flush()
            $line = [Console]::ReadLine()
            if ($line -ne '{"cancel":true}') { exit 9 }
            Start-Sleep -Milliseconds 500
            [Console]::Out.WriteLine('{"contract_version":1,"event":"cancelled","message":"Cancelled safely."}')
            exit 2
            """, installTimeout: TimeSpan.FromMilliseconds(100));
        var ready = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var operation = fixture.Library.InstallAsync("new", Fingerprint, true,
            new ImmediateProgress(_ => ready.TrySetResult()), CancellationToken.None);
        await ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.False(operation.IsCompleted);
        await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Library.ListAsync(CancellationToken.None));
        var outcome = await operation.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.True(outcome.Cancelled);
        Assert.False(outcome.Succeeded);
    }

    [Theory]
    [InlineData("missing")]
    [InlineData("duplicate")]
    [InlineData("version")]
    [InlineData("truncated")]
    [InlineData("invalid-data")]
    public async Task Malformed_or_missing_outcomes_never_claim_success_or_echo_stderr(string fault)
    {
        var lines = fault switch
        {
            "missing" => "",
            "duplicate" => $"[Console]::Out.WriteLine('{Result}')\n[Console]::Out.WriteLine('{Result}')",
            "version" => $"[Console]::Out.WriteLine('{Result.Replace("\"contract_version\":1", "\"contract_version\":99")}')",
            "truncated" => $"[Console]::Out.Write('{Result}')",
            _ => "[Console]::Out.WriteLine('{\"contract_version\":1,\"event\":\"result\"}')",
        };
        using var fixture = new Fixture($"[Console]::Error.WriteLine('secret-marker')\n{lines}\nexit 0");
        var exception = await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Library.InstallAsync("new", Fingerprint, true,
            new ImmediateProgress(_ => { }), CancellationToken.None));
        Assert.DoesNotContain("secret-marker", exception.Message);
    }

    [Fact]
    public async Task Inventory_preserves_unicode_and_metadata_without_loading_an_engine()
    {
        var payload = JsonSerializer.Serialize(new
        {
            contract_version = 1,
            @event = "result",
            data = new
            {
                catalog_fingerprint = Fingerprint,
                manifest_fingerprint = Fingerprint,
                config_fingerprint = Fingerprint,
                configured_default = "da",
                config_valid = true,
                installed_voices = new[] { new { id = "da", name = "Dansk stemme æøå", language = "da-DK", family = "vits", license = "fixture", package_source = "models/voices/da", assets_present = true, is_configured_default = true } },
                packages = Array.Empty<object>(),
            },
        });
        using var fixture = new Fixture($"[Console]::Out.WriteLine('{payload}')\nexit 0");
        var inventory = await fixture.Library.ListAsync(CancellationToken.None);
        Assert.Equal("Dansk stemme æøå", Assert.Single(inventory.InstalledVoices).Name);
        Assert.True(inventory.InstalledVoices[0].AssetsPresent);
    }

    [Fact]
    public async Task Oversized_protocol_is_drained_and_rejected_without_echoing_content()
    {
        using var fixture = new Fixture("[Console]::Out.WriteLine(('x' * 4194305))\nexit 0");
        await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Library.ListAsync(CancellationToken.None));
    }

    [Fact]
    public async Task Already_cancelled_operation_does_not_start_a_helper()
    {
        var called = false;
        var library = new LocalVoiceLibrary(isolatedCommand: (_, _) => { called = true; throw new InvalidOperationException(); });
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => library.ListAsync(cancellation.Token));
        Assert.False(called);
    }

    [Fact]
    public void Launcher_keeps_repo_and_package_as_separate_arguments_with_no_shell()
    {
        using var fixture = new Fixture("exit 0");
        Directory.CreateDirectory(Path.Combine(fixture.Root, "scripts", "windows"));
        File.WriteAllText(Path.Combine(fixture.Root, "scripts", "windows", "run_service.ps1"), "# fixture marker only");
        var start = LocalVoiceLibrary.BuildStartInfo("install", ["--package-id", "one value & another"], fixture.Root);
        Assert.Contains(fixture.Root, start.ArgumentList);
        Assert.Contains("one value & another", start.ArgumentList);
        Assert.Contains("tts_service.model_manager", start.ArgumentList);
        Assert.Equal(fixture.Root, start.WorkingDirectory);
        Assert.Contains(Path.Combine(fixture.Root, "apps/tts_service/src"), start.Environment["PYTHONPATH"]);
        Assert.False(start.UseShellExecute);
    }

    private sealed class ImmediateProgress(Action<VoiceInstallationProgress> action) : IProgress<VoiceInstallationProgress>
    { public void Report(VoiceInstallationProgress value) => action(value); }

    private sealed class Fixture : IDisposable
    {
        internal string Root { get; } = Path.Combine(Path.GetTempPath(), "tts voice bridge " + Guid.NewGuid().ToString("N"));
        internal LocalVoiceLibrary Library { get; }
        public Fixture(string script, TimeSpan? installTimeout = null)
        {
            Directory.CreateDirectory(Root);
            var path = Path.Combine(Root, "synthetic-helper.ps1");
            File.WriteAllText(path, "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n" + script);
            Library = new LocalVoiceLibrary(isolatedCommand: (_, _) =>
            {
                var start = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),
                    "System32", "WindowsPowerShell", "v1.0", "powershell.exe"));
                foreach (var argument in new[] { "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path }) start.ArgumentList.Add(argument);
                return start;
            }, installTimeout: installTimeout ?? TimeSpan.FromSeconds(5));
        }
        public void Dispose() => Directory.Delete(Root, recursive: true);
    }
}
