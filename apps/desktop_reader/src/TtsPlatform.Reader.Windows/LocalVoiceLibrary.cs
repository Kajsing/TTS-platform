using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

public sealed class LocalVoiceLibrary(string? startDirectory = null,
    Func<string, IReadOnlyList<string>, ProcessStartInfo>? isolatedCommand = null,
    TimeSpan? readTimeout = null, TimeSpan? installTimeout = null) : ILocalVoiceLibrary
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private const int MaxLine = 4 * 1024 * 1024;

    public async Task<VoiceLibraryInventory> ListAsync(CancellationToken cancellationToken)
    {
        var terminal = await ExecuteAsync("list", [], null, cancellationToken).ConfigureAwait(false);
        if (terminal.Event != "result") throw new VoiceLibraryException(terminal.Message);
        try
        {
            var inventory = terminal.Data.Deserialize<VoiceLibraryInventory>(Json);
            if (inventory is null || inventory.InstalledVoices is null || inventory.Packages is null ||
                !ValidFingerprint(inventory.CatalogFingerprint) || !ValidFingerprint(inventory.ManifestFingerprint) ||
                !ValidFingerprint(inventory.ConfigFingerprint) ||
                inventory.InstalledVoices.Count > 2048 || inventory.Packages.Count > 512 ||
                inventory.InstalledVoices.Any(voice => voice is null || string.IsNullOrWhiteSpace(voice.Id) || voice.Name is null) ||
                inventory.Packages.Any(package => package is null || string.IsNullOrWhiteSpace(package.Id) ||
                    package.Name is null || package.Voices is null || package.Voices.Count > 256))
                throw new JsonException();
            return inventory;
        }
        catch (Exception exception) when (exception is JsonException or InvalidOperationException)
        { throw new VoiceLibraryException("The local voice inventory is invalid. Nothing was changed."); }
    }

    public async Task<VoiceInstallationOutcome> InstallAsync(string packageId, string catalogFingerprint,
        bool acceptedLicense, IProgress<VoiceInstallationProgress> progress, CancellationToken cancellationToken)
    {
        if (!acceptedLicense || string.IsNullOrWhiteSpace(packageId) || packageId.Length > 256 || !ValidFingerprint(catalogFingerprint))
            throw new VoiceLibraryException("Package-specific license and catalog review are required.");
        var result = await ExecuteAsync("install", ["--package-id", packageId, "--catalog-fingerprint", catalogFingerprint, "--accept-license"],
            progress, cancellationToken).ConfigureAwait(false);
        if (result.Event == "result")
        {
            if (result.Data.ValueKind != JsonValueKind.Object ||
                !result.Data.TryGetProperty("checksum_verified", out var verified) || verified.ValueKind != JsonValueKind.True ||
                !result.Data.TryGetProperty("activation", out var activation) || activation.ValueKind != JsonValueKind.String ||
                activation.GetString() != "restart_required")
                throw new VoiceLibraryException("Installation result could not be verified. Refresh the library before retrying.");
            return new(true, false, "Installed and files verified. The running service was not changed. Restart it explicitly when idle to load the new voices.");
        }
        return new(false, result.Event == "cancelled", result.Message);
    }

    private sealed record Terminal(string Event, JsonElement Data, string Message);

    public async Task SetDefaultAsync(string voiceId, string manifestFingerprint, string configFingerprint, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(voiceId) || voiceId.Length > 256 ||
            !ValidFingerprint(manifestFingerprint) || !ValidFingerprint(configFingerprint))
            throw new VoiceLibraryException("Refresh the installed voices before selecting a service default.");
        var result = await ExecuteAsync("set-default", ["--voice-id", voiceId,
            "--manifest-fingerprint", manifestFingerprint, "--config-fingerprint", configFingerprint], null, cancellationToken).ConfigureAwait(false);
        if (result.Event != "result") throw new VoiceLibraryException(result.Message);
        if (result.Data.ValueKind != JsonValueKind.Object ||
            !result.Data.TryGetProperty("voice_id", out var selected) || selected.ValueKind != JsonValueKind.String || selected.GetString() != voiceId ||
            !result.Data.TryGetProperty("activation", out var activation) || activation.ValueKind != JsonValueKind.String || activation.GetString() != "restart_required")
            throw new VoiceLibraryException("The saved service default could not be verified. Refresh before retrying.");
    }

    private async Task<Terminal> ExecuteAsync(string command, IReadOnlyList<string> arguments,
        IProgress<VoiceInstallationProgress>? progress, CancellationToken cancellationToken)
    {
        if (!await _gate.WaitAsync(0, cancellationToken).ConfigureAwait(false))
            throw new VoiceLibraryException("Another local voice operation is still running.");
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            var start = isolatedCommand is null ? BuildStartInfo(command, arguments, startDirectory) : isolatedCommand(command, arguments);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.RedirectStandardInput = start.RedirectStandardOutput = start.RedirectStandardError = true;
            start.StandardOutputEncoding = start.StandardErrorEncoding = Encoding.UTF8;
            using var process = Process.Start(start) ?? throw new VoiceLibraryException("The local model helper could not start.");
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(command == "install" ? installTimeout ?? TimeSpan.FromMinutes(31) : readTimeout ?? TimeSpan.FromSeconds(20));
            var cancelSent = 0;
            Task? cancelWrite = null;
            void CancelHelper()
            {
                if (Interlocked.Exchange(ref cancelSent, 1) != 0) return;
                if (command == "list")
                {
                    // This helper is read-only and ours; never use this path for installation.
                    try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
                    catch (Exception exception) when (exception is InvalidOperationException or Win32Exception) { }
                }
                else cancelWrite = SendCancelAsync(process);
            }
            using var registration = timeout.Token.Register(CancelHelper);
            Terminal? terminal = null;
            var invalid = false;
            var output = ReadOutputAsync(process.StandardOutput, line =>
            {
                if (invalid) return;
                try
                {
                    using var document = JsonDocument.Parse(line);
                    var item = document.RootElement;
                    if (item.GetProperty("contract_version").GetInt32() != 1) throw new JsonException();
                    var kind = item.GetProperty("event").GetString();
                    if (terminal is not null) throw new JsonException();
                    if (kind == "progress" && command == "install")
                    {
                        var value = item.Deserialize<VoiceInstallationProgress>(Json) ?? throw new JsonException();
                        if (value.Phase is not ("resolving" or "downloading" or "verifying" or "extracting" or "committing" or "completed") ||
                            value.Completed < 0 || value.Total < 0) throw new JsonException();
                        progress?.Report(value);
                    }
                    else if (kind is "result" or "cancelled" or "failed")
                    {
                        var message = item.TryGetProperty("message", out var text) ? text.GetString() : null;
                        terminal = new(kind, item.TryGetProperty("data", out var data) ? data.Clone() : default,
                            message is { Length: <= 1024 } ? message : "The local model operation failed. Refresh actual state before retrying.");
                    }
                    else throw new JsonException();
                }
                catch (Exception exception) when (exception is JsonException or InvalidOperationException or KeyNotFoundException or FormatException)
                { invalid = true; CancelHelper(); }
            }, () => { invalid = true; CancelHelper(); });
            var errors = DiscardAsync(process.StandardError);
            // No cancellation/observation timeout releases this gate. Installation
            // owns rollback and commit; keep draining pipes and await actual exit.
            await Task.WhenAll(output, errors, process.WaitForExitAsync()).ConfigureAwait(false);
            if (cancelWrite is not null) await cancelWrite.ConfigureAwait(false);
            var expected = terminal?.Event switch { "result" => 0, "cancelled" => 2, "failed" => 1, _ => -1 };
            if (invalid || terminal is null || process.ExitCode != expected)
                throw new VoiceLibraryException(command == "list"
                    ? "The local voice inventory could not be read. Check Python and refresh."
                    : "The voice helper exited without a verified outcome. Refresh actual state before retrying.");
            return terminal;
        }
        finally { _gate.Release(); }
    }

    private static async Task SendCancelAsync(Process process)
    {
        try
        {
            await process.StandardInput.WriteLineAsync("{\"cancel\":true}").ConfigureAwait(false);
            await process.StandardInput.FlushAsync().ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is IOException or InvalidOperationException or ObjectDisposedException) { }
    }

    private static async Task ReadOutputAsync(StreamReader reader, Action<string> line, Action invalid)
    {
        var buffer = new char[4096];
        var pending = new StringBuilder();
        var oversized = false;
        int count;
        while ((count = await reader.ReadAsync(buffer).ConfigureAwait(false)) != 0)
        {
            for (var i = 0; i < count; i++)
            {
                if (buffer[i] == '\n')
                {
                    if (!oversized && pending.Length > 0) line(pending.ToString());
                    pending.Clear();
                }
                else if (!oversized && buffer[i] != '\r')
                {
                    if (pending.Length >= MaxLine) { oversized = true; pending.Clear(); invalid(); }
                    else pending.Append(buffer[i]);
                }
            }
        }
        if (pending.Length != 0) invalid(); // A terminal line must be complete.
    }

    private static async Task DiscardAsync(StreamReader reader)
    {
        var buffer = new char[4096];
        while (await reader.ReadAsync(buffer).ConfigureAwait(false) != 0) { }
    }

    private static bool ValidFingerprint(string? value) => value is { Length: 64 } && value.All(Uri.IsHexDigit);

    public static ProcessStartInfo BuildStartInfo(string command, IReadOnlyList<string> arguments, string? startDirectory = null)
    {
        if (command is not ("list" or "install" or "set-default")) throw new ArgumentOutOfRangeException(nameof(command));
        var launcher = ScheduledServiceController.FindLocalServiceLauncher(startDirectory ?? AppContext.BaseDirectory)
            ?? throw new VoiceLibraryException("The local TTS installation could not be found.");
        var root = launcher.Directory!.Parent!.Parent!.FullName;
        var start = new ProcessStartInfo { WorkingDirectory = root };
        var python = Environment.GetEnvironmentVariable("TTS_PLATFORM_PYTHON");
        var venv = Path.Combine(root, ".venv", "Scripts", "python.exe");
        if (!string.IsNullOrWhiteSpace(python)) start.FileName = python;
        else if (File.Exists(venv)) start.FileName = venv;
        else if (FindOnPath("py.exe") is { } py) { start.FileName = py; start.ArgumentList.Add("-3"); }
        else start.FileName = FindOnPath("python.exe") ?? "python.exe";
        start.ArgumentList.Add("-m");
        start.ArgumentList.Add("tts_service.model_manager");
        start.ArgumentList.Add(command);
        start.ArgumentList.Add("--repo-root");
        start.ArgumentList.Add(root);
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        var paths = new[] { "apps/tts_service/src", "packages/tts_core/src", "packages/reader_core/src", "packages/document_import/src", "packages/speech_rules/src" }
            .Select(path => Path.Combine(root, path)).ToList();
        if (Environment.GetEnvironmentVariable("PYTHONPATH") is { Length: > 0 } inherited) paths.Add(inherited);
        start.Environment["PYTHONPATH"] = string.Join(Path.PathSeparator, paths);
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        start.Environment["PYTHONUNBUFFERED"] = "1";
        return start;
    }

    private static string? FindOnPath(string name) => (Environment.GetEnvironmentVariable("PATH") ?? "")
        .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
        .Select(path => Path.Combine(path.Trim('"'), name)).FirstOrDefault(File.Exists);
}
