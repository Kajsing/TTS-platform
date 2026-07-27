using System.Diagnostics;

namespace TtsPlatform.Reader.Windows;

public static class ScheduledServiceController
{
    public const string TaskName = "TTS Platform Local Reader";

    public static bool TryStart(out string message)
    {
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "schtasks.exe"),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                ArgumentList = { "/Run", "/TN", TaskName },
            });
            if (process is null)
            {
                message = "Windows could not start the service task.";
                return false;
            }

            process.WaitForExit(5000);
            if (!process.HasExited)
            {
                message = "The service start command is still running. Retry the connection shortly.";
                return true;
            }

            message = process.ExitCode == 0
                ? "The per-user service start was requested. Retry the connection shortly."
                : "The per-user service task is not installed. Run `tts service-install --user` from the source bundle.";
            return process.ExitCode == 0;
        }
        catch (Exception exception) when (exception is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            message = $"The service task could not be started: {exception.Message}";
            return false;
        }
    }
}
