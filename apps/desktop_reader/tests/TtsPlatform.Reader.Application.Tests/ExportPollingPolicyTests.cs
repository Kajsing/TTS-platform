using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class ExportPollingPolicyTests
{
    [Theory]
    [InlineData("queued")]
    [InlineData("running")]
    [InlineData("RUNNING")]
    public void Active_jobs_use_the_rate_safe_active_interval(string status)
    {
        Assert.Equal(
            TimeSpan.FromSeconds(4),
            ExportPollingPolicy.NextInterval([status]));
    }

    [Fact]
    public void Terminal_or_empty_job_lists_use_the_idle_interval()
    {
        Assert.Equal(
            TimeSpan.FromSeconds(15),
            ExportPollingPolicy.NextInterval(["completed", "failed", "cancelled"]));
        Assert.Equal(
            TimeSpan.FromSeconds(15),
            ExportPollingPolicy.NextInterval([]));
    }
}
