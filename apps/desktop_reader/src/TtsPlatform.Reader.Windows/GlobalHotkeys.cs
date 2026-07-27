using System.Runtime.InteropServices;
using Forms = System.Windows.Forms;

namespace TtsPlatform.Reader.Windows;

public enum GlobalHotkeyCommand
{
    ReadClipboard,
    CopySelectionAndRead,
    PlayPause,
    Stop,
}

public sealed record GlobalHotkeyBinding(GlobalHotkeyCommand Command, string Gesture);
public sealed record GlobalHotkeyRegistration(
    GlobalHotkeyCommand Command,
    string Gesture,
    bool Registered,
    string? Message = null);

public sealed class GlobalHotkeyManager : IDisposable
{
    public const int HotkeyMessage = 0x0312;
    private const uint ModifierAlt = 0x0001;
    private const uint ModifierControl = 0x0002;
    private const uint ModifierShift = 0x0004;
    private const uint ModifierWindows = 0x0008;
    private const uint ModifierNoRepeat = 0x4000;
    private readonly Dictionary<int, GlobalHotkeyCommand> _commands = [];
    private IntPtr _windowHandle;

    public event EventHandler<GlobalHotkeyCommand>? Pressed;

    public IReadOnlyList<GlobalHotkeyRegistration> Register(
        IntPtr windowHandle,
        IReadOnlyList<GlobalHotkeyBinding> bindings)
    {
        UnregisterAll();
        _windowHandle = windowHandle;
        var results = new List<GlobalHotkeyRegistration>();
        var identifier = 0x5200;
        foreach (var binding in bindings)
        {
            if (!TryParse(binding.Gesture, out var modifiers, out var key))
            {
                results.Add(new GlobalHotkeyRegistration(
                    binding.Command,
                    binding.Gesture,
                    false,
                    "The configured hotkey gesture is invalid."));
                continue;
            }
            var registered = RegisterHotKey(
                windowHandle,
                identifier,
                modifiers | ModifierNoRepeat,
                key);
            results.Add(new GlobalHotkeyRegistration(
                binding.Command,
                binding.Gesture,
                registered,
                registered ? null : "Windows reported that this hotkey is unavailable."));
            if (registered)
            {
                _commands[identifier] = binding.Command;
                identifier++;
            }
        }
        return results;
    }

    public bool ProcessWindowMessage(int message, IntPtr wordParameter)
    {
        if (message != HotkeyMessage || !_commands.TryGetValue(wordParameter.ToInt32(), out var command))
        {
            return false;
        }
        Pressed?.Invoke(this, command);
        return true;
    }

    public void Dispose() => UnregisterAll();

    public static bool TryParse(string gesture, out uint modifiers, out uint key)
    {
        modifiers = 0;
        key = 0;
        if (string.IsNullOrWhiteSpace(gesture))
        {
            return false;
        }
        var parts = gesture.Split('+', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length < 2)
        {
            return false;
        }
        foreach (var modifier in parts[..^1])
        {
            var parsedModifier = modifier.ToUpperInvariant() switch
            {
                "CTRL" or "CONTROL" => ModifierControl,
                "ALT" => ModifierAlt,
                "SHIFT" => ModifierShift,
                "WIN" or "WINDOWS" => ModifierWindows,
                _ => 0U,
            };
            if (parsedModifier == 0)
            {
                return false;
            }
            modifiers |= parsedModifier;
        }
        if (!Enum.TryParse<Forms.Keys>(parts[^1], ignoreCase: true, out var parsedKey))
        {
            return false;
        }
        var keyCode = parsedKey & Forms.Keys.KeyCode;
        if (keyCode == Forms.Keys.None || modifiers == 0)
        {
            return false;
        }
        key = (uint)keyCode;
        return true;
    }

    private void UnregisterAll()
    {
        foreach (var identifier in _commands.Keys)
        {
            _ = UnregisterHotKey(_windowHandle, identifier);
        }
        _commands.Clear();
        _windowHandle = IntPtr.Zero;
    }

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool RegisterHotKey(IntPtr windowHandle, int identifier, uint modifiers, uint key);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UnregisterHotKey(IntPtr windowHandle, int identifier);
}
