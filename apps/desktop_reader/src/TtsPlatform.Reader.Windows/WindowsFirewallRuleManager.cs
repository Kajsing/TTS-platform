using System.ComponentModel;
using System.Diagnostics;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Windows;

public sealed class WindowsFirewallRuleManager(string? scriptPath = null)
{
    public string ScriptPath { get; } = scriptPath ?? Path.Combine(
        AppContext.BaseDirectory,
        "reader_remote_firewall.ps1");

    public Task CreateAsync(
        RemoteServerProfile profile,
        CancellationToken cancellationToken = default) =>
        RunElevatedAsync(CreateArguments(profile), cancellationToken);

    public Task RemoveAsync(
        string profileId,
        CancellationToken cancellationToken = default) =>
        RunElevatedAsync(RemoveArguments(profileId), cancellationToken);

    public IReadOnlyList<string> CreateArguments(RemoteServerProfile profile)
    {
        ArgumentNullException.ThrowIfNull(profile);
        if (!Guid.TryParse(profile.ProfileId, out _))
        {
            throw new ReaderClientConfigurationException("The remote profile id is invalid.");
        }
        return
        [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ScriptPath,
            "-Action",
            "Create",
            "-ProfileId",
            profile.ProfileId,
            "-LocalAddress",
            profile.BindHost,
            "-LocalPort",
            profile.Port.ToString(),
            "-Mode",
            profile.FirewallMode,
            "-RemoteAddress",
            profile.FirewallRemoteAddress,
            "-NetworkProfile",
            profile.FirewallProfile,
            "-Program",
            profile.GatewayProgram,
            .. string.IsNullOrWhiteSpace(profile.FirewallInterfaceAlias)
                ? []
                : new[] { "-InterfaceAlias", profile.FirewallInterfaceAlias },
        ];
    }

    public IReadOnlyList<string> RemoveArguments(string profileId)
    {
        if (!Guid.TryParse(profileId, out _))
        {
            throw new ReaderClientConfigurationException("The remote profile id is invalid.");
        }
        return
        [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ScriptPath,
            "-Action",
            "Remove",
            "-ProfileId",
            profileId,
        ];
    }

    private async Task RunElevatedAsync(
        IReadOnlyList<string> arguments,
        CancellationToken cancellationToken)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Windows Firewall setup requires Windows.");
        }
        if (!File.Exists(ScriptPath))
        {
            throw new ReaderClientConfigurationException("The Reader firewall helper is missing.");
        }
        var startInfo = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }
        try
        {
            using var process = Process.Start(startInfo)
                ?? throw new ReaderClientConfigurationException(
                    "Windows Firewall setup could not be started.");
            await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            if (process.ExitCode != 0)
            {
                throw new ReaderClientConfigurationException(
                    "Windows Firewall did not accept the exact Reader rule.");
            }
        }
        catch (Win32Exception exception) when (exception.NativeErrorCode == 1223)
        {
            throw new ReaderClientConfigurationException(
                "Windows Firewall permission was cancelled.",
                exception);
        }
    }
}
