using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public sealed class SourceHighlightTextBlock : TextBlock
{
    private static readonly Brush PlaybackBrush = CreateFrozenBrush(Color.FromRgb(255, 224, 130));
    private static readonly Brush FindBrush = CreateFrozenBrush(Color.FromRgb(190, 225, 226));
    private Run? _highlightedRun;
    private Run? _findRun;

    public static readonly DependencyProperty SourceTextProperty = DependencyProperty.Register(
        nameof(SourceText),
        typeof(string),
        typeof(SourceHighlightTextBlock),
        new FrameworkPropertyMetadata(string.Empty, OnDisplayPropertyChanged));

    public static readonly DependencyProperty HighlightStartProperty = DependencyProperty.Register(
        nameof(HighlightStart),
        typeof(int),
        typeof(SourceHighlightTextBlock),
        new FrameworkPropertyMetadata(-1, OnDisplayPropertyChanged));

    public static readonly DependencyProperty HighlightLengthProperty = DependencyProperty.Register(
        nameof(HighlightLength),
        typeof(int),
        typeof(SourceHighlightTextBlock),
        new FrameworkPropertyMetadata(0, OnDisplayPropertyChanged));

    public static readonly DependencyProperty FindStartProperty = DependencyProperty.Register(
        nameof(FindStart),
        typeof(int),
        typeof(SourceHighlightTextBlock),
        new FrameworkPropertyMetadata(-1, OnDisplayPropertyChanged));

    public static readonly DependencyProperty FindLengthProperty = DependencyProperty.Register(
        nameof(FindLength),
        typeof(int),
        typeof(SourceHighlightTextBlock),
        new FrameworkPropertyMetadata(0, OnDisplayPropertyChanged));

    public string SourceText
    {
        get => (string)GetValue(SourceTextProperty);
        set => SetValue(SourceTextProperty, value);
    }

    public int HighlightStart
    {
        get => (int)GetValue(HighlightStartProperty);
        set => SetValue(HighlightStartProperty, value);
    }

    public int HighlightLength
    {
        get => (int)GetValue(HighlightLengthProperty);
        set => SetValue(HighlightLengthProperty, value);
    }

    public int FindStart
    {
        get => (int)GetValue(FindStartProperty);
        set => SetValue(FindStartProperty, value);
    }

    public int FindLength
    {
        get => (int)GetValue(FindLengthProperty);
        set => SetValue(FindLengthProperty, value);
    }

    public bool BringHighlightedTextIntoView()
    {
        return BringRunIntoView(_highlightedRun);
    }

    public bool BringFindTextIntoView()
    {
        return BringRunIntoView(_findRun);
    }

    private bool BringRunIntoView(Run? run)
    {
        if (run is null)
        {
            return false;
        }

        var characterRect = run.ContentStart.GetCharacterRect(
            LogicalDirection.Forward);
        if (characterRect.IsEmpty)
        {
            return false;
        }

        var lineHeight = double.IsNaN(LineHeight) || LineHeight <= 0
            ? Math.Max(characterRect.Height, FontSize * 1.35)
            : LineHeight;
        var contextRect = new Rect(
            0,
            Math.Max(0, characterRect.Top - (lineHeight * 2)),
            Math.Max(1, ActualWidth),
            Math.Max(lineHeight * 5, characterRect.Height));
        BringIntoView(contextRect);
        return true;
    }

    private static void OnDisplayPropertyChanged(
        DependencyObject dependencyObject,
        DependencyPropertyChangedEventArgs eventArgs)
    {
        _ = eventArgs;
        ((SourceHighlightTextBlock)dependencyObject).RebuildInlines();
    }

    private void RebuildInlines()
    {
        Inlines.Clear();
        _highlightedRun = null;
        _findRun = null;
        var text = SourceText ?? string.Empty;
        var playbackStart = Math.Clamp(HighlightStart, 0, text.Length);
        var playbackLength = Math.Clamp(HighlightLength, 0, text.Length - playbackStart);
        var playbackEnd = playbackStart + playbackLength;
        var findStart = Math.Clamp(FindStart, 0, text.Length);
        var findLength = Math.Clamp(FindLength, 0, text.Length - findStart);
        var findEnd = findStart + findLength;
        var hasPlayback = HighlightStart >= 0 && playbackLength > 0;
        var hasFind = FindStart >= 0 && findLength > 0;
        if (!hasPlayback && !hasFind)
        {
            Inlines.Add(new Run(text));
            AutomationProperties.SetHelpText(this, string.Empty);
            return;
        }

        var boundaries = new SortedSet<int> { 0, text.Length };
        if (hasPlayback)
        {
            boundaries.Add(playbackStart);
            boundaries.Add(playbackEnd);
        }
        if (hasFind)
        {
            boundaries.Add(findStart);
            boundaries.Add(findEnd);
        }

        var ordered = boundaries.ToArray();
        for (var index = 0; index + 1 < ordered.Length; index++)
        {
            var start = ordered[index];
            var end = ordered[index + 1];
            if (end <= start)
            {
                continue;
            }
            var run = new Run(text.Substring(start, end - start));
            if (hasPlayback && start < playbackEnd && end > playbackStart)
            {
                run.Background = PlaybackBrush;
                _highlightedRun ??= run;
            }
            else if (hasFind && start < findEnd && end > findStart)
            {
                run.Background = FindBrush;
                _findRun ??= run;
            }
            Inlines.Add(run);
        }
        var help = hasPlayback && hasFind
            ? "Currently spoken source text and current Find result"
            : hasPlayback
                ? "Currently spoken source text"
                : "Current Find result";
        AutomationProperties.SetHelpText(this, help);
    }

    private static Brush CreateFrozenBrush(Color color)
    {
        var brush = new SolidColorBrush(color);
        brush.Freeze();
        return brush;
    }
}

public sealed class ReaderBlockDisplay(ReaderBlock block) : INotifyPropertyChanged
{
    private int _highlightStart = -1;
    private int _highlightLength;
    private int _findStart = -1;
    private int _findLength;
    private string _text = block.Text;

    public event PropertyChangedEventHandler? PropertyChanged;

    public ReaderBlock Block { get; private set; } = block;
    public string Id => Block.Id;
    public string? SectionId => Block.SectionId;
    public int Ordinal => Block.Ordinal;
    public string Text
    {
        get => _text;
        set
        {
            if (string.Equals(_text, value, StringComparison.Ordinal))
            {
                return;
            }
            _text = value;
            OnPropertyChanged();
        }
    }
    public double DisplayFontSize => Block.Kind is "title" ? 24 : Block.Kind is "heading" ? 21 : 18;
    public FontWeight DisplayFontWeight =>
        Block.Kind is "title" or "heading" ? FontWeights.SemiBold : FontWeights.Normal;
    public FontStyle DisplayFontStyle =>
        Block.Kind is "quote" ? FontStyles.Italic : FontStyles.Normal;
    public FontFamily DisplayFontFamily =>
        Block.Kind is "code" ? new FontFamily("Consolas") : new FontFamily("Segoe UI");
    public Thickness DisplayMargin => Block.Kind switch
    {
        "title" => new Thickness(8, 16, 8, 8),
        "heading" => new Thickness(8, 14, 8, 5),
        "list_item" => new Thickness(28, 4, 8, 4),
        "quote" => new Thickness(24, 6, 16, 6),
        "code" => new Thickness(16, 8, 8, 8),
        _ => new Thickness(8, 5, 8, 5),
    };

    public int HighlightStart
    {
        get => _highlightStart;
        set
        {
            if (_highlightStart == value)
            {
                return;
            }
            _highlightStart = value;
            OnPropertyChanged();
        }
    }

    public int HighlightLength
    {
        get => _highlightLength;
        set
        {
            if (_highlightLength == value)
            {
                return;
            }
            _highlightLength = value;
            OnPropertyChanged();
        }
    }

    public int FindStart
    {
        get => _findStart;
        set
        {
            if (_findStart == value)
            {
                return;
            }
            _findStart = value;
            OnPropertyChanged();
        }
    }

    public int FindLength
    {
        get => _findLength;
        set
        {
            if (_findLength == value)
            {
                return;
            }
            _findLength = value;
            OnPropertyChanged();
        }
    }

    public void ApplySavedBlock(ReaderBlock savedBlock)
    {
        ArgumentNullException.ThrowIfNull(savedBlock);
        if (!string.Equals(savedBlock.Id, Block.Id, StringComparison.Ordinal))
        {
            throw new ArgumentException("Saved block must match the displayed block.", nameof(savedBlock));
        }
        Block = savedBlock;
        Text = savedBlock.Text;
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
