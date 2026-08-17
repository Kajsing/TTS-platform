using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public sealed class PlaybackHighlightAdorner : Adorner, IDisposable
{
    private static readonly Brush HighlightFill = CreateHighlightFill();
    private static readonly Pen HighlightBorderPen = CreateHighlightBorderPen();
    private static readonly Pen UnderlinePen = CreateUnderlinePen();
    private static readonly Brush FindFill = CreateFindFill();
    private static readonly Pen FindBorderPen = CreateFindBorderPen();

    private readonly TextBox _textBox;
    private readonly ScrollChangedEventHandler _scrollChangedHandler;
    private int _highlightStart = -1;
    private int _highlightLength;
    private int _findStart = -1;
    private int _findLength;
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
    public int FindStart => _findStart;
    public int FindLength => _findLength;

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

    public void ShowFind(int start, int length)
    {
        var textLength = _textBox.Text?.Length ?? 0;
        _findStart = Math.Clamp(start, 0, textLength);
        _findLength = Math.Clamp(length, 0, textLength - _findStart);
        InvalidateVisual();
    }

    public void ClearFind()
    {
        _findStart = -1;
        _findLength = 0;
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
        if (text.Length == 0 ||
            ((_highlightStart < 0 || _highlightLength <= 0) &&
                (_findStart < 0 || _findLength <= 0)))
        {
            return;
        }

        drawingContext.PushClip(new RectangleGeometry(
            new Rect(0, 0, ActualWidth, ActualHeight)));
        try
        {
            DrawHighlight(
                drawingContext,
                text,
                _findStart,
                _findLength,
                FindFill,
                FindBorderPen,
                underlinePen: null);
            DrawHighlight(
                drawingContext,
                text,
                _highlightStart,
                _highlightLength,
                HighlightFill,
                HighlightBorderPen,
                UnderlinePen);
        }
        finally
        {
            drawingContext.Pop();
        }
    }

    private void DrawHighlight(
        DrawingContext drawingContext,
        string text,
        int highlightStart,
        int highlightLength,
        Brush fill,
        Pen borderPen,
        Pen? underlinePen)
    {
        if (highlightStart < 0 || highlightLength <= 0)
        {
            return;
        }
        var start = Math.Clamp(highlightStart, 0, text.Length);
        var end = Math.Clamp(start + highlightLength, start, text.Length);
        if (end <= start)
        {
            return;
        }
        var visualLineRanges = VisualLineRangePlanner.Build(
            start,
            end,
            _textBox.GetLineIndexFromCharacterIndex);
        foreach (var range in visualLineRanges)
        {
            DrawRangeHighlight(
                drawingContext,
                text,
                range.Start,
                range.End,
                fill,
                borderPen,
                underlinePen);
        }
    }

    private void DrawRangeHighlight(
        DrawingContext drawingContext,
        string text,
        int segmentStart,
        int segmentEnd,
        Brush fill,
        Pen borderPen,
        Pen? underlinePen)
    {
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
        if (startRect.IsEmpty ||
            !TryGetTrailingCharacterEdge(text, segmentEnd - 1, out var endRect))
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
            fill,
            borderPen,
            highlightRect,
            radiusX: 2,
            radiusY: 2);
        if (underlinePen is not null)
        {
            var underlineY = Math.Max(top, bottom - 1.25);
            drawingContext.DrawLine(
                underlinePen,
                new Point(left, underlineY),
                new Point(right, underlineY));
        }
    }

    private void TextBox_LayoutChanged(object sender, SizeChangedEventArgs e) =>
        InvalidateVisual();

    private void TextBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        _highlightStart = -1;
        _highlightLength = 0;
        _findStart = -1;
        _findLength = 0;
        InvalidateVisual();
    }

    private bool TryGetTrailingCharacterEdge(string text, int characterIndex, out Rect edge)
    {
        edge = _textBox.GetRectFromCharacterIndex(characterIndex, trailingEdge: true);
        if (!edge.IsEmpty)
        {
            return true;
        }

        var leadingEdge = _textBox.GetRectFromCharacterIndex(
            characterIndex,
            trailingEdge: false);
        if (leadingEdge.IsEmpty)
        {
            return false;
        }

        var pixelsPerDip = VisualTreeHelper.GetDpi(_textBox).PixelsPerDip;
        var measuredCharacter = new FormattedText(
            text[characterIndex].ToString(),
            CultureInfo.CurrentUICulture,
            _textBox.FlowDirection,
            new Typeface(
                _textBox.FontFamily,
                _textBox.FontStyle,
                _textBox.FontWeight,
                _textBox.FontStretch),
            _textBox.FontSize,
            _textBox.Foreground,
            pixelsPerDip);
        edge = new Rect(
            leadingEdge.X + measuredCharacter.WidthIncludingTrailingWhitespace,
            leadingEdge.Y,
            0,
            leadingEdge.Height);
        return true;
    }

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

    private static Brush CreateFindFill()
    {
        var brush = new SolidColorBrush(Color.FromArgb(54, 35, 119, 122));
        brush.Freeze();
        return brush;
    }

    private static Pen CreateFindBorderPen()
    {
        var brush = new SolidColorBrush(Color.FromRgb(35, 119, 122));
        brush.Freeze();
        var pen = new Pen(brush, 1.1);
        pen.Freeze();
        return pen;
    }
}
