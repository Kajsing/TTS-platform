using System.Windows;

namespace TtsPlatform.Reader.App;

public partial class RecoveryKeyDialog : Window
{
    public RecoveryKeyDialog(string recoveryKey)
    {
        InitializeComponent();
        RecoveryKeyTextBox.Text = recoveryKey;
        Loaded += (_, _) => RecoveryKeyTextBox.SelectAll();
    }

    private void CopyButton_Click(object sender, RoutedEventArgs e)
    {
        Clipboard.SetText(RecoveryKeyTextBox.Text);
    }

    private void SavedCheckBox_Changed(object sender, RoutedEventArgs e)
    {
        CloseButton.IsEnabled = SavedCheckBox.IsChecked is true;
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = true;
    }
}
