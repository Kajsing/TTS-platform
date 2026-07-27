using System.Windows;

namespace TtsPlatform.Reader.App;

public partial class RenameDocumentDialog : Window
{
    public RenameDocumentDialog(string currentTitle)
    {
        InitializeComponent();
        TitleTextBox.Text = currentTitle;
        TitleTextBox.SelectAll();
        Loaded += (_, _) => TitleTextBox.Focus();
    }

    public string? NewTitle { get; private set; }

    private void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        var title = TitleTextBox.Text.Trim();
        if (title.Length == 0)
        {
            ValidationText.Text = "Enter a document title.";
            return;
        }

        NewTitle = title;
        DialogResult = true;
    }
}
