using System.Windows;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MoveArticlesDialog : Window
{
    public MoveArticlesDialog(IReadOnlyList<ReaderFolder> folders, int articleCount)
    {
        InitializeComponent();
        SummaryText.Text = $"Move {articleCount:N0} article(s)";
        var destinations = new List<FolderDestination>
        {
            new(null, "All articles (no folder)"),
        };
        destinations.AddRange(folders
            .Where(folder => !folder.PrivacyLocked || folder.PrivacyUnlocked)
            .Select(folder => new FolderDestination(folder.Id, folder.Name)));
        DestinationComboBox.ItemsSource = destinations;
        DestinationComboBox.SelectedIndex = 0;
    }

    public string? TargetFolderId { get; private set; }

    private void MoveButton_Click(object sender, RoutedEventArgs e)
    {
        if (DestinationComboBox.SelectedItem is not FolderDestination destination)
        {
            return;
        }
        TargetFolderId = destination.Id;
        DialogResult = true;
    }

    private sealed record FolderDestination(string? Id, string Name);
}
