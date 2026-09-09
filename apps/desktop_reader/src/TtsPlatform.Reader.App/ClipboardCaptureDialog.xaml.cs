using System.Windows;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.App;

public partial class ClipboardCaptureDialog : Window
{
    public ClipboardCaptureDialog(
        string text,
        string? sourceExecutable,
        bool privacyMode,
        string? appendTarget = null)
    {
        InitializeComponent();
        SourceText.Text = sourceExecutable is null
            ? $"{text.Length:N0} characters copied from an unknown application."
            : $"{text.Length:N0} characters copied from {sourceExecutable}.";
        PreviewText.Text = privacyMode
            ? "Preview hidden by privacy mode. Choose an action or Ignore."
            : text.Length <= 500 ? text : $"{text[..500]}…";
        AlwaysIgnoreButton.IsEnabled = !string.IsNullOrWhiteSpace(sourceExecutable);
        if (appendTarget is not null) AppendTargetText.Text = "Add target: " + appendTarget;
    }

    public ClipboardCaptureAction SelectedAction { get; private set; } = ClipboardCaptureAction.Ignore;
    public bool StartNewChapter => NewChapterCheckBox.IsChecked == true;

    private void ReadNow_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardCaptureAction.ReadNow);

    private void Append_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardCaptureAction.AppendToOpenDocument);

    private void Create_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardCaptureAction.CreateNewDocument);

    private void Inbox_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardCaptureAction.SaveToInbox);

    private void Ignore_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardCaptureAction.Ignore);

    private void Snooze_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardCaptureAction.SnoozeFiveMinutes);

    private void AlwaysIgnore_Click(object sender, RoutedEventArgs e) =>
        Complete(ClipboardCaptureAction.AlwaysIgnoreApplication);

    private void Complete(ClipboardCaptureAction action)
    {
        SelectedAction = action;
        DialogResult = true;
    }
}
