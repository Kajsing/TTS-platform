using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private PlaybackInteractionTrace? _interactionTrace;
    private PlaybackInterruptionKind _diagnosticInterruption;

    private void InitializePlaybackDiagnostics()
    {
        _interactionTrace = new PlaybackInteractionTrace(interaction =>
            _playbackPerformance?.Record(new PlaybackPerformanceEvent(
                "playback_ui",
                RunId: _playback?.DiagnosticRunId,
                DocumentId: _editor?.Document?.Id,
                State: _playback?.State.ToString(),
                Interaction: interaction)));
        ObservePlaybackWindow(this, PlaybackUiWindow.Reader);
    }

    private void ObservePlaybackWindow(Window window, PlaybackUiWindow surface)
    {
        void Observe(PlaybackUiEvent kind, object? target = null, PlaybackUiInput input = PlaybackUiInput.None)
        {
            // An observer of this app's routed events only. No global input
            // hooks, coordinates, text, key streams or foreign window inspection.
            try
            {
                _interactionTrace?.Observe(kind, InteractionContext(window, surface), ClassifyPlaybackTarget(target), input);
            }
            catch (Exception)
            {
                // A disappearing visual must not turn diagnostics into an input error.
            }
        }
        window.Activated += (_, _) => Observe(PlaybackUiEvent.Activated);
        window.Deactivated += (_, _) => Observe(PlaybackUiEvent.Deactivated);
        window.StateChanged += (_, _) => Observe(PlaybackUiEvent.WindowState);
        window.AddHandler(Keyboard.GotKeyboardFocusEvent, new KeyboardFocusChangedEventHandler((_, e) =>
            Observe(PlaybackUiEvent.KeyboardFocus, e.NewFocus)), handledEventsToo: true);
        window.AddHandler(Mouse.PreviewMouseDownEvent, new MouseButtonEventHandler((_, e) =>
            Observe(PlaybackUiEvent.MouseDown, e.OriginalSource,
                e.ChangedButton == MouseButton.Left ? PlaybackUiInput.LeftMouse : PlaybackUiInput.OtherMouse)), true);
        window.AddHandler(Mouse.PreviewMouseUpEvent, new MouseButtonEventHandler((_, e) =>
            Observe(PlaybackUiEvent.MouseUp, e.OriginalSource,
                e.ChangedButton == MouseButton.Left ? PlaybackUiInput.LeftMouse : PlaybackUiInput.OtherMouse)), true);
        window.AddHandler(Keyboard.PreviewKeyDownEvent, new KeyEventHandler((_, e) =>
        {
            if (ClassifyPlaybackTarget(e.OriginalSource) is PlaybackUiTarget.PlayPause or PlaybackUiTarget.Stop or PlaybackUiTarget.StartAtCursor &&
                e.Key is Key.Space or Key.Return)
                Observe(PlaybackUiEvent.ButtonKey, e.OriginalSource,
                    e.Key == Key.Space ? PlaybackUiInput.Space : PlaybackUiInput.Enter);
        }), true);
    }

    private PlaybackInteractionContext InteractionContext(Window window, PlaybackUiWindow surface) => new(
        surface, IsActive, window.IsActive, ClassifyPlaybackTarget(Keyboard.FocusedElement),
        _audioInterruptionActive, _ephemeralPlaying, _diagnosticInterruption,
        ClassifyPlaybackTarget(Mouse.Captured), window.IsMouseOver, window.IsVisible,
        window.WindowState == WindowState.Minimized);

    private void TracePlaybackCommand(PlaybackUiCommand command, PlaybackCommandSource source)
    {
        try
        {
            var compact = source == PlaybackCommandSource.CompactButton && _compactController is not null;
            _interactionTrace?.Observe(PlaybackUiEvent.Command,
                InteractionContext(compact ? _compactController! : this, compact ? PlaybackUiWindow.Compact : PlaybackUiWindow.Reader),
                input: source == PlaybackCommandSource.LocalSpace ? PlaybackUiInput.Space :
                    source == PlaybackCommandSource.LocalEscape ? PlaybackUiInput.Escape : PlaybackUiInput.None,
                source: source, command: command);
        }
        catch (Exception)
        {
            // The requested command still runs if collecting UI context fails.
        }
    }

    private PlaybackUiTarget ClassifyPlaybackTarget(object? target)
    {
        if (target is null) return PlaybackUiTarget.None;
        var current = target as DependencyObject;
        for (var depth = 0; current is not null && depth < 30; depth++)
        {
            if (ReferenceEquals(current, PlayPauseButton) || ReferenceEquals(current, _compactController?.PlayPauseButton)) return PlaybackUiTarget.PlayPause;
            if (ReferenceEquals(current, StopButton) || ReferenceEquals(current, _compactController?.StopButton)) return PlaybackUiTarget.Stop;
            if (ReferenceEquals(current, PlayFromCursorButton)) return PlaybackUiTarget.StartAtCursor;
            if (ReferenceEquals(current, EditorTextBox)) return PlaybackUiTarget.Editor;
            if (ReferenceEquals(current, DocumentsGrid)) return PlaybackUiTarget.Library;
            if (ReferenceEquals(current, FindPanel)) return PlaybackUiTarget.Find;
            current = current is Visual ? VisualTreeHelper.GetParent(current) :
                current is FrameworkContentElement content ? content.Parent : LogicalTreeHelper.GetParent(current);
        }
        return PlaybackUiTarget.Other;
    }
}
