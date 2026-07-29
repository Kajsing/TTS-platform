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
        var text = SourceText ?? string.Empty;
        var start = Math.Clamp(HighlightStart, 0, text.Length);
        var length = Math.Clamp(HighlightLength, 0, text.Length - start);
        if (HighlightStart < 0 || length == 0)
        {
            Inlines.Add(new Run(text));
            AutomationProperties.SetHelpText(this, string.Empty);
            return;
        }

        if (start > 0)
        {
            Inlines.Add(new Run(text[..start]));
        }
        Inlines.Add(new Run(text.Substring(start, length))
        {
            Background = new SolidColorBrush(Color.FromRgb(255, 224, 130)),
            FontWeight = FontWeights.Bold,
            TextDecorations = System.Windows.TextDecorations.Underline,
        });
        if (start + length < text.Length)
        {
            Inlines.Add(new Run(text[(start + length)..]));
        }
        AutomationProperties.SetHelpText(this, "Currently spoken source text");
    }
}

public sealed class ReaderBlockDisplay(ReaderBlock block) : INotifyPropertyChanged
{
    private int _highlightStart = -1;
    private int _highlightLength;
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
