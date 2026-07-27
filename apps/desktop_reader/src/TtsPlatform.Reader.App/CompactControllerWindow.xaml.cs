using System.ComponentModel;
using System.Windows;

namespace TtsPlatform.Reader.App;

public partial class CompactControllerWindow : Window
{
    public CompactControllerWindow()
    {
        InitializeComponent();
    }

    public event EventHandler? PlayPauseRequested;
    public event EventHandler? StopRequested;
    public event EventHandler? OpenReaderRequested;
    public bool AllowClose { get; set; }

    public void SetState(string state, string context, bool playing)
    {
        StateText.Text = state;
        ContextText.Text = context;
        PlayPauseButton.Content = playing ? "Pause" : "Play";
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        if (!AllowClose)
        {
            e.Cancel = true;
            Hide();
            return;
        }
        base.OnClosing(e);
    }

    private void PlayPause_Click(object sender, RoutedEventArgs e) =>
        PlayPauseRequested?.Invoke(this, EventArgs.Empty);

    private void Stop_Click(object sender, RoutedEventArgs e) =>
        StopRequested?.Invoke(this, EventArgs.Empty);

    private void OpenReader_Click(object sender, RoutedEventArgs e) =>
        OpenReaderRequested?.Invoke(this, EventArgs.Empty);
}
