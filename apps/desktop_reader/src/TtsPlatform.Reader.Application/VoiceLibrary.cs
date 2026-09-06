namespace TtsPlatform.Reader.Application;

// Local model-manager contract, deliberately separate from public TTS APIs.
public sealed record InstalledLibraryVoice(string Id, string Name, string Language, string Family,
    string License, string PackageSource, bool AssetsPresent, bool IsConfiguredDefault)
{
    public string Details => $"{Language} · {Family} · {License}";
    public string FileStatus => AssetsPresent ? "Files present · service load not checked" : "Files missing or configuration incomplete";
    public string DefaultLabel => IsConfiguredDefault ? "Configured service default" : "";
}

public sealed record PackageLibraryVoice(string Id, string Name, string Language);
public sealed record VoiceLibraryPackage(string Id, string Name, string Language, string Family,
    long? SizeBytes, string License, string? LicenseUrl, string? SourceUrl,
    IReadOnlyList<PackageLibraryVoice> Voices, bool Installed, bool CanInstall, string? UnavailableReason)
{
    public string SizeLabel => SizeBytes is > 0 ? $"{SizeBytes.Value / 1048576d:N1} MiB download" : "Download size unknown";
    public string Details => $"{Language} · {Family} · {SizeLabel} · {Voices.Count} voice(s)";
    public string Availability => CanInstall ? "Available to install" : UnavailableReason ?? "Unavailable";
}

public sealed record VoiceLibraryInventory(string CatalogFingerprint, string ManifestFingerprint,
    string? ConfiguredDefault, bool ConfigValid, IReadOnlyList<InstalledLibraryVoice> InstalledVoices,
    IReadOnlyList<VoiceLibraryPackage> Packages, string? ConfigFingerprint = null);

public sealed record VoiceInstallationProgress(string Phase, long? Completed, long? Total, bool Cancellable)
{
    public double? Percent => Total is > 0 && Completed is >= 0
        ? Math.Clamp(100d * Completed.Value / Total.Value, 0, 100) : null;
    public string Label => Phase switch
    {
        "resolving" => "Checking the reviewed package",
        "downloading" => "Downloading",
        "verifying" => "Verifying SHA-256",
        "extracting" => "Unpacking and checking voice files",
        "committing" => "Registering voices — please wait",
        "completed" => "Installation committed",
        _ => "Waiting for the installer",
    };
    public string Display => Percent is { } percent ? $"{Label} · {percent:N0}%" : Label;
}

public sealed record VoiceInstallationOutcome(bool Succeeded, bool Cancelled, string Message);
public sealed class VoiceLibraryException(string message) : Exception(message);

public interface ILocalVoiceLibrary
{
    Task<VoiceLibraryInventory> ListAsync(CancellationToken cancellationToken);
    Task<VoiceInstallationOutcome> InstallAsync(string packageId, string catalogFingerprint,
        bool acceptedLicense, IProgress<VoiceInstallationProgress> progress, CancellationToken cancellationToken);
    Task SetDefaultAsync(string voiceId, string manifestFingerprint, string configFingerprint, CancellationToken cancellationToken);
}

// Owned by the tray host, not a window. Closing/reopening the panel keeps the
// active task and its cancellation source; an observation timeout is not exit.
public sealed class VoiceLibraryController(ILocalVoiceLibrary library)
{
    public event EventHandler? Changed;
    public VoiceLibraryInventory? Inventory { get; private set; }
    public VoiceInstallationProgress? Progress { get; private set; }
    public string Message { get; private set; } = "Open this tab to read the local voice library.";
    public bool IsBusy { get; private set; }
    public bool IsInstalling { get; private set; }
    public bool CancelRequested { get; private set; }
    public bool CanCancel => IsInstalling && !CancelRequested && (Progress?.Cancellable ?? true);
    private CancellationTokenSource? _operation;
    private int _generation;

    public async Task RefreshAsync()
    {
        if (IsBusy) return;
        Begin(installing: false);
        Message = "Reading installed voices and the local package catalog…";
        Notify();
        try
        {
            Inventory = await library.ListAsync(_operation!.Token);
            Message = $"{Inventory.InstalledVoices.Count} installed voices · {Inventory.Packages.Count} catalog packages. Files present does not mean loaded in the running service.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            Inventory = null;
            Message = SafeMessage(exception);
        }
        finally { End(); }
    }

    public async Task InstallAsync(string packageId, bool acceptedLicense)
    {
        if (IsBusy) return;
        var package = Inventory?.Packages.FirstOrDefault(value => value.Id == packageId);
        if (!acceptedLicense || package?.CanInstall != true)
        {
            Message = "Select an available package and review its voice license before installing.";
            Notify();
            return;
        }
        var fingerprint = Inventory!.CatalogFingerprint;
        Begin(installing: true);
        var generation = _generation;
        Message = $"Installing {package.Name}. Existing voices and the running service stay unchanged.";
        Notify();
        var progress = new Progress<VoiceInstallationProgress>(value =>
        {
            if (!IsInstalling || generation != _generation) return;
            Progress = value;
            Notify();
        });
        try
        {
            var result = await library.InstallAsync(packageId, fingerprint, true, progress, _operation!.Token);
            IsInstalling = false; // The helper has actually exited, not just emitted 100%.
            Progress = null;
            Message = result.Message;
            Notify();
            // A committed result wins a late cancellation. Read actual state
            // with a fresh token, including after failure/uncertain outcomes.
            try { Inventory = await library.ListAsync(CancellationToken.None); }
            catch (Exception exception) when (IsExpected(exception))
            { Inventory = null; Message += " Refresh the library to confirm its current state."; }
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            Inventory = null;
            Message = SafeMessage(exception) + " Refresh before retrying.";
        }
        finally { End(); }
    }

    public void Cancel()
    {
        if (!CanCancel) return;
        CancelRequested = true;
        Message = "Cancellation requested. Waiting for the installer to finish safely; a commit already in progress will complete.";
        _operation!.Cancel();
        Notify();
    }

    public bool CanSetDefault(string? voiceId) => !IsBusy && Inventory is { ConfigValid: true, ConfigFingerprint.Length: 64 } &&
        Inventory.InstalledVoices.Count(voice => voice.Id == voiceId) == 1 &&
        Inventory.InstalledVoices.Any(voice => voice.Id == voiceId && voice.AssetsPresent && !voice.IsConfiguredDefault);

    public async Task SetDefaultAsync(string voiceId)
    {
        if (!CanSetDefault(voiceId)) return;
        var reviewed = Inventory!;
        Begin(installing: false);
        Message = "Saving the service default for the next restart. Current playback is unchanged…";
        Notify();
        try
        {
            await library.SetDefaultAsync(voiceId, reviewed.ManifestFingerprint, reviewed.ConfigFingerprint!, _operation!.Token);
            Message = "Service default saved for the next explicit restart. Running speech and Reader's own voice preference are unchanged.";
            try { Inventory = await library.ListAsync(CancellationToken.None); }
            catch (Exception exception) when (IsExpected(exception))
            { Inventory = null; Message += " Refresh to confirm the saved setting."; }
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            Inventory = null;
            Message = SafeMessage(exception) + " Refresh before retrying.";
        }
        finally { End(); }
    }

    public void OwnerClosing() => _operation?.Cancel();
    private void Begin(bool installing)
    {
        _operation = new CancellationTokenSource();
        IsBusy = true;
        IsInstalling = installing;
        CancelRequested = false;
        Progress = null;
        _generation++;
    }
    private void End()
    {
        IsBusy = IsInstalling = false;
        Progress = null;
        _operation?.Dispose();
        _operation = null;
        Notify();
    }
    private void Notify() => Changed?.Invoke(this, EventArgs.Empty);
    private static bool IsExpected(Exception exception) => exception is VoiceLibraryException or
        IOException or UnauthorizedAccessException or OperationCanceledException or System.ComponentModel.Win32Exception;
    private static string SafeMessage(Exception exception) => exception is VoiceLibraryException
        ? exception.Message : "The local voice operation could not be completed. Check the local Python installation and file access.";
}
