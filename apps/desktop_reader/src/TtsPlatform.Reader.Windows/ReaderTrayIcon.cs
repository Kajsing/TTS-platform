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
    StartService,
    StopService,
    RestartService,
    Exit,
}

public sealed class ReaderTrayIcon : IDisposable
{
    private static int _liveInstances;
    public static int LiveInstances => Volatile.Read(ref _liveInstances);
    private bool _disposed;
    private readonly Forms.NotifyIcon _notifyIcon;
    private readonly Forms.ToolStripMenuItem _monitoringItem;
    private readonly List<Forms.ToolStripMenuItem> _readerItems = [];
    private readonly Icon _icon;
    private readonly Forms.ToolStripMenuItem _startService;
    private readonly Forms.ToolStripMenuItem _stopService;
    private readonly Forms.ToolStripMenuItem _restartService;
    private string _serviceStatus = "Checking";
    private string _readerStatus = "Reader closed";

    public ReaderTrayIcon()
    {
        _monitoringItem = new Forms.ToolStripMenuItem("Clipboard Prompt Mode");
        var menu = new Forms.ContextMenuStrip();
        Add(menu, "Open Reader", ReaderTrayCommand.OpenReader);
        Add(menu, "Compact Controller", ReaderTrayCommand.OpenCompactController, readerOnly: true);
        menu.Items.Add(new Forms.ToolStripSeparator());
        Add(menu, "Play/Pause", ReaderTrayCommand.PlayPause, readerOnly: true);
        Add(menu, "Stop playback", ReaderTrayCommand.Stop, readerOnly: true);
        Add(menu, "Read Clipboard", ReaderTrayCommand.ReadClipboard, readerOnly: true);
        _monitoringItem.Click += (_, _) => Command?.Invoke(
            this,
            ReaderTrayCommand.ToggleClipboardMonitoring);
        menu.Items.Add(_monitoringItem);
        _readerItems.Add(_monitoringItem);
        Add(menu, "Service Center…", ReaderTrayCommand.ServiceStatus);
        _startService = Add(menu, "Start local service", ReaderTrayCommand.StartService);
        _stopService = Add(menu, "Stop local service…", ReaderTrayCommand.StopService);
        _restartService = Add(menu, "Restart local service…", ReaderTrayCommand.RestartService);
        _startService.Enabled = _stopService.Enabled = _restartService.Enabled = false;
        menu.Items.Add(new Forms.ToolStripSeparator());
        Add(menu, "Exit Service Center...", ReaderTrayCommand.Exit);

        _icon = (Environment.ProcessPath is { } executable ? Icon.ExtractAssociatedIcon(executable) : null)
            ?? (Icon)SystemIcons.Application.Clone();
        _notifyIcon = new Forms.NotifyIcon
        {
            Text = "TTS Platform Service Center",
            Icon = _icon,
            ContextMenuStrip = menu,
            Visible = true,
        };
        _notifyIcon.DoubleClick += (_, _) => Command?.Invoke(this, ReaderTrayCommand.OpenReader);
        Interlocked.Increment(ref _liveInstances);
    }

    public event EventHandler<ReaderTrayCommand>? Command;

    public void SetClipboardMonitoring(bool enabled) => _monitoringItem.Checked = enabled;

    public void ShowServiceNotice(string title, string message) =>
        _notifyIcon.ShowBalloonTip(8000, title, message, Forms.ToolTipIcon.Warning);

    public void SetReaderAvailable(bool available)
    {
        foreach (var item in _readerItems) item.Enabled = available;
        if (!available) _monitoringItem.Checked = false;
    }

    public void SetStatus(string status)
    {
        _readerStatus = status;
        UpdateTooltip();
    }

    public void SetServiceStatus(string status, bool canStart, bool canStop)
    {
        _serviceStatus = status;
        _startService.Enabled = canStart;
        _stopService.Enabled = _restartService.Enabled = canStop;
        UpdateTooltip();
    }

    private void UpdateTooltip()
    {
        var text = $"TTS · {_serviceStatus} · {_readerStatus}";
        _notifyIcon.Text = text.Length <= 63 ? text : text[..63];
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _notifyIcon.Visible = false;
        _notifyIcon.ContextMenuStrip?.Dispose();
        _notifyIcon.Dispose();
        _icon.Dispose();
        Interlocked.Decrement(ref _liveInstances);
    }

    private Forms.ToolStripMenuItem Add(
        Forms.ContextMenuStrip menu,
        string label,
        ReaderTrayCommand command,
        bool readerOnly = false)
    {
        var item = new Forms.ToolStripMenuItem(label);
        item.Click += (_, _) => Command?.Invoke(this, command);
        menu.Items.Add(item);
        if (readerOnly) _readerItems.Add(item);
        return item;
    }
}
