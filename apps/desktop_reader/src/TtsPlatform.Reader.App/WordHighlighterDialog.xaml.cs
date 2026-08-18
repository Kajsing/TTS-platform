using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class WordHighlighterDialog : Window
{
    public WordHighlighterDialog(
        ReaderHighlighterConfiguration configuration,
        IReadOnlyDictionary<string, int> counts)
    {
        ArgumentNullException.ThrowIfNull(configuration);
        ArgumentNullException.ThrowIfNull(counts);
        InitializeComponent();
        Rows = new ObservableCollection<HighlighterTermRow>(
            configuration.Terms
                .OrderBy(term => term.Ordinal)
                .Select(term => new HighlighterTermRow(
                    term.Id,
                    term.Term,
                    term.Active,
                    term.Color,
                    counts.GetValueOrDefault(term.Id))));
        DataContext = this;
        StatusText.Text = configuration.Terms.Count == 0
            ? "Add a recurring name, word, or phrase to begin."
            : $"{configuration.Terms.Count:N0} global term(s). Counts use the complete open article.";
    }

    public ObservableCollection<HighlighterTermRow> Rows { get; }
    public IReadOnlyList<SaveHighlighterTerm> SavedTerms { get; private set; } = [];
    public event EventHandler<string>? JumpRequested;

    private void Add_Click(object sender, RoutedEventArgs e)
    {
        var term = NewTermTextBox.Text.Trim();
        if (term.Length is 0 or > WordHighlighterEngine.MaxTermCharacters)
        {
            StatusText.Text =
                $"Enter from 1 through {WordHighlighterEngine.MaxTermCharacters:N0} characters.";
            return;
        }
        if (Rows.Count == WordHighlighterEngine.MaxTerms)
        {
            StatusText.Text = $"The global list is limited to {WordHighlighterEngine.MaxTerms:N0} terms.";
            return;
        }
        if (Rows.Any(row => string.Equals(row.Term.Trim(), term, StringComparison.OrdinalIgnoreCase)))
        {
            StatusText.Text = "That word or phrase is already in the list.";
            return;
        }
        var row = new HighlighterTermRow(
            string.Empty,
            term,
            active: true,
            color: "#E5E9ED",
            count: 0);
        Rows.Add(row);
        TermsGrid.SelectedItem = row;
        TermsGrid.ScrollIntoView(row);
        NewTermTextBox.Clear();
        NewTermTextBox.Focus();
        StatusText.Text = "New term added. Choose Save to apply it.";
    }

    private void Remove_Click(object sender, RoutedEventArgs e)
    {
        if (TermsGrid.SelectedItem is not HighlighterTermRow selected)
        {
            StatusText.Text = "Select a row to remove it.";
            return;
        }
        Rows.Remove(selected);
        StatusText.Text = "Term removed. Choose Save to apply the change.";
    }

    private void Next_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is not HighlighterTermRow row ||
            string.IsNullOrWhiteSpace(row.Id) ||
            !row.Active ||
            row.Count == 0)
        {
            StatusText.Text = "This term has no active matches in the open article.";
            return;
        }
        JumpRequested?.Invoke(this, row.Id);
        StatusText.Text = $"Moved to the next “{row.Term}” match.";
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        var terms = Rows.Select(row => row.Term.Trim()).ToArray();
        if (terms.Any(term => term.Length is 0 or > WordHighlighterEngine.MaxTermCharacters))
        {
            StatusText.Text =
                $"Every entry must contain from 1 through {WordHighlighterEngine.MaxTermCharacters:N0} characters.";
            return;
        }
        if (terms.Distinct(StringComparer.OrdinalIgnoreCase).Count() != terms.Length)
        {
            StatusText.Text = "The list contains the same word or phrase more than once.";
            return;
        }
        SavedTerms = Rows
            .Select(row => new SaveHighlighterTerm(row.Term.Trim(), row.Active))
            .ToArray();
        DialogResult = true;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => DialogResult = false;
}

public sealed class HighlighterTermRow(
    string id,
    string term,
    bool active,
    string color,
    int count) : INotifyPropertyChanged
{
    private string _term = term;
    private bool _active = active;

    public event PropertyChangedEventHandler? PropertyChanged;
    public string Id { get; } = id;
    public string Color { get; } = color;
    public int Count { get; } = count;
    public string Term
    {
        get => _term;
        set
        {
            if (string.Equals(_term, value, StringComparison.Ordinal))
            {
                return;
            }
            _term = value;
            OnPropertyChanged();
        }
    }
    public bool Active
    {
        get => _active;
        set
        {
            if (_active == value)
            {
                return;
            }
            _active = value;
            OnPropertyChanged();
        }
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
