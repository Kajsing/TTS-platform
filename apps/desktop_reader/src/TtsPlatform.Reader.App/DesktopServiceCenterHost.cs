using System.IO;
using System.Windows;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

// Owns presentation lifetime, never synthesis or article storage. A closed
// Reader is disposed; the tray does not retain a hidden editor to stay alive.
internal sealed class DesktopServiceCenterHost : IDisposable
{
    private readonly IDesktopSettingsStore _settingsStore;
    private readonly Dispatcher _dispatcher;
    private readonly ReaderTrayIcon? _tray;
    private readonly bool _isolatedSmoke;
    private bool _openingReader;
    private bool _exiting;
    private bool _disposed;

    internal MainWindow? Reader { get; private set; }

    internal DesktopServiceCenterHost(IDesktopSettingsStore settingsStore, bool isolatedSmoke = false)
    {
        _settingsStore = settingsStore;
        _dispatcher = System.Windows.Application.Current.Dispatcher;
        _isolatedSmoke = isolatedSmoke;
        _tray = new ReaderTrayIcon();
        _tray.Command += TrayCommand;
        _tray.SetReaderAvailable(false);
        _tray.SetStatus("Reader closed; service is independent");
    }

    internal void QueueActivation(ReaderActivation activation)
    {
        if (_disposed || _dispatcher.HasShutdownStarted) return;
        _dispatcher.BeginInvoke(new Action(async () =>
        {
            if (_disposed || _exiting) return;
            if (activation == ReaderActivation.Background) return;
            await OpenReaderAsync();
            if (activation == ReaderActivation.OpenServiceCenter && Reader is { } reader)
                await reader.HandleTrayCommandAsync(ReaderTrayCommand.ServiceStatus);
        }));
    }

    internal async Task OpenReaderAsync()
    {
        if (_disposed || _exiting || _openingReader) return;
        if (Reader is not null)
        {
            Reader.OpenMainWindow();
            return;
        }
        _openingReader = true;
        try
        {
            // Reload after closing Reader: do not overwrite settings saved by
            // the previous window with a stale host-owned copy.
            var settings = await _settingsStore.LoadAsync();
            if (_disposed || _exiting) return;
            var reader = new MainWindow(_settingsStore, settings, _isolatedSmoke, sharedTray: _tray);
            Reader = reader;
            reader.Closed += ReaderClosed;
            _tray?.SetReaderAvailable(true);
            _tray?.SetClipboardMonitoring(settings.ClipboardMonitoringEnabled);
            System.Windows.Application.Current.MainWindow = reader;
            reader.Show();
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or
            System.Text.Json.JsonException or TtsPlatform.Reader.Client.ReaderClientConfigurationException)
        {
            if (_isolatedSmoke) throw;
            MessageBox.Show("Reader could not load its settings. Existing settings were not replaced.\n\n" + exception.Message,
                "Open Reader", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _openingReader = false;
        }
    }

    private void ReaderClosed(object? sender, EventArgs e)
    {
        if (sender is MainWindow reader) reader.Closed -= ReaderClosed;
        Reader = null;
        System.Windows.Application.Current.MainWindow = null;
        _tray?.SetReaderAvailable(false);
        _tray?.SetStatus("Reader closed; service is independent");
    }

    private async void TrayCommand(object? sender, ReaderTrayCommand command)
    {
        if (_disposed || _exiting) return;
        if (command == ReaderTrayCommand.Exit)
        {
            await ExitAsync();
            return;
        }
        if (command is ReaderTrayCommand.OpenReader or ReaderTrayCommand.ServiceStatus) await OpenReaderAsync();
        if (Reader is { } reader) await reader.HandleTrayCommandAsync(command);
    }

    internal async Task<bool> ExitAsync(bool confirm = true)
    {
        if (_exiting || _openingReader) return false;
        if (confirm && MessageBox.Show(
            "Exit Service Center? Its tray icon will disappear.\n\nThe local TTS service will keep running. " +
            "Reader playback will stop, but background audio exports will continue. Unsaved edits will be checked before closing.",
            "Exit Service Center", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
            return false;
        _exiting = true;
        try
        {
            if (Reader is { } reader && !await reader.CloseReaderAsync()) return false;
            System.Windows.Application.Current.Shutdown();
            return true;
        }
        finally
        {
            _exiting = false;
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        if (_tray is not null)
        {
            _tray.Command -= TrayCommand;
            _tray.Dispose();
        }
    }
}
