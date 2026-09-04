using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class AudioInterruptionTests
{
    [Theory]
    [InlineData("ms-teams", null, null, false, false)]
    [InlineData("Teams.exe", null, null, false, true)]
    [InlineData("msedgewebview2", "Microsoft Teams", null, false, false)]
    public void Teams_sessions_are_recognized(
        string processName,
        string? displayName,
        string? sessionIdentifier,
        bool systemSounds,
        bool capture)
    {
        Assert.Equal(
            "Microsoft Teams",
            WindowsAudioInterruptionMonitor.ClassifySource(
                processName,
                displayName,
                sessionIdentifier,
                systemSounds,
                capture));
    }

    [Theory]
    [InlineData("Time.exe", null, null, false)]
    [InlineData("ApplicationFrameHost", null, "Microsoft.WindowsAlarms_8wekyb3d8bbwe", false)]
    [InlineData("audiodg", null, null, true)]
    public void Windows_alarm_and_alert_sessions_are_recognized(
        string processName,
        string? displayName,
        string? sessionIdentifier,
        bool systemSounds)
    {
        Assert.NotNull(WindowsAudioInterruptionMonitor.ClassifySource(
            processName,
            displayName,
            sessionIdentifier,
            systemSounds,
            isCapture: false));
    }

    [Fact]
    public void Unrelated_and_capture_alert_sessions_are_ignored()
    {
        Assert.Null(WindowsAudioInterruptionMonitor.ClassifySource(
            "chrome",
            "YouTube",
            null,
            false,
            false));
        Assert.Null(WindowsAudioInterruptionMonitor.ClassifySource(
            "audiodg",
            null,
            null,
            true,
            true));
    }

    [Fact]
    public async Task Monitor_can_be_enabled_and_disabled_without_audio_hardware_assumptions()
    {
        using var monitor = new WindowsAudioInterruptionMonitor();

        monitor.Enabled = true;
        await Task.Delay(300);
        monitor.Enabled = false;

        Assert.False(monitor.Enabled);
    }
}
