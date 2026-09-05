using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Windows;

public sealed class AgentConnectionFiles(string? directory = null)
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
    };
    private readonly string _directory = directory ?? DesktopPaths.AgentConnectionsDirectory;

    public string ConfigurationPath(string grantId) => Path.Combine(_directory, $"{Identifier(grantId)}.json");

    public bool HasConnection(string grantId) => File.Exists(ConfigurationPath(grantId)) &&
        File.Exists(Path.Combine(_directory, $"{Identifier(grantId)}.bin"));

    public string Save(ReaderAgentProvisionResult provision, string serviceBaseUrl)
    {
        var id = Identifier(provision.Grant.Id);
        var url = ServiceBaseUrl.Parse(serviceBaseUrl).AbsoluteUri;
        if (!Regex.IsMatch(provision.Credential, "^rdr_agent_[A-Za-z0-9_-]{43}$"))
        {
            throw new ReaderClientConfigurationException("The service returned an invalid agent credential.");
        }
        var path = ConfigurationPath(id);
        var protectedPath = Path.Combine(_directory, $"{id}.bin");
        if (File.Exists(path) || File.Exists(protectedPath))
        {
            throw new ReaderClientConfigurationException("A local connection already exists for this grant.");
        }
        Directory.CreateDirectory(_directory);
        var temporary = path + $".{Guid.NewGuid():N}.tmp";
        var store = new DpapiCredentialStore(_directory);
        try
        {
            store.Save(id, provision.Credential);
            File.WriteAllText(temporary, JsonSerializer.Serialize(new
            {
                Version = 1,
                ServiceBaseUrl = url,
                GrantId = id,
            }, JsonOptions));
            File.Move(temporary, path);
            return path;
        }
        catch
        {
            store.Delete(id);
            throw;
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    public void RemoveRevoked(string grantId)
    {
        // Only call after the service confirms revocation. These local files
        // contain configuration and now-unusable encrypted credentials, not articles.
        new DpapiCredentialStore(_directory).Delete(grantId);
        File.Delete(ConfigurationPath(grantId));
    }

    public string ClientConfiguration(string grantId, string pythonExecutable)
    {
        if (!HasConnection(grantId))
        {
            throw new ReaderClientConfigurationException("The local connection file is missing. Provision a new grant.");
        }
        var python = ValidatePython(pythonExecutable);
        return JsonSerializer.Serialize(new
        {
            mcpServers = new Dictionary<string, object>
            {
                ["tts-platform-reader"] = new
                {
                    command = python,
                    args = new[] { "-m", "reader_agent.server", "--config", ConfigurationPath(grantId) },
                },
            },
        }, new JsonSerializerOptions { WriteIndented = true });
    }

    public async Task<bool> CheckAsync(string grantId, string pythonExecutable, CancellationToken cancellationToken = default)
    {
        var start = new ProcessStartInfo(ValidatePython(pythonExecutable))
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in new[] { "-m", "reader_agent.server", "--config", ConfigurationPath(grantId), "--check" })
        {
            start.ArgumentList.Add(argument);
        }
        using var process = Process.Start(start) ?? throw new IOException("Could not start the Reader agent check.");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        try
        {
            var output = process.StandardOutput.ReadToEndAsync(timeout.Token);
            var errors = process.StandardError.ReadToEndAsync(timeout.Token);
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
            var result = await output.ConfigureAwait(false);
            _ = await errors.ConfigureAwait(false); // Do not forward subprocess details/secrets to UI logs.
            if (process.ExitCode != 0)
            {
                return false;
            }
            using var payload = JsonDocument.Parse(result);
            return payload.RootElement.TryGetProperty("ready", out var ready) && ready.ValueKind is JsonValueKind.True;
        }
        finally
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync(CancellationToken.None).ConfigureAwait(false);
            }
        }
    }

    public static string? FindAgentPython()
    {
        foreach (var start in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory })
        {
            for (var current = new DirectoryInfo(start); current is not null; current = current.Parent)
            {
                if (!File.Exists(Path.Combine(current.FullName, "pyproject.toml")))
                {
                    continue;
                }
                var python = Path.Combine(current.FullName, ".venv-agent", "Scripts", "python.exe");
                if (File.Exists(python))
                {
                    return python;
                }
            }
        }
        return null;
    }

    private static string ValidatePython(string path)
    {
        if (!Path.IsPathFullyQualified(path) || !File.Exists(path) ||
            !string.Equals(Path.GetExtension(path), ".exe", StringComparison.OrdinalIgnoreCase))
        {
            throw new ReaderClientConfigurationException("Select the Python executable from the installed Reader agent environment.");
        }
        return Path.GetFullPath(path);
    }

    private static string Identifier(string value) => Guid.TryParse(value, out var id)
        ? id.ToString("D")
        : throw new ReaderClientConfigurationException("The agent grant identifier is invalid.");
}
