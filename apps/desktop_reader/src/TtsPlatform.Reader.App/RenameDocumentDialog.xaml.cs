using System.Windows;

namespace TtsPlatform.Reader.App;

public partial class RenameDocumentDialog : Window
{
    public RenameDocumentDialog(string currentTitle, bool chapter = false)
    {
        InitializeComponent();
        if (chapter)
        {
            TitleLabel.Text = "Chapter title";
            TitleTextBox.MaxLength = 300;
            System.Windows.Automation.AutomationProperties.SetName(this, "Chapter title");
            System.Windows.Automation.AutomationProperties.SetName(TitleTextBox, "New chapter title");
        }
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
            ValidationText.Text = "Enter a title.";
            return;
        }

        NewTitle = title;
        DialogResult = true;
    }
}
