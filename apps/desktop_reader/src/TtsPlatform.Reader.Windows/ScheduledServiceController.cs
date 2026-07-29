using System.ComponentModel;
using System.Diagnostics;

namespace TtsPlatform.Reader.Windows;

public static class ScheduledServiceController
{
    public const string TaskName = "TTS Platform Local Reader";

    private static readonly object ProcessGate = new();
    private static Process? _ownedServiceProcess;

    public static bool OwnsRunningService
    {
        get
        {
            lock (ProcessGate)
            {
                return _ownedServiceProcess is { HasExited: false };
            }
        }
    }

    public static bool TryStart(out string message)
    {
        lock (ProcessGate)
        {
            if (_ownedServiceProcess is { HasExited: false })
            {
                message = "The Reader-started local service is already running.";
                return true;
            }
            _ownedServiceProcess?.Dispose();
            _ownedServiceProcess = null;
        }

        if (TryRunScheduledTask("/Run", out _))
        {
            message = "The per-user local service was started.";
            return true;
        }

        var launcher = FindLocalServiceLauncher(AppContext.BaseDirectory);
        if (launcher is null)
        {
            message =
                "The per-user service task is not installed and the local service launcher was not found. " +
                "Run `tts service-install --user` from the source bundle.";
            return false;
        }

        try
        {
            var process = Process.Start(new ProcessStartInfo
            {
                FileName = WindowsPowerShellPath(),
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                WorkingDirectory = launcher.DirectoryName!,
                ArgumentList =
                {
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    launcher.FullName,
                },
            });
            if (process is null)
            {
                message = "Windows could not start the local service launcher.";
                return false;
            }

            lock (ProcessGate)
            {
                _ownedServiceProcess = process;
            }
            message = "The local service was started by Reader.";
            return true;
        }
        catch (Exception exception) when (exception is InvalidOperationException or Win32Exception)
        {
            message = $"The local service could not be started: {exception.Message}";
            return false;
        }
    }

    public static bool TryStop(out string message)
    {
        Process? owned;
        lock (ProcessGate)
        {
            owned = _ownedServiceProcess;
            _ownedServiceProcess = null;
        }

        if (owned is not null)
        {
            try
            {
                if (!owned.HasExited)
                {
                    owned.Kill(entireProcessTree: true);
                    owned.WaitForExit(5000);
                }
                message = "The Reader-started local service was stopped.";
                return true;
            }
            catch (Exception exception) when (
                exception is InvalidOperationException or Win32Exception or NotSupportedException)
            {
                message = $"The Reader-started service could not be stopped: {exception.Message}";
                return false;
            }
            finally
            {
                owned.Dispose();
            }
        }

        if (TryRunScheduledTask("/End", out var schedulerError))
        {
            message = "The per-user local service was stopped.";
            return true;
        }

        message =
            "Reader did not start this service and the per-user service task could not be stopped. " +
            $"No unrelated Python process was terminated. {schedulerError}";
        return false;
    }

    public static FileInfo? FindLocalServiceLauncher(string startDirectory)
    {
        if (string.IsNullOrWhiteSpace(startDirectory))
        {
            return null;
        }

        var current = new DirectoryInfo(Path.GetFullPath(startDirectory));
        for (var depth = 0; depth < 12 && current is not null; depth++, current = current.Parent)
        {
            var candidate = new FileInfo(
                Path.Combine(current.FullName, "scripts", "windows", "run_service.ps1"));
            if (candidate.Exists)
            {
                return candidate;
            }
        }
        return null;
    }

    private static bool TryRunScheduledTask(string action, out string error)
    {
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.System),
                    "schtasks.exe"),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                ArgumentList = { action, "/TN", TaskName },
            });
            if (process is null)
            {
                error = "Windows could not run the service task command.";
                return false;
            }

            if (!process.WaitForExit(5000))
            {
                error = "The service task command did not finish within five seconds.";
                return false;
            }

            var standardError = process.StandardError.ReadToEnd().Trim();
            var standardOutput = process.StandardOutput.ReadToEnd().Trim();
            error = string.IsNullOrWhiteSpace(standardError) ? standardOutput : standardError;
            return process.ExitCode == 0;
        }
        catch (Exception exception) when (exception is InvalidOperationException or Win32Exception)
        {
            error = exception.Message;
            return false;
        }
    }

    private static string WindowsPowerShellPath() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.Windows),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe");
}
