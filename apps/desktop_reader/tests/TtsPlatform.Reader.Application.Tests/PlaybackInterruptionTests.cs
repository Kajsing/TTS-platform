using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class PlaybackInterruptionTests
{
    [Fact]
    public void Short_audio_does_not_activate_an_interruption()
    {
        var policy = Policy();
        var start = DateTimeOffset.UnixEpoch;

        Assert.Null(policy.Observe("Microsoft Teams", start));
        Assert.Null(policy.Observe(null, start.AddMilliseconds(499)));
        Assert.False(policy.IsActive);
    }

    [Fact]
    public void Sustained_audio_activates_after_the_debounce_period()
    {
        var policy = Policy();
        var start = DateTimeOffset.UnixEpoch;

        Assert.Null(policy.Observe("Microsoft Teams", start));
        var transition = policy.Observe("Microsoft Teams", start.AddMilliseconds(500));

        Assert.Equal(new PlaybackInterruptionTransition(true, "Microsoft Teams"), transition);
        Assert.True(policy.IsActive);
    }

    [Fact]
    public void Different_short_sources_are_not_combined_into_one_interruption()
    {
        var policy = Policy();
        var start = DateTimeOffset.UnixEpoch;

        Assert.Null(policy.Observe("Microsoft Teams", start));
        Assert.Null(policy.Observe("Windows alarm", start.AddMilliseconds(300)));
        Assert.Null(policy.Observe("Windows alarm", start.AddMilliseconds(700)));

        Assert.False(policy.IsActive);
    }

    [Fact]
    public void Interruption_clears_only_after_the_release_grace_period()
    {
        var policy = Policy();
        var start = DateTimeOffset.UnixEpoch;
        _ = policy.Observe("Windows alarm", start);
        _ = policy.Observe("Windows alarm", start.AddMilliseconds(500));

        Assert.Null(policy.Observe(null, start.AddSeconds(1)));
        Assert.Null(policy.Observe(null, start.AddSeconds(2.9)));
        var transition = policy.Observe(null, start.AddSeconds(3));

        Assert.Equal(new PlaybackInterruptionTransition(false, null), transition);
        Assert.False(policy.IsActive);
    }

    [Fact]
    public void Reset_releases_an_active_interruption_immediately()
    {
        var policy = Policy();
        var start = DateTimeOffset.UnixEpoch;
        _ = policy.Observe("Microsoft Teams", start);
        _ = policy.Observe("Microsoft Teams", start.AddMilliseconds(500));

        Assert.Equal(new PlaybackInterruptionTransition(false, null), policy.Reset());
        Assert.False(policy.IsActive);
        Assert.Null(policy.Reset());
    }

    private static PlaybackInterruptionDebouncer Policy() => new(
        TimeSpan.FromMilliseconds(500),
        TimeSpan.FromSeconds(2));
}
