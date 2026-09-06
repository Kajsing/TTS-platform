using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Windows.Input;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    // Explicit isolated lifecycle fixture only. No real hotkey registration,
    // foreign window input, audio, service calls, clipboard or production logs.
    internal async Task VerifyPlaybackDiagnosticsAsync(string root)
    {
        if (!_smokeTest || _playbackPerformance is not null || _playback is not null)
            throw new InvalidOperationException("Playback diagnostics smoke requires an isolated empty Reader.");
        var path = Path.Combine(root, $"interaction-smoke-{Guid.NewGuid():N}.jsonl");
        _playbackPerformance = new JsonlPlaybackPerformanceSink(path);
        async Task Idle() => await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        static void Require(bool value, string message)
        {
            if (!value) throw new InvalidOperationException(message);
        }
        string ReadLog()
        {
            using var reader = new StreamReader(new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite));
            return reader.ReadToEnd();
        }
        List<PlaybackInteraction> Read() => ReadLog().Split('\n', StringSplitOptions.RemoveEmptyEntries).Select(line =>
        {
            using var json = JsonDocument.Parse(line);
            return json.RootElement.GetProperty("performance").GetProperty("interaction")
                .Deserialize<PlaybackInteraction>(new JsonSerializerOptions(JsonSerializerDefaults.Web)
                { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower })!;
        }).ToList();
        try
        {
            OnActivated(EventArgs.Empty);
            OnDeactivated(EventArgs.Empty);
            var initial = Read();
            Require(initial.Any(entry => entry.Event == PlaybackUiEvent.Deactivated), "Deactivation was not observed.");
            Require(initial.All(entry => entry.Event != PlaybackUiEvent.Command), "Focus changes invoked playback.");

            var down = new MouseButtonEventArgs(Mouse.PrimaryDevice, Environment.TickCount, MouseButton.Left)
            { RoutedEvent = Mouse.PreviewMouseDownEvent };
            var up = new MouseButtonEventArgs(Mouse.PrimaryDevice, Environment.TickCount, MouseButton.Left)
            { RoutedEvent = Mouse.PreviewMouseUpEvent };
            // Exercise real WPF routed observation, then real button automation;
            // this verifies routing, not a physical mouse/game reproduction.
            PlayPauseButton.RaiseEvent(down);
            PlayPauseButton.RaiseEvent(up);
            Require(!down.Handled && !up.Handled, "Diagnostics consumed routed mouse input.");
            PlayPauseButton.IsEnabled = true;
            ((IInvokeProvider)new ButtonAutomationPeer(PlayPauseButton).GetPattern(PatternInterface.Invoke)!).Invoke();
            await Idle();
            var clicked = Read().Last(entry => entry.Event == PlaybackUiEvent.Command);
            Require(clicked.Source == PlaybackCommandSource.MainButton && clicked.Command == PlaybackUiCommand.PlayPause &&
                clicked.RecentInput == PlaybackUiInput.LeftMouse && clicked.RecentInputTarget == PlaybackUiTarget.PlayPause,
                "Button click lost its mouse/target provenance.");

            PlayPauseButton.Focus();
            var space = new KeyEventArgs(Keyboard.PrimaryDevice, PresentationSource.FromVisual(this)!, Environment.TickCount, Key.Space)
            { RoutedEvent = Keyboard.PreviewKeyDownEvent };
            PlayPauseButton.RaiseEvent(space);
            await Idle();
            Require(Read().Any(entry => entry.Source == PlaybackCommandSource.LocalSpace), "Reader Space shortcut was not identified.");
            var commandsBeforeTyping = Read().Count(entry => entry.Event == PlaybackUiEvent.Command);
            var unrelated = new KeyEventArgs(Keyboard.PrimaryDevice, PresentationSource.FromVisual(this)!, Environment.TickCount, Key.A)
            { RoutedEvent = Keyboard.PreviewKeyDownEvent };
            PlayPauseButton.RaiseEvent(unrelated);
            await Idle();
            Require(!unrelated.Handled && Read().Count(entry => entry.Event == PlaybackUiEvent.Command) == commandsBeforeTyping,
                "Observer consumed or interpreted unrelated keyboard input.");

            Hotkeys_Pressed(this, GlobalHotkeyCommand.PlayPause);
            await HandleTrayCommandAsync(ReaderTrayCommand.Stop);
            await Idle();
            Require(Read().Any(entry => entry.Source == PlaybackCommandSource.GlobalHotkey), "Hotkey route was not identified.");
            Require(Read().Any(entry => entry.Source == PlaybackCommandSource.TrayMenu), "Tray route was not identified.");

            ShowCompactController();
            ((IInvokeProvider)new ButtonAutomationPeer(_compactController!.PlayPauseButton).GetPattern(PatternInterface.Invoke)!).Invoke();
            await Idle();
            var compact = Read().Last(entry => entry.Event == PlaybackUiEvent.Command);
            Require(compact.Source == PlaybackCommandSource.CompactButton && compact.Context.Window == PlaybackUiWindow.Compact,
                "Compact controller source was not identified.");
            _compactController.AllowClose = true;
            _compactController.Close();
            _compactController = null;

            await PauseForAudioInterruptionAsync("PRIVATE input must not enter log");
            Require(Read().Any(entry => entry.Source == PlaybackCommandSource.AudioInterruption), "Automatic pause was not identified.");
            Require(!ReadLog().Contains("PRIVATE", StringComparison.Ordinal), "Diagnostics leaked free text.");
            Require(_playback is null && _editor is null, "Observer created playback or loaded article state.");
        }
        finally
        {
            _playbackPerformance.Dispose();
            _playbackPerformance = null;
        }
    }
}
