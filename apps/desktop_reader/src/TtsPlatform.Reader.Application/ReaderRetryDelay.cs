using System.Text.Json;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public static class ReaderRetryDelay
{
    public static TimeSpan ForError(ReaderApiException exception, TimeSpan fallback)
    {
        var seconds = exception.Details.TryGetValue("retry_after_seconds", out var retry) ? retry switch
        {
            int value => value,
            long value => (double)value,
            double value => value,
            JsonElement value when value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number) => number,
            _ => fallback.TotalSeconds,
        } : fallback.TotalSeconds;
        if (!double.IsFinite(seconds) || seconds <= 0) seconds = fallback.TotalSeconds;
        return TimeSpan.FromSeconds(Math.Clamp(seconds, 1, 3600));
    }
}
