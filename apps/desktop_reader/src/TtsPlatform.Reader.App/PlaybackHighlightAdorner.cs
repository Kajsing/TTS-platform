using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace TtsPlatform.Reader.App;

public sealed class PlaybackHighlightAdorner : Adorner, IDisposable
{
    private static readonly Brush HighlightFill = CreateHighlightFill();
    private static readonly Pen HighlightBorderPen = CreateHighlightBorderPen();
    private static readonly Pen UnderlinePen = CreateUnderlinePen();

    private readonly TextBox _textBox;
    private readonly ScrollChangedEventHandler _scrollChangedHandler;
    private int _highlightStart = -1;
    private int _highlightLength;
    private bool _disposed;

    public PlaybackHighlightAdorner(TextBox textBox)
        : base(textBox)
    {
        _textBox = textBox;
        IsHitTestVisible = false;
        ClipToBounds = true;
        _scrollChangedHandler = (_, _) => InvalidateVisual();
        _textBox.SizeChanged += TextBox_LayoutChanged;
        _textBox.TextChanged += TextBox_TextChanged;
        _textBox.AddHandler(ScrollViewer.ScrollChangedEvent, _scrollChangedHandler);
    }

    public int HighlightStart => _highlightStart;
    public int HighlightLength => _highlightLength;

    public void Show(int start, int length)
    {
        var textLength = _textBox.Text?.Length ?? 0;
        _highlightStart = Math.Clamp(start, 0, textLength);
        _highlightLength = Math.Clamp(length, 0, textLength - _highlightStart);
        InvalidateVisual();
    }

    public void Clear()
    {
        _highlightStart = -1;
        _highlightLength = 0;
        InvalidateVisual();
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _textBox.SizeChanged -= TextBox_LayoutChanged;
        _textBox.TextChanged -= TextBox_TextChanged;
        _textBox.RemoveHandler(ScrollViewer.ScrollChangedEvent, _scrollChangedHandler);
    }

    protected override void OnRender(DrawingContext drawingContext)
    {
        base.OnRender(drawingContext);
        var text = _textBox.Text ?? string.Empty;
        if (_highlightStart < 0 || _highlightLength <= 0 || text.Length == 0)
        {
            return;
        }

        var start = Math.Clamp(_highlightStart, 0, text.Length);
        var end = Math.Clamp(start + _highlightLength, start, text.Length);
        if (end <= start)
        {
            return;
        }

        var firstLine = _textBox.GetLineIndexFromCharacterIndex(start);
        var lastLine = _textBox.GetLineIndexFromCharacterIndex(end - 1);
        if (firstLine < 0 || lastLine < firstLine)
        {
            return;
        }

        drawingContext.PushClip(new RectangleGeometry(
            new Rect(0, 0, ActualWidth, ActualHeight)));
        try
        {
            for (var line = firstLine; line <= lastLine; line++)
            {
                DrawLineHighlight(drawingContext, text, line, start, end);
            }
        }
        finally
        {
            drawingContext.Pop();
        }
    }

    private void DrawLineHighlight(
        DrawingContext drawingContext,
        string text,
        int line,
        int highlightStart,
        int highlightEnd)
    {
        var lineStart = _textBox.GetCharacterIndexFromLineIndex(line);
        if (lineStart < 0)
        {
            return;
        }
        var lineEnd = Math.Min(text.Length, lineStart + _textBox.GetLineLength(line));
        var segmentStart = Math.Max(highlightStart, lineStart);
        var segmentEnd = Math.Min(highlightEnd, lineEnd);
        while (segmentStart < segmentEnd && text[segmentStart] is '\r' or '\n')
        {
            segmentStart++;
        }
        while (segmentEnd > segmentStart && text[segmentEnd - 1] is '\r' or '\n')
        {
            segmentEnd--;
        }
        if (segmentEnd <= segmentStart)
        {
            return;
        }

        var startRect = _textBox.GetRectFromCharacterIndex(segmentStart, trailingEdge: false);
        var endRect = _textBox.GetRectFromCharacterIndex(segmentEnd - 1, trailingEdge: true);
        if (startRect.IsEmpty || endRect.IsEmpty)
        {
            return;
        }

        var left = Math.Min(startRect.X, endRect.X);
        var right = Math.Max(startRect.X, endRect.X);
        if (right - left < 1)
        {
            right = left + Math.Max(1, _textBox.FontSize * 0.45);
        }
        var top = Math.Min(startRect.Top, endRect.Top);
        var bottom = Math.Max(startRect.Bottom, endRect.Bottom);
        if (bottom - top < 1)
        {
            return;
        }

        var highlightRect = new Rect(left, top, right - left, bottom - top);
        drawingContext.DrawRoundedRectangle(
            HighlightFill,
            HighlightBorderPen,
            highlightRect,
            radiusX: 2,
            radiusY: 2);
        var underlineY = Math.Max(top, bottom - 1.25);
        drawingContext.DrawLine(
            UnderlinePen,
            new Point(left, underlineY),
            new Point(right, underlineY));
    }

    private void TextBox_LayoutChanged(object sender, SizeChangedEventArgs e) =>
        InvalidateVisual();

    private void TextBox_TextChanged(object sender, TextChangedEventArgs e) =>
        Clear();

    private static Brush CreateHighlightFill()
    {
        var brush = new SolidColorBrush(Color.FromArgb(28, 255, 224, 130));
        brush.Freeze();
        return brush;
    }

    private static Pen CreateHighlightBorderPen()
    {
        var brush = new SolidColorBrush(Color.FromRgb(213, 152, 0));
        brush.Freeze();
        var pen = new Pen(brush, 0.9);
        pen.Freeze();
        return pen;
    }

    private static Pen CreateUnderlinePen()
    {
        var brush = new SolidColorBrush(Color.FromRgb(177, 113, 0));
        brush.Freeze();
        var pen = new Pen(brush, 1.25);
        pen.Freeze();
        return pen;
    }
}
