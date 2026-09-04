using System.Windows;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class OptionsDialog : Window
{
    public OptionsDialog(DesktopSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        Settings = settings;
        InitializeComponent();
        PauseForCallsAndAlarmsCheckBox.IsChecked = settings.EffectivePauseForCallsAndAlarms;
        ClipboardMonitoringCheckBox.IsChecked = settings.ClipboardMonitoringEnabled;
        ClipboardPromptMinimumTextBox.Text = settings.ClipboardPromptMinimumCharacters.ToString();
        CopySelectionCheckBox.IsChecked = settings.CopySelectionAndReadEnabled;
        PrivacyModeCheckBox.IsChecked = settings.PrivacyMode;
        BlockedApplicationsTextBox.Text = string.Join(", ", settings.EffectiveClipboardBlockedApplications);
        MinimizeToTrayCheckBox.IsChecked = settings.MinimizeToTrayOnClose;
        CompactEnabledCheckBox.IsChecked = settings.EffectiveCompactController.Enabled;
        ReadClipboardHotkeyTextBox.Text = settings.EffectiveHotkeys.ReadClipboard;
        CopySelectionHotkeyTextBox.Text = settings.EffectiveHotkeys.CopySelectionAndRead;
        PlayPauseHotkeyTextBox.Text = settings.EffectiveHotkeys.PlayPause;
        StopHotkeyTextBox.Text = settings.EffectiveHotkeys.Stop;
    }

    public DesktopSettings Settings { get; private set; }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Settings = Settings with
            {
                PauseForCallsAndAlarms = PauseForCallsAndAlarmsCheckBox.IsChecked == true,
                ClipboardMonitoringEnabled = ClipboardMonitoringCheckBox.IsChecked == true,
                ClipboardPromptMinimumCharacters = ParseClipboardPromptMinimum(
                    ClipboardPromptMinimumTextBox.Text),
                CopySelectionAndReadEnabled = CopySelectionCheckBox.IsChecked == true,
                PrivacyMode = PrivacyModeCheckBox.IsChecked == true,
                MinimizeToTrayOnClose = MinimizeToTrayCheckBox.IsChecked == true,
                ClipboardBlockedApplications = ParseBlockedApplications(
                    BlockedApplicationsTextBox.Text),
                Hotkeys = new DesktopHotkeys(
                    ReadClipboardHotkeyTextBox.Text.Trim(),
                    CopySelectionHotkeyTextBox.Text.Trim(),
                    PlayPauseHotkeyTextBox.Text.Trim(),
                    StopHotkeyTextBox.Text.Trim()),
                CompactController = Settings.EffectiveCompactController with
                {
                    Enabled = CompactEnabledCheckBox.IsChecked == true,
                },
            };
            DialogResult = true;
        }
        catch (ReaderClientConfigurationException exception)
        {
            MessageBox.Show(
                this,
                exception.Message,
                "Invalid option",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }

    private static IReadOnlyList<string> ParseBlockedApplications(string value) =>
        value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private static int ParseClipboardPromptMinimum(string value)
    {
        if (!int.TryParse(value.Trim(), out var minimum) || minimum is < 0 or > 10_000_000)
        {
            throw new ReaderClientConfigurationException(
                "The clipboard prompt minimum must be a number from 0 to 10,000,000.");
        }
        return minimum;
    }
}
