using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using System.IO;
using Microsoft.Win32;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.App;

public sealed class CaptureOutboxWindow : Window
{
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(1) };
    public CaptureOutboxWindow(CaptureOutbox outbox)
    {
        Title = "Capture queue — saved on this computer";
        Width = 760; Height = 360; MinWidth = 600; MinHeight = 300;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var panel = new DockPanel { Margin = new Thickness(16) };
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 10) };
        DockPanel.SetDock(status, Dock.Top); panel.Children.Add(status);
        var progress = new ProgressBar { Height = 5, Margin = new Thickness(0, 0, 0, 10), Minimum = 0, Maximum = 1 };
        DockPanel.SetDock(progress, Dock.Top); panel.Children.Add(progress);
        var buttons = new WrapPanel { Margin = new Thickness(0, 10, 0, 0) };
        DockPanel.SetDock(buttons, Dock.Bottom); panel.Children.Add(buttons);
        var list = new ListBox(); panel.Children.Add(list);
        Content = panel;
        void Refresh()
        {
            var id = (list.SelectedItem as ListBoxItem)?.Tag as string;
            var wait = Math.Max(0, (int)Math.Ceiling((outbox.RetryAt - DateTimeOffset.UtcNow).TotalSeconds));
            status.Text = outbox.Status + (wait > 0 ? $" · retry in {wait}s" : "") + "\nOnly accepted captures are stored. Keep Reader open for delivery. Other-workspace captures wait for their original connection.";
            progress.IsIndeterminate = outbox.Sending;
            list.Items.Clear();
            foreach (var item in outbox.Items)
            {
                var row = new ListBoxItem { Tag = item.Id, Content = $"{item.AcceptedAt.LocalDateTime:g} · {item.Request.Action} · {item.Request.Text.Length:N0} characters · {(item.Attempted ? "delivery attempted" : "queued")}" };
                list.Items.Add(row);
                if (item.Id == id) list.SelectedItem = row;
            }
        }
        void Add(string label, Action action)
        {
            var button = new Button { Content = label, Margin = new Thickness(3), Padding = new Thickness(10, 5, 10, 5) };
            button.Click += (_, _) => { try { action(); Refresh(); } catch (Exception error) { MessageBox.Show(this, error.Message, "Capture retained"); } };
            buttons.Children.Add(button);
        }
        Add("Retry", outbox.Retry);
        Add("Allow duplicate", () =>
        {
            if ((list.SelectedItem as ListBoxItem)?.Tag is string id && MessageBox.Show(this,
            "Create another article containing the same text?", "Allow duplicate", MessageBoxButton.YesNo) == MessageBoxResult.Yes) outbox.AllowDuplicate(id);
        });
        Add("Discard selected…", () =>
        {
            if ((list.SelectedItem as ListBoxItem)?.Tag is string id && MessageBox.Show(this,
            "Discard this local pending copy? If delivery was attempted, the service may already have saved it. This does not undo a server write.",
            "Discard pending capture", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes) outbox.Discard(id);
        });
        Add("Recover text…", () =>
        {
            if ((list.SelectedItem as ListBoxItem)?.Tag is string id && outbox.Items.FirstOrDefault(item => item.Id == id) is { } item)
                ShowRecovery(this, item.Request.Text, "This capture remains in the protected queue. Saving a text file creates an unencrypted copy.");
        });
        Add("Close", Close);
        _timer.Tick += (_, _) => Refresh();
        Loaded += (_, _) => { Refresh(); _timer.Start(); };
        Closed += (_, _) => _timer.Stop();
    }

    public static void ShowRecovery(Window owner, string text, string reason)
    {
        var window = new Window
        {
            Title = "Keep this text — capture recovery",
            Owner = owner,
            Width = 680,
            Height = 460,
            WindowStartupLocation = WindowStartupLocation.CenterOwner
        };
        var panel = new DockPanel { Margin = new Thickness(16) };
        var message = new TextBlock { Text = reason + "\nKeep this window open until you have recovered the text. Select and copy below, or save a plain-text file.", TextWrapping = TextWrapping.Wrap };
        DockPanel.SetDock(message, Dock.Top); panel.Children.Add(message);
        var save = new Button { Content = "Save plain-text copy…", Margin = new Thickness(0, 8, 0, 0) };
        DockPanel.SetDock(save, Dock.Bottom); panel.Children.Add(save);
        panel.Children.Add(new TextBox
        {
            Text = text,
            IsReadOnly = true,
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        });
        save.Click += (_, _) =>
        {
            var dialog = new SaveFileDialog { Filter = "Text files (*.txt)|*.txt", FileName = "Reader capture.txt" };
            if (dialog.ShowDialog(window) == true)
            {
                try { File.WriteAllText(dialog.FileName, text); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException)
                { MessageBox.Show(window, error.Message, "Text was not saved"); }
            }
        };
        window.Content = panel;
        window.ShowDialog();
    }
}
