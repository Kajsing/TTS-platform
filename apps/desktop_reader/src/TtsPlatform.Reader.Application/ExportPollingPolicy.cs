namespace TtsPlatform.Reader.Application;

public static class ExportPollingPolicy
{
    public static readonly TimeSpan ActiveInterval = TimeSpan.FromSeconds(4);
    public static readonly TimeSpan IdleInterval = TimeSpan.FromSeconds(15);
    public static readonly TimeSpan RateLimitBackoff = TimeSpan.FromSeconds(61);

    public static TimeSpan NextInterval(IEnumerable<string> statuses)
    {
        ArgumentNullException.ThrowIfNull(statuses);
        return statuses.Any(status =>
            string.Equals(status, "queued", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(status, "running", StringComparison.OrdinalIgnoreCase))
            ? ActiveInterval
            : IdleInterval;
    }
}
