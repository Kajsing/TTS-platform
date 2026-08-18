using System.Windows;

namespace TtsPlatform.Reader.App;

public enum FolderPrivacyDialogMode
{
    Setup,
    Unlock,
    Change,
    Recover,
    Remove,
}

public partial class FolderPrivacyDialog : Window
{
    private readonly FolderPrivacyDialogMode _mode;

    public FolderPrivacyDialog(FolderPrivacyDialogMode mode, string folderName)
    {
        _mode = mode;
        InitializeComponent();
        Configure(folderName);
        Loaded += (_, _) => PrimaryPasswordBox.Focus();
    }

    public string PrimarySecret => PrimaryPasswordBox.Password;

    public string NewCode => NewCodePasswordBox.Password;

    private void Configure(string folderName)
    {
        var safeName = string.IsNullOrWhiteSpace(folderName) ? "this folder" : folderName;
        switch (_mode)
        {
            case FolderPrivacyDialogMode.Setup:
                Title = "Set Privacy lock";
                HeadingText.Text = $"Protect {safeName}";
                PrimaryLabel.Text = "New code (at least 6 characters)";
                NewCodeEntryPanel.Visibility = Visibility.Collapsed;
                AcceptButton.Content = "Set lock";
                break;
            case FolderPrivacyDialogMode.Unlock:
                Title = "Unlock folder";
                HeadingText.Text = $"Unlock {safeName}";
                PrimaryLabel.Text = "Code";
                NewCodePanel.Visibility = Visibility.Collapsed;
                AcceptButton.Content = "Unlock";
                break;
            case FolderPrivacyDialogMode.Change:
                Title = "Change Privacy lock code";
                HeadingText.Text = $"Change code for {safeName}";
                PrimaryLabel.Text = "Current code";
                AcceptButton.Content = "Change code";
                break;
            case FolderPrivacyDialogMode.Recover:
                Title = "Recover Privacy lock";
                HeadingText.Text = $"Recover {safeName}";
                PrimaryLabel.Text = "Recovery key";
                PrimaryPasswordBox.MaxLength = 100;
                AcceptButton.Content = "Reset code";
                break;
            case FolderPrivacyDialogMode.Remove:
                Title = "Remove Privacy lock";
                HeadingText.Text = $"Remove lock from {safeName}";
                PrimaryLabel.Text = "Current code";
                NewCodePanel.Visibility = Visibility.Collapsed;
                AcceptButton.Content = "Remove lock";
                break;
        }
    }

    private void AcceptButton_Click(object sender, RoutedEventArgs e)
    {
        var minimum = _mode is FolderPrivacyDialogMode.Recover ? 30 : 6;
        if (PrimaryPasswordBox.Password.Length < minimum)
        {
            ValidationText.Text = _mode is FolderPrivacyDialogMode.Recover
                ? "Enter the complete recovery key."
                : "The code must contain at least 6 characters.";
            return;
        }
        if (_mode is FolderPrivacyDialogMode.Setup && !string.Equals(
            PrimaryPasswordBox.Password,
            ConfirmPasswordBox.Password,
            StringComparison.Ordinal))
        {
            ValidationText.Text = "The two code fields do not match.";
            return;
        }
        if (_mode is FolderPrivacyDialogMode.Change or FolderPrivacyDialogMode.Recover)
        {
            if (NewCodePasswordBox.Password.Length < 6)
            {
                ValidationText.Text = "The new code must contain at least 6 characters.";
                return;
            }
            if (!string.Equals(
                NewCodePasswordBox.Password,
                ConfirmPasswordBox.Password,
                StringComparison.Ordinal))
            {
                ValidationText.Text = "The two new-code fields do not match.";
                return;
            }
        }
        DialogResult = true;
    }
}
