using System.Collections.Concurrent;

namespace TtsPlatform.Reader.Client;

public sealed class ReaderRequestCooldown(TimeProvider? time = null)
{
    private static readonly ConcurrentDictionary<string, ReaderRequestCooldown> Shared = new(StringComparer.Ordinal);
    private readonly TimeProvider _time = time ?? TimeProvider.System;
    private long _untilTicks;
    public static ReaderRequestCooldown ForService(string serviceUrl) =>
        Shared.GetOrAdd(new Uri(serviceUrl).GetLeftPart(UriPartial.Authority), _ => new());
    public void Observe(HttpResponseMessage response)
    {
        if ((int)response.StatusCode != 429) return;
        var seconds = response.Headers.RetryAfter?.Delta?.TotalSeconds ??
            (response.Headers.RetryAfter?.Date - _time.GetUtcNow())?.TotalSeconds ?? 61;
        var deadline = _time.GetUtcNow().AddSeconds(Math.Clamp(seconds, 1, 3600)).Ticks;
        long previous;
        do
        {
            previous = Interlocked.Read(ref _untilTicks);
            if (previous >= deadline) return;
        } while (Interlocked.CompareExchange(ref _untilTicks, deadline, previous) != previous);
    }
    public int RemainingSeconds => Math.Max(0, (int)Math.Ceiling(
        (Interlocked.Read(ref _untilTicks) - _time.GetUtcNow().Ticks) / (double)TimeSpan.TicksPerSecond));
    public void Check()
    {
        var seconds = RemainingSeconds;
        if (seconds > 0) throw new ReaderApiException("rate_limited", "Waiting for the service request budget to recover.", 429,
            details: new Dictionary<string, object?> { ["retry_after_seconds"] = seconds });
    }
}
