using System.Text.Json;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class PlaybackInteractionTraceTests
{
    private static readonly PlaybackInteractionContext Context = new(
        PlaybackUiWindow.Reader, true, true, PlaybackUiTarget.PlayPause, false, false);

    [Fact]
    public void Command_correlates_mouse_and_deactivation_using_monotonic_time()
    {
        var entries = new List<PlaybackInteraction>();
        var clock = new Clock();
        var trace = new PlaybackInteractionTrace(entries.Add, clock);
        trace.Observe(PlaybackUiEvent.MouseDown, Context, PlaybackUiTarget.PlayPause, PlaybackUiInput.LeftMouse);
        clock.Advance(25);
        trace.Observe(PlaybackUiEvent.Deactivated, Context with { ReaderActive = false, WindowActive = false });
        clock.Advance(10);
        trace.Observe(PlaybackUiEvent.Command, Context, source: PlaybackCommandSource.MainButton, command: PlaybackUiCommand.PlayPause);

        Assert.Equal(new long[] { 1, 2, 3 }, entries.Select(entry => entry.Sequence));
        Assert.Equal(35, entries[^1].RecentInputAgeMs);
        Assert.Equal(10, entries[^1].RecentActivationAgeMs);
        Assert.Equal(PlaybackUiInput.LeftMouse, entries[^1].RecentInput);
        Assert.Equal(PlaybackUiTarget.PlayPause, entries[^1].RecentInputTarget);
        Assert.Equal(PlaybackUiEvent.Deactivated, entries[^1].RecentActivation);
        Assert.Equal(PlaybackCommandSource.MainButton, entries[^1].Source);
    }

    [Fact]
    public void Global_hotkey_without_local_input_is_not_reported_as_a_mouse_click()
    {
        PlaybackInteraction? result = null;
        new PlaybackInteractionTrace(entry => result = entry).Observe(PlaybackUiEvent.Command, Context,
            source: PlaybackCommandSource.GlobalHotkey, command: PlaybackUiCommand.Stop);
        Assert.NotNull(result);
        Assert.Null(result.RecentInput);
        Assert.Null(result.RecentInputAgeMs);
        Assert.Equal(PlaybackUiInput.None, result.Input);
    }

    [Fact]
    public void Noisy_editor_input_is_sampled_without_losing_commands_or_button_edges()
    {
        var entries = new List<PlaybackInteraction>();
        var clock = new Clock();
        var trace = new PlaybackInteractionTrace(entries.Add, clock);
        for (var i = 0; i < 100; i++)
            trace.Observe(PlaybackUiEvent.MouseDown, Context, PlaybackUiTarget.Editor, PlaybackUiInput.LeftMouse);
        Assert.Single(entries);
        trace.Observe(PlaybackUiEvent.MouseDown, Context, PlaybackUiTarget.Stop, PlaybackUiInput.LeftMouse);
        trace.Observe(PlaybackUiEvent.MouseUp, Context, PlaybackUiTarget.Stop, PlaybackUiInput.LeftMouse);
        trace.Observe(PlaybackUiEvent.Command, Context, source: PlaybackCommandSource.MainButton, command: PlaybackUiCommand.Stop);
        Assert.Equal(4, entries.Count);
        clock.Advance(100);
        trace.Observe(PlaybackUiEvent.KeyboardFocus, Context, PlaybackUiTarget.Editor);
        Assert.Equal(5, entries.Count);
    }

    [Fact]
    public void Compact_input_remains_identifiable_after_reader_regains_focus()
    {
        var entries = new List<PlaybackInteraction>();
        var trace = new PlaybackInteractionTrace(entries.Add);
        trace.Observe(PlaybackUiEvent.MouseUp, Context with { Window = PlaybackUiWindow.Compact }, PlaybackUiTarget.Stop, PlaybackUiInput.LeftMouse);
        trace.Observe(PlaybackUiEvent.Activated, Context);
        trace.Observe(PlaybackUiEvent.Command, Context, source: PlaybackCommandSource.CompactButton, command: PlaybackUiCommand.Stop);
        Assert.Equal(PlaybackUiWindow.Compact, entries[^1].RecentInputWindow);
        Assert.Equal(PlaybackUiWindow.Reader, entries[^1].RecentActivationWindow);
    }

    [Fact]
    public void Broken_diagnostics_do_not_throw_into_input_handlers()
    {
        var trace = new PlaybackInteractionTrace(_ => throw new IOException("Unavailable sink"));
        trace.Observe(PlaybackUiEvent.Command, Context, source: PlaybackCommandSource.MainButton, command: PlaybackUiCommand.PlayPause);
    }

    [Fact]
    public void Interaction_contract_has_no_free_text_or_key_code_fields()
    {
        Assert.DoesNotContain(typeof(PlaybackInteraction).GetProperties(), property => property.PropertyType == typeof(string));
        Assert.DoesNotContain(typeof(PlaybackInteractionContext).GetProperties(), property => property.PropertyType == typeof(string));
        PlaybackInteraction? result = null;
        new PlaybackInteractionTrace(entry => result = entry).Observe(PlaybackUiEvent.Command, Context,
            source: PlaybackCommandSource.LocalSpace, command: PlaybackUiCommand.PlayPause);
        var json = JsonSerializer.Serialize(result);
        Assert.Contains("LocalSpace", json);
        Assert.DoesNotContain("KeyCode", json);
    }

    private sealed class Clock : TimeProvider
    {
        private long _milliseconds;
        public override long TimestampFrequency => 1000;
        public override long GetTimestamp() => _milliseconds;
        public void Advance(long milliseconds) => _milliseconds += milliseconds;
    }
}
