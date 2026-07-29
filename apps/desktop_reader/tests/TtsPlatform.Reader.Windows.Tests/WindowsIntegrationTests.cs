using NAudio.Wave;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class WindowsIntegrationTests
{
    [Fact]
    public void Service_controller_finds_only_the_bundled_launcher_above_the_app_directory()
    {
        var root = Path.Combine(Path.GetTempPath(), $"tts-reader-service-{Guid.NewGuid():N}");
        var launcher = Path.Combine(root, "scripts", "windows", "run_service.ps1");
        var appDirectory = Path.Combine(root, "apps", "desktop_reader", "publish");
        Directory.CreateDirectory(Path.GetDirectoryName(launcher)!);
        Directory.CreateDirectory(appDirectory);
        File.WriteAllText(launcher, "# test launcher");
        try
        {
            var found = ScheduledServiceController.FindLocalServiceLauncher(appDirectory);

            Assert.NotNull(found);
            Assert.Equal(Path.GetFullPath(launcher), found.FullName);
            Assert.Null(ScheduledServiceController.FindLocalServiceLauncher(
                Path.Combine(Path.GetTempPath(), $"tts-reader-unrelated-{Guid.NewGuid():N}")));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Theory]
    [InlineData("Ctrl+Alt+Insert")]
    [InlineData("Ctrl+Alt+Space")]
    [InlineData("Ctrl+Alt+Shift+F24")]
    public void Hotkey_parser_accepts_supported_configurable_gestures(string gesture)
    {
        Assert.True(GlobalHotkeyManager.TryParse(gesture, out var modifiers, out var key));
        Assert.NotEqual(0U, modifiers);
        Assert.NotEqual(0U, key);
    }

    [Theory]
    [InlineData("")]
    [InlineData("P")]
    [InlineData("Ctrl+NoSuchKey")]
    [InlineData("Ctrl+Banana+P")]
    public void Hotkey_parser_rejects_invalid_gestures_without_throwing(string gesture)
    {
        Assert.False(GlobalHotkeyManager.TryParse(gesture, out _, out _));
    }

    [Fact]
    public async Task Copy_selection_sends_copy_once_reads_new_sequence_and_restores_safe_text()
    {
        var clipboard = new FakeClipboard("previous", "selected");
        var sender = new FakeCopySender(() => clipboard.Advance());
        var helper = new CopySelectionHelper(
            clipboard,
            sender,
            new FakeForeground("notepad.exe"),
            new FakeDesktop(true),
            timeout: TimeSpan.FromMilliseconds(100),
            pollInterval: TimeSpan.FromMilliseconds(5));

        var result = await helper.CaptureAsync([]);

        Assert.True(result.Succeeded);
        Assert.Equal("selected", result.Text);
        Assert.Equal(1, sender.SendCount);
        Assert.Equal("previous", clipboard.RestoredText);
    }

    [Fact]
    public async Task Copy_selection_block_list_prevents_input_and_timeout_never_retries()
    {
        var blockedSender = new FakeCopySender(() => { });
        var blocked = new CopySelectionHelper(
            new FakeClipboard("old", "new"),
            blockedSender,
            new FakeForeground("password-manager.exe"),
            new FakeDesktop(true),
            timeout: TimeSpan.FromMilliseconds(30),
            pollInterval: TimeSpan.FromMilliseconds(5));
        var blockedResult = await blocked.CaptureAsync(["Password-Manager"]);

        var timeoutSender = new FakeCopySender(() => { });
        var timeout = new CopySelectionHelper(
            new FakeClipboard("old", "new"),
            timeoutSender,
            new FakeForeground("notepad.exe"),
            new FakeDesktop(true),
            timeout: TimeSpan.FromMilliseconds(30),
            pollInterval: TimeSpan.FromMilliseconds(5));
        var timeoutResult = await timeout.CaptureAsync([]);

        Assert.False(blockedResult.Succeeded);
        Assert.Equal(0, blockedSender.SendCount);
        Assert.False(timeoutResult.Succeeded);
        Assert.Equal(1, timeoutSender.SendCount);
        Assert.Contains("one second", timeoutResult.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Copy_selection_refuses_secure_desktop_and_never_restores_unsafe_formats()
    {
        var secureSender = new FakeCopySender(() => { });
        var secure = new CopySelectionHelper(
            new FakeClipboard("old", "new"),
            secureSender,
            new FakeForeground("notepad.exe"),
            new FakeDesktop(false));

        var secureResult = await secure.CaptureAsync([]);

        var unsafeClipboard = new FakeClipboard("old", "new", restorable: false);
        var unsafeSender = new FakeCopySender(unsafeClipboard.Advance);
        var unsafeCapture = new CopySelectionHelper(
            unsafeClipboard,
            unsafeSender,
            new FakeForeground("notepad.exe"),
            new FakeDesktop(true),
            timeout: TimeSpan.FromMilliseconds(100),
            pollInterval: TimeSpan.FromMilliseconds(5));

        var unsafeResult = await unsafeCapture.CaptureAsync([]);

        Assert.False(secureResult.Succeeded);
        Assert.Contains("secure desktop", secureResult.Message, StringComparison.Ordinal);
        Assert.Equal(0, secureSender.SendCount);
        Assert.True(unsafeResult.Succeeded);
        Assert.Null(unsafeClipboard.RestoredText);
    }

    [Fact]
    public void Wave_decoder_accepts_mono_pcm16_and_rejects_stereo()
    {
        var mono = CreateWave(new WaveFormat(22_050, 16, 1));
        var decoded = WavePcmDecoder.Decode(mono);

        Assert.Equal(22_050, decoded.Format.SampleRateHz);
        Assert.Equal(1, decoded.Format.Channels);
        Assert.Equal(200, decoded.Bytes.Length);
        Assert.Throws<InvalidDataException>(() =>
            WavePcmDecoder.Decode(CreateWave(new WaveFormat(22_050, 16, 2))));
    }

    private static byte[] CreateWave(WaveFormat format)
    {
        using var stream = new MemoryStream();
        using (var writer = new WaveFileWriter(stream, format))
        {
            writer.Write(new byte[200], 0, 200);
        }
        return stream.ToArray();
    }

    private sealed class FakeClipboard(
        string oldText,
        string newText,
        bool restorable = true) : IClipboardAdapter
    {
        public uint SequenceNumber { get; private set; } = 1;
        public string? RestoredText { get; private set; }

        public void Advance() => SequenceNumber++;
        public ClipboardTextResult ReadText() => new(true, newText, "ready");
        public ClipboardSnapshot? CaptureRestorableSnapshot() =>
            restorable ? new(oldText) : null;
        public void Restore(ClipboardSnapshot snapshot) => RestoredText = snapshot.Text;
    }

    private sealed class FakeCopySender(Action onSend) : ICopyKeySender
    {
        public int SendCount { get; private set; }
        public bool SendCopy()
        {
            SendCount++;
            onSend();
            return true;
        }
    }

    private sealed class FakeForeground(string executable) : IForegroundApplicationReader
    {
        public string? GetExecutableName() => executable;
    }

    private sealed class FakeDesktop(bool available) : IDesktopSecurityGuard
    {
        public bool IsDefaultInteractiveDesktop() => available;
    }
}
