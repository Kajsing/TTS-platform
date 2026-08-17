namespace TtsPlatform.Reader.Windows.Tests;

public sealed class VisualLineRangePlannerTests
{
    [Fact]
    public void Forward_line_indexes_preserve_every_wrapped_visual_line()
    {
        var ranges = VisualLineRangePlanner.Build(
            105,
            220,
            offset => offset < 195 ? 3 : 4);

        Assert.Equal(
            [new VisualLineRange(105, 195), new VisualLineRange(195, 220)],
            ranges);
    }

    [Fact]
    public void Empty_or_unmapped_ranges_do_not_produce_highlights()
    {
        Assert.Empty(VisualLineRangePlanner.Build(12, 12, _ => 0));
        Assert.Empty(VisualLineRangePlanner.Build(12, 20, _ => -1));
    }
}
