using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using Forms = System.Windows.Forms;

namespace TtsPlatform.Reader.Windows;

public sealed record ClipboardTextResult(bool Succeeded, string? Text, string Message);
public enum ClipboardSnapshotValueKind
{
    Text,
    MemoryStream,
    ByteArray,
}

public sealed record ClipboardSnapshotItem(
    string Format,
    ClipboardSnapshotValueKind Kind,
    string? Text = null,
    byte[]? Bytes = null);

public sealed record ClipboardSnapshot(IReadOnlyList<ClipboardSnapshotItem> Items)
{
    public ClipboardSnapshot(string text)
        : this([
            new ClipboardSnapshotItem(
                Forms.DataFormats.UnicodeText,
                ClipboardSnapshotValueKind.Text,
                Text: text),
        ])
    {
    }

    public string? Text => Items.FirstOrDefault(item =>
        item.Kind == ClipboardSnapshotValueKind.Text)?.Text;
}

public interface IClipboardAdapter
{
    uint SequenceNumber { get; }
    ClipboardTextResult ReadText();
    ClipboardSnapshot? CaptureRestorableSnapshot();
    void Restore(ClipboardSnapshot snapshot);
}

public interface ICopyKeySender
{
    bool SendCopy();
}

public interface IForegroundApplicationReader
{
    string? GetExecutableName();
}

public interface IDesktopSecurityGuard
{
    bool IsDefaultInteractiveDesktop();
}

public sealed record CopySelectionResult(
    bool Succeeded,
    string Message,
    string? Text = null,
    string? SourceExecutable = null,
    uint? CapturedSequence = null);

public sealed class CopySelectionHelper
{
    public static readonly TimeSpan MaximumTimeout = TimeSpan.FromSeconds(1);
    private readonly IClipboardAdapter _clipboard;
    private readonly ICopyKeySender _copyKeySender;
    private readonly IForegroundApplicationReader _foregroundApplication;
    private readonly IDesktopSecurityGuard _desktopSecurity;
    private readonly TimeSpan _timeout;
    private readonly TimeSpan _pollInterval;

    public CopySelectionHelper(
        IClipboardAdapter clipboard,
        ICopyKeySender copyKeySender,
        IForegroundApplicationReader foregroundApplication,
        IDesktopSecurityGuard desktopSecurity,
        TimeSpan? timeout = null,
        TimeSpan? pollInterval = null)
    {
        _clipboard = clipboard;
        _copyKeySender = copyKeySender;
        _foregroundApplication = foregroundApplication;
        _desktopSecurity = desktopSecurity;
        _timeout = timeout ?? MaximumTimeout;
        _pollInterval = pollInterval ?? TimeSpan.FromMilliseconds(25);
        if (_timeout <= TimeSpan.Zero || _timeout > MaximumTimeout)
        {
            throw new ArgumentOutOfRangeException(nameof(timeout), "Selection capture must time out within one second.");
        }
        if (_pollInterval <= TimeSpan.Zero || _pollInterval > _timeout)
        {
            throw new ArgumentOutOfRangeException(nameof(pollInterval));
        }
    }

    public async Task<CopySelectionResult> CaptureAsync(
        IReadOnlyCollection<string> blockedApplications,
        CancellationToken cancellationToken = default)
    {
        var sourceExecutable = _foregroundApplication.GetExecutableName();
        if (IsBlocked(sourceExecutable, blockedApplications))
        {
            return new CopySelectionResult(
                false,
                "Selection capture is disabled for this application.",
                SourceExecutable: sourceExecutable);
        }
        if (!_desktopSecurity.IsDefaultInteractiveDesktop())
        {
            return new CopySelectionResult(
                false,
                "Selection capture is unavailable on the secure desktop.",
                SourceExecutable: sourceExecutable);
        }

        var originalSequence = _clipboard.SequenceNumber;
        var restorable = _clipboard.CaptureRestorableSnapshot();
        if (!_copyKeySender.SendCopy())
        {
            return new CopySelectionResult(
                false,
                "Windows did not accept the one-time Copy command.",
                SourceExecutable: sourceExecutable);
        }

        var stopwatch = Stopwatch.StartNew();
        while (stopwatch.Elapsed < _timeout)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var sequence = _clipboard.SequenceNumber;
            if (sequence != originalSequence)
            {
                var result = _clipboard.ReadText();
                if (restorable is not null)
                {
                    _clipboard.Restore(restorable);
                }
                return result.Succeeded
                    ? new CopySelectionResult(
                        true,
                        "Selection copied for immediate reading.",
                        result.Text,
                        sourceExecutable,
                        sequence)
                    : new CopySelectionResult(
                        false,
                        "The copied selection did not contain readable text.",
                        SourceExecutable: sourceExecutable,
                        CapturedSequence: sequence);
            }
            // Windows Forms clipboard access must resume on the calling STA/UI thread.
            await Task.Delay(_pollInterval, cancellationToken);
        }

        return new CopySelectionResult(
            false,
            "No selectable text was copied within one second.",
            SourceExecutable: sourceExecutable);
    }

    private static bool IsBlocked(
        string? sourceExecutable,
        IReadOnlyCollection<string> blockedApplications)
    {
        if (string.IsNullOrWhiteSpace(sourceExecutable))
        {
            return false;
        }
        var sourceBase = Path.GetFileNameWithoutExtension(sourceExecutable);
        return blockedApplications.Any(item =>
            string.Equals(item, sourceExecutable, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(
                Path.GetFileNameWithoutExtension(item),
                sourceBase,
                StringComparison.OrdinalIgnoreCase));
    }
}

public sealed class WindowsClipboardAdapter : IClipboardAdapter
{
    private const int MaximumClipboardCharacters = 10_000_000;
    private const int MaximumSnapshotBytes = 16 * 1024 * 1024;
    private const int MaximumSnapshotFormats = 32;

    public uint SequenceNumber => GetClipboardSequenceNumber();

    public ClipboardTextResult ReadText()
    {
        try
        {
            if (!Forms.Clipboard.ContainsText(Forms.TextDataFormat.UnicodeText))
            {
                return new ClipboardTextResult(false, null, "The clipboard does not contain text.");
            }
            var text = Forms.Clipboard.GetText(Forms.TextDataFormat.UnicodeText);
            if (string.IsNullOrWhiteSpace(text))
            {
                return new ClipboardTextResult(false, null, "The clipboard text is empty.");
            }
            if (text.Length > MaximumClipboardCharacters)
            {
                return new ClipboardTextResult(false, null, "The clipboard text exceeds the Reader limit.");
            }
            return new ClipboardTextResult(true, text, "Clipboard text is ready.");
        }
        catch (Exception exception) when (
            exception is ExternalException or ThreadStateException)
        {
            return new ClipboardTextResult(false, null, "The clipboard is temporarily unavailable.");
        }
    }

    public ClipboardSnapshot? CaptureRestorableSnapshot()
    {
        try
        {
            var data = Forms.Clipboard.GetDataObject();
            if (data is null)
            {
                return null;
            }
            var formats = data.GetFormats(autoConvert: false);
            if (formats.Length is 0 or > MaximumSnapshotFormats)
            {
                return null;
            }

            var items = new List<ClipboardSnapshotItem>(formats.Length);
            long totalBytes = 0;
            foreach (var format in formats)
            {
                var value = data.GetData(format, autoConvert: false);
                switch (value)
                {
                    case string text when text.Length <= MaximumClipboardCharacters:
                        totalBytes += (long)text.Length * sizeof(char);
                        items.Add(new ClipboardSnapshotItem(
                            format,
                            ClipboardSnapshotValueKind.Text,
                            Text: text));
                        break;
                    case MemoryStream stream when stream.Length <= MaximumSnapshotBytes:
                        var streamBytes = stream.ToArray();
                        totalBytes += streamBytes.Length;
                        items.Add(new ClipboardSnapshotItem(
                            format,
                            ClipboardSnapshotValueKind.MemoryStream,
                            Bytes: streamBytes));
                        break;
                    case byte[] bytes when bytes.Length <= MaximumSnapshotBytes:
                        var copy = bytes.ToArray();
                        totalBytes += copy.Length;
                        items.Add(new ClipboardSnapshotItem(
                            format,
                            ClipboardSnapshotValueKind.ByteArray,
                            Bytes: copy));
                        break;
                    default:
                        return null;
                }
                if (totalBytes > MaximumSnapshotBytes)
                {
                    return null;
                }
            }
            return items.Count == 0 ? null : new ClipboardSnapshot(items);
        }
        catch (Exception exception) when (
            exception is ExternalException or
                ThreadStateException or
                IOException or
                ObjectDisposedException)
        {
            return null;
        }
    }

    public void Restore(ClipboardSnapshot snapshot)
    {
        try
        {
            var data = new Forms.DataObject();
            foreach (var item in snapshot.Items)
            {
                object value = item.Kind switch
                {
                    ClipboardSnapshotValueKind.Text => item.Text
                        ?? throw new InvalidDataException("Clipboard text snapshot is incomplete."),
                    ClipboardSnapshotValueKind.MemoryStream => new MemoryStream(
                        item.Bytes
                            ?? throw new InvalidDataException("Clipboard stream snapshot is incomplete."),
                        writable: false),
                    ClipboardSnapshotValueKind.ByteArray => item.Bytes?.ToArray()
                        ?? throw new InvalidDataException("Clipboard byte snapshot is incomplete."),
                    _ => throw new InvalidDataException("Clipboard snapshot kind is unsupported."),
                };
                data.SetData(item.Format, autoConvert: false, value);
            }
            Forms.Clipboard.SetDataObject(data, copy: true);
        }
        catch (Exception exception) when (
            exception is ExternalException or ThreadStateException or InvalidDataException)
        {
            // Restoration is deliberately best effort.
        }
    }

    [DllImport("user32.dll")]
    private static extern uint GetClipboardSequenceNumber();
}

public sealed class WindowsCopyKeySender : ICopyKeySender
{
    private const uint InputKeyboard = 1;
    private const uint KeyUp = 0x0002;
    private const ushort VirtualKeyControl = 0x11;
    private const ushort VirtualKeyC = 0x43;

    public bool SendCopy()
    {
        var inputs = new[]
        {
            KeyboardInput(VirtualKeyControl, 0),
            KeyboardInput(VirtualKeyC, 0),
            KeyboardInput(VirtualKeyC, KeyUp),
            KeyboardInput(VirtualKeyControl, KeyUp),
        };
        return SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<Input>()) == inputs.Length;
    }

    private static Input KeyboardInput(ushort key, uint flags) => new()
    {
        Type = InputKeyboard,
        Union = new InputUnion
        {
            Keyboard = new KeyboardInputData { VirtualKey = key, Flags = flags },
        },
    };

    [StructLayout(LayoutKind.Sequential)]
    private struct Input
    {
        public uint Type;
        public InputUnion Union;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct InputUnion
    {
        [FieldOffset(0)] public KeyboardInputData Keyboard;
        [FieldOffset(0)] public MouseInputData Mouse;
        [FieldOffset(0)] public HardwareInputData Hardware;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KeyboardInputData
    {
        public ushort VirtualKey;
        public ushort ScanCode;
        public uint Flags;
        public uint Time;
        public nuint ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MouseInputData
    {
        public int X;
        public int Y;
        public uint MouseData;
        public uint Flags;
        public uint Time;
        public nuint ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct HardwareInputData
    {
        public uint Message;
        public ushort ParameterLow;
        public ushort ParameterHigh;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint inputCount, Input[] inputs, int inputSize);
}

public sealed class ForegroundApplicationReader : IForegroundApplicationReader
{
    public string? GetExecutableName()
    {
        var window = GetForegroundWindow();
        if (window == IntPtr.Zero)
        {
            return null;
        }
        _ = GetWindowThreadProcessId(window, out var processId);
        try
        {
            return $"{Process.GetProcessById((int)processId).ProcessName}.exe";
        }
        catch (Exception exception) when (
            exception is ArgumentException or InvalidOperationException or Win32Exception)
        {
            return null;
        }
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
}

public sealed class DefaultDesktopSecurityGuard : IDesktopSecurityGuard
{
    private const uint DesktopReadObjects = 0x0001;
    private const int UserObjectName = 2;

    public bool IsDefaultInteractiveDesktop()
    {
        var desktop = OpenInputDesktop(0, false, DesktopReadObjects);
        if (desktop == IntPtr.Zero)
        {
            return false;
        }
        try
        {
            var buffer = new StringBuilder(256);
            return GetUserObjectInformation(
                desktop,
                UserObjectName,
                buffer,
                buffer.Capacity * sizeof(char),
                out _) && string.Equals(buffer.ToString(), "Default", StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            _ = CloseDesktop(desktop);
        }
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint desiredAccess);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetUserObjectInformation(
        IntPtr handle,
        int index,
        StringBuilder information,
        int length,
        out int needed);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseDesktop(IntPtr desktop);
}

public sealed record ClipboardChangedEventArgs(uint SequenceNumber, string? SourceExecutable);

public sealed class ClipboardListener(IForegroundApplicationReader foregroundApplication) : IDisposable
{
    public const int ClipboardUpdateMessage = 0x031D;
    private IntPtr _windowHandle;
    private uint _lastSequence;
    private uint _suppressedSequence;

    public event EventHandler<ClipboardChangedEventArgs>? ClipboardChanged;
    public bool IsRegistered { get; private set; }
    public string? RegistrationError { get; private set; }

    public bool Register(IntPtr windowHandle)
    {
        if (IsRegistered)
        {
            return true;
        }
        if (windowHandle == IntPtr.Zero || !AddClipboardFormatListener(windowHandle))
        {
            RegistrationError = "Clipboard prompt monitoring could not register with Windows.";
            return false;
        }
        _windowHandle = windowHandle;
        _lastSequence = GetClipboardSequenceNumber();
        IsRegistered = true;
        RegistrationError = null;
        return true;
    }

    public bool ProcessWindowMessage(int message)
    {
        if (!IsRegistered || message != ClipboardUpdateMessage)
        {
            return false;
        }
        var sequence = GetClipboardSequenceNumber();
        if (sequence == 0 || sequence == _lastSequence)
        {
            return true;
        }
        _lastSequence = sequence;
        if (sequence == _suppressedSequence)
        {
            _suppressedSequence = 0;
            return true;
        }
        ClipboardChanged?.Invoke(
            this,
            new ClipboardChangedEventArgs(sequence, foregroundApplication.GetExecutableName()));
        return true;
    }

    public void SuppressSequence(uint sequence) => _suppressedSequence = sequence;

    public void Dispose()
    {
        Unregister();
    }

    public void Unregister()
    {
        if (IsRegistered)
        {
            _ = RemoveClipboardFormatListener(_windowHandle);
        }
        IsRegistered = false;
        _windowHandle = IntPtr.Zero;
        _suppressedSequence = 0;
    }

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AddClipboardFormatListener(IntPtr windowHandle);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool RemoveClipboardFormatListener(IntPtr windowHandle);

    [DllImport("user32.dll")]
    private static extern uint GetClipboardSequenceNumber();
}
