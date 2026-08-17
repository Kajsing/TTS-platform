namespace TtsPlatform.Reader.Windows;

public sealed record VisualLineRange(int Start, int End);

public static class VisualLineRangePlanner
{
    public static IReadOnlyList<VisualLineRange> Build(
        int start,
        int end,
        Func<int, int> lineIndexAt)
    {
        ArgumentNullException.ThrowIfNull(lineIndexAt);
        if (start < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(start));
        }
        if (end <= start)
        {
            return [];
        }

        var currentLine = lineIndexAt(start);
        if (currentLine < 0)
        {
            return [];
        }

        var ranges = new List<VisualLineRange>();
        var segmentStart = start;
        for (var offset = start + 1; offset < end; offset++)
        {
            var line = lineIndexAt(offset);
            if (line == currentLine)
            {
                continue;
            }

            ranges.Add(new VisualLineRange(segmentStart, offset));
            segmentStart = offset;
            currentLine = line;
        }
        ranges.Add(new VisualLineRange(segmentStart, end));
        return ranges;
    }
}
