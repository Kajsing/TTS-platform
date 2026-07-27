using System.Drawing;
using Forms = System.Windows.Forms;

namespace TtsPlatform.Reader.Windows;

public enum ReaderTrayCommand
{
    OpenReader,
    OpenCompactController,
    PlayPause,
    Stop,
    ReadClipboard,
    ToggleClipboardMonitoring,
    ServiceStatus,
    Exit,
}

public sealed class ReaderTrayIcon : IDisposable
{
    private readonly Forms.NotifyIcon _notifyIcon;
    private readonly Forms.ToolStripMenuItem _monitoringItem;

    public ReaderTrayIcon()
    {
        _monitoringItem = new Forms.ToolStripMenuItem("Clipboard Prompt Mode");
        var menu = new Forms.ContextMenuStrip();
        Add(menu, "Open Reader", ReaderTrayCommand.OpenReader);
        Add(menu, "Compact Controller", ReaderTrayCommand.OpenCompactController);
        menu.Items.Add(new Forms.ToolStripSeparator());
        Add(menu, "Play/Pause", ReaderTrayCommand.PlayPause);
        Add(menu, "Stop", ReaderTrayCommand.Stop);
        Add(menu, "Read Clipboard", ReaderTrayCommand.ReadClipboard);
        _monitoringItem.Click += (_, _) => Command?.Invoke(
            this,
            ReaderTrayCommand.ToggleClipboardMonitoring);
        menu.Items.Add(_monitoringItem);
        Add(menu, "Service Status", ReaderTrayCommand.ServiceStatus);
        menu.Items.Add(new Forms.ToolStripSeparator());
        Add(menu, "Exit", ReaderTrayCommand.Exit);

        _notifyIcon = new Forms.NotifyIcon
        {
            Text = "TTS Platform Reader",
            Icon = SystemIcons.Application,
            ContextMenuStrip = menu,
            Visible = true,
        };
        _notifyIcon.DoubleClick += (_, _) => Command?.Invoke(this, ReaderTrayCommand.OpenReader);
    }

    public event EventHandler<ReaderTrayCommand>? Command;

    public void SetClipboardMonitoring(bool enabled) => _monitoringItem.Checked = enabled;

    public void SetStatus(string status)
    {
        var text = $"TTS Platform Reader — {status}";
        _notifyIcon.Text = text.Length <= 63 ? text : text[..63];
    }

    public void Dispose()
    {
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
    }

    private void Add(
        Forms.ContextMenuStrip menu,
        string label,
        ReaderTrayCommand command)
    {
        var item = new Forms.ToolStripMenuItem(label);
        item.Click += (_, _) => Command?.Invoke(this, command);
        menu.Items.Add(item);
    }
}
