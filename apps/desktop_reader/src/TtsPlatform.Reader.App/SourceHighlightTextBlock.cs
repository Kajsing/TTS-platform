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

    public event PropertyChangedEventHandler? PropertyChanged;

    public ReaderBlock Block { get; } = block;
    public string Id => Block.Id;
    public string? SectionId => Block.SectionId;
    public int Ordinal => Block.Ordinal;
    public string Text => Block.Text;

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

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
