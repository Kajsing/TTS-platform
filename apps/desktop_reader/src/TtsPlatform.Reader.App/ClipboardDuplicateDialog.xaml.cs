using System.Windows;

namespace TtsPlatform.Reader.App;

public enum ClipboardDuplicateChoice
{
    Cancel,
    OpenExisting,
    CreateAnyway,
}

public partial class ClipboardDuplicateDialog : Window
{
    public ClipboardDuplicateDialog() => InitializeComponent();

    public ClipboardDuplicateChoice SelectedChoice { get; private set; } =
        ClipboardDuplicateChoice.Cancel;

    private void OpenExisting_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardDuplicateChoice.OpenExisting);

    private void CreateAnyway_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardDuplicateChoice.CreateAnyway);

    private void Cancel_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardDuplicateChoice.Cancel);

    private void Complete(ClipboardDuplicateChoice choice)
    {
        SelectedChoice = choice;
        DialogResult = true;
    }
}
