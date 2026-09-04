namespace TtsPlatform.Reader.Application;

public sealed record PlaybackInterruptionTransition(bool IsActive, string? Source);

public sealed class PlaybackInterruptionDebouncer(
    TimeSpan? activationDelay = null,
    TimeSpan? releaseDelay = null)
{
    public static readonly TimeSpan DefaultActivationDelay = TimeSpan.FromMilliseconds(450);
    public static readonly TimeSpan DefaultReleaseDelay = TimeSpan.FromSeconds(2);
    private readonly TimeSpan _activationDelay = activationDelay ?? DefaultActivationDelay;
    private readonly TimeSpan _releaseDelay = releaseDelay ?? DefaultReleaseDelay;
    private DateTimeOffset? _candidateSince;
    private DateTimeOffset? _clearSince;
    private string? _candidateSource;

    public bool IsActive { get; private set; }

    public PlaybackInterruptionTransition? Observe(
        string? source,
        DateTimeOffset observedAt)
    {
        if (!string.IsNullOrWhiteSpace(source))
        {
            _clearSince = null;
            if (IsActive)
            {
                _candidateSource = source;
                return null;
            }
            if (!string.Equals(_candidateSource, source, StringComparison.Ordinal))
            {
                _candidateSince = observedAt;
            }
            _candidateSince ??= observedAt;
            _candidateSource = source;
            if (observedAt - _candidateSince < _activationDelay)
            {
                return null;
            }
            IsActive = true;
            return new PlaybackInterruptionTransition(true, _candidateSource);
        }

        _candidateSince = null;
        _candidateSource = null;
        if (!IsActive)
        {
            return null;
        }
        _clearSince ??= observedAt;
        if (observedAt - _clearSince < _releaseDelay)
        {
            return null;
        }
        IsActive = false;
        _clearSince = null;
        return new PlaybackInterruptionTransition(false, null);
    }

    public PlaybackInterruptionTransition? Reset()
    {
        var wasActive = IsActive;
        IsActive = false;
        _candidateSince = null;
        _clearSince = null;
        _candidateSource = null;
        return wasActive ? new PlaybackInterruptionTransition(false, null) : null;
    }
}
