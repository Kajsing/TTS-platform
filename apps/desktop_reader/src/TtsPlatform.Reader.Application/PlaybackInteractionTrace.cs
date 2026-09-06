using System.Text.Json.Serialization;

namespace TtsPlatform.Reader.Application;

// Closed vocabularies only: never pass control content, arbitrary keys, window
// titles, process identities or article text into input diagnostics.
[JsonConverter(typeof(JsonStringEnumConverter<PlaybackCommandSource>))]
public enum PlaybackCommandSource
{
    None, MainButton, CompactButton, TrayMenu, GlobalHotkey, LocalSpace,
    LocalEscape, AudioInterruption, AutomaticResume, ClipboardReading,
    DocumentLoad, ReaderClose, ServiceOperation, PrivacySessionEnded,
}

[JsonConverter(typeof(JsonStringEnumConverter<PlaybackUiEvent>))]
public enum PlaybackUiEvent
{
    Command, Activated, Deactivated, KeyboardFocus, WindowState,
    MouseDown, MouseUp, ButtonKey, AudioInterruptionChanged,
}

[JsonConverter(typeof(JsonStringEnumConverter<PlaybackUiTarget>))]
public enum PlaybackUiTarget { None, PlayPause, Stop, StartAtCursor, Editor, Library, Find, Other }

[JsonConverter(typeof(JsonStringEnumConverter<PlaybackUiInput>))]
public enum PlaybackUiInput { None, LeftMouse, OtherMouse, Space, Enter, Escape }

[JsonConverter(typeof(JsonStringEnumConverter<PlaybackUiWindow>))]
public enum PlaybackUiWindow { Reader, Compact }

[JsonConverter(typeof(JsonStringEnumConverter<PlaybackUiCommand>))]
public enum PlaybackUiCommand { None, PlayPause, Stop, Pause, Resume, StartAtCursor, ReadClipboard, CopySelectionAndRead }

[JsonConverter(typeof(JsonStringEnumConverter<PlaybackInterruptionKind>))]
public enum PlaybackInterruptionKind { None, Teams, WindowsAlarm, WindowsAlertOrAlarm, Other }

public sealed record PlaybackInteractionContext(
    PlaybackUiWindow Window,
    bool ReaderActive,
    bool WindowActive,
    PlaybackUiTarget KeyboardFocus,
    bool AudioInterruptionActive,
    bool EphemeralPlaying,
    PlaybackInterruptionKind Interruption = PlaybackInterruptionKind.None,
    PlaybackUiTarget MouseCapture = PlaybackUiTarget.None,
    bool PointerOverWindow = false,
    bool WindowVisible = true,
    bool WindowMinimized = false);

public sealed record PlaybackInteraction(
    int Version,
    long Sequence,
    PlaybackUiEvent Event,
    PlaybackInteractionContext Context,
    PlaybackUiTarget Target,
    PlaybackUiInput Input,
    PlaybackCommandSource Source,
    PlaybackUiCommand Command,
    PlaybackUiInput? RecentInput,
    PlaybackUiTarget? RecentInputTarget,
    PlaybackUiWindow? RecentInputWindow,
    long? RecentInputAgeMs,
    PlaybackUiEvent? RecentActivation,
    PlaybackUiWindow? RecentActivationWindow,
    long? RecentActivationAgeMs);

// UI-thread observer. Time comes from a monotonic clock, independent of UTC
// corrections. High-frequency pointer/focus observations are sampled; commands
// and activation changes are always recorded. The JSONL sink also bounds disk use.
public sealed class PlaybackInteractionTrace(Action<PlaybackInteraction> record, TimeProvider? clock = null)
{
    private readonly TimeProvider _clock = clock ?? TimeProvider.System;
    private long _sequence;
    private (long At, PlaybackUiInput Input, PlaybackUiTarget Target, PlaybackUiWindow Window)? _input;
    private (long At, PlaybackUiEvent Event, PlaybackUiWindow Window)? _activation;
    private long? _lastSample;

    public void Observe(
        PlaybackUiEvent kind,
        PlaybackInteractionContext context,
        PlaybackUiTarget target = PlaybackUiTarget.None,
        PlaybackUiInput input = PlaybackUiInput.None,
        PlaybackCommandSource source = PlaybackCommandSource.None,
        PlaybackUiCommand command = PlaybackUiCommand.None)
    {
        try
        {
            var now = _clock.GetTimestamp();
            long? Age(long? at) => at is long value
                ? Math.Max(0, (long)_clock.GetElapsedTime(value, now).TotalMilliseconds) : null;
            if (input != PlaybackUiInput.None) _input = (now, input, target, context.Window);
            if (kind is PlaybackUiEvent.Activated or PlaybackUiEvent.Deactivated)
                _activation = (now, kind, context.Window);
            // Do not sample playback-button mouse/key events: their exact order
            // matters when diagnosing focus, mouse capture and activation clicks.
            if (kind is PlaybackUiEvent.MouseDown or PlaybackUiEvent.MouseUp or PlaybackUiEvent.KeyboardFocus &&
                target is not (PlaybackUiTarget.PlayPause or PlaybackUiTarget.Stop or PlaybackUiTarget.StartAtCursor))
            {
                if (Age(_lastSample) is < 100) return;
                _lastSample = now;
            }
            record(new PlaybackInteraction(1, ++_sequence, kind, context, target, input, source, command,
                _input?.Input, _input?.Target, _input?.Window, Age(_input?.At),
                _activation?.Event, _activation?.Window, Age(_activation?.At)));
        }
        catch (Exception)
        {
            // Input observation must never consume an event or break playback.
        }
    }
}
