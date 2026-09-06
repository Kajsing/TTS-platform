using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class VoicePreviewTests
{
    [Fact]
    public async Task Rendering_and_audio_use_separate_idle_reservations_and_stop_before_release()
    {
        var fixture = new Fixture();
        await fixture.Runner.RunAsync("selected-voice", _ => { }, CancellationToken.None);
        Assert.Equal(["status", "reserve1", "render:selected-voice:ticket1", "load", "reserve2", "play", "stop", "dispose", "release:ticket2"], fixture.Calls);
    }

    [Fact]
    public async Task Active_or_unknown_service_never_renders_or_opens_audio()
    {
        foreach (var state in new[] { "busy", "unknown", "not-ready", "reserved" })
        {
            var fixture = new Fixture { StatusFault = state };
            await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Runner.RunAsync("selected", _ => { }, CancellationToken.None));
            Assert.Equal(["status"], fixture.Calls);
        }
    }

    [Theory]
    [InlineData("busy")]
    [InlineData("expired")]
    [InlineData("invalid-ttl")]
    public async Task Stale_or_busy_playback_reservation_never_plays(string fault)
    {
        var fixture = new Fixture { PlaybackFault = fault };
        await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Runner.RunAsync("selected", _ => { }, CancellationToken.None));
        Assert.DoesNotContain("play", fixture.Calls);
        Assert.Contains("dispose", fixture.Calls);
        if (fault != "busy") Assert.Equal("release:ticket2", fixture.Calls.Last());
    }

    [Fact]
    public async Task Overlong_audio_is_never_reserved_or_played()
    {
        var fixture = new Fixture { Duration = TimeSpan.FromSeconds(11) };
        await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Runner.RunAsync("selected", _ => { }, CancellationToken.None));
        Assert.DoesNotContain("reserve2", fixture.Calls);
        Assert.DoesNotContain("play", fixture.Calls);
        Assert.Equal("dispose", fixture.Calls.Last());
    }

    [Fact]
    public async Task Cancellation_stops_audio_and_releases_the_reservation_after_disposal()
    {
        var fixture = new Fixture { HoldAudio = true };
        using var cancel = new CancellationTokenSource();
        var pending = fixture.Runner.RunAsync("selected", _ => { }, cancel.Token);
        await fixture.PlayStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await Assert.ThrowsAsync<VoiceLibraryException>(() => fixture.Runner.RunAsync("other", _ => { }, CancellationToken.None));
        cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(new[] { "stop", "dispose", "release:ticket2" }, fixture.Calls.TakeLast(3));
    }

    [Fact]
    public async Task Cancelled_render_requests_release_but_never_creates_audio()
    {
        var fixture = new Fixture { HoldRender = true };
        using var cancel = new CancellationTokenSource();
        var pending = fixture.Runner.RunAsync("selected", _ => { }, cancel.Token);
        await fixture.RenderStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.DoesNotContain("load", fixture.Calls);
        Assert.Equal("release:ticket1", fixture.Calls.Last());
    }

    private sealed class Fixture : ILocalVoicePreviewClient, IVoicePreviewAudio
    {
        internal readonly List<string> Calls = [];
        internal string? StatusFault;
        internal string? PlaybackFault;
        internal bool HoldAudio;
        internal bool HoldRender;
        internal TimeSpan Duration = TimeSpan.FromSeconds(2);
        internal readonly TaskCompletionSource PlayStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource RenderStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly VoicePreviewRunner Runner;
        private readonly Clock _clock = new();
        private int _reservations;
        internal Fixture() => Runner = new(this, () => this, _clock);
        public Task<LocalServiceStatus> GetLocalStatusAsync(CancellationToken token)
        {
            Calls.Add("status"); return Task.FromResult(new LocalServiceStatus(
            StatusFault == "unknown" ? 99 : 1, "same-instance", StatusFault != "not-ready", true, "old", "Old", 2, 10, true,
            new(0, 0, 0, StatusFault == "busy" ? 1 : 0, 0), StatusFault == "reserved", new("service_process", 1, 0, 1, 4, 1024)));
        }
        public Task<ServiceMaintenanceReservation> ReserveMaintenanceAsync(string instance, CancellationToken token)
        {
            Assert.Equal("same-instance", instance);
            Calls.Add($"reserve{++_reservations}");
            if (_reservations == 2 && PlaybackFault == "busy") throw new VoiceLibraryException("Busy.");
            if (_reservations == 2 && PlaybackFault == "expired") _clock.Now += 15000;
            return Task.FromResult(new ServiceMaintenanceReservation($"ticket{_reservations}", _reservations == 2 && PlaybackFault == "invalid-ttl" ? 90 : 15));
        }
        public Task<ServiceMaintenanceRelease> ReleaseMaintenanceAsync(string ticket, CancellationToken token)
        { Calls.Add("release:" + ticket); return Task.FromResult(new ServiceMaintenanceRelease(true)); }
        public async Task<byte[]> RenderVoicePreviewAsync(string ticket, string voice, CancellationToken token)
        {
            Calls.Add($"render:{voice}:{ticket}");
            RenderStarted.TrySetResult();
            if (HoldRender) await Task.Delay(Timeout.Infinite, token);
            return [1, 2, 3];
        }
        public TimeSpan Load(ReadOnlyMemory<byte> wave) { Calls.Add("load"); return Duration; }
        public async Task PlayAsync(CancellationToken token)
        { Calls.Add("play"); PlayStarted.TrySetResult(); if (HoldAudio) await Task.Delay(Timeout.Infinite, token); }
        public Task StopAsync() { Calls.Add("stop"); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { Calls.Add("dispose"); return ValueTask.CompletedTask; }
    }

    private sealed class Clock : TimeProvider
    {
        internal long Now;
        public override long TimestampFrequency => 1000;
        public override long GetTimestamp() => Now;
    }
}
