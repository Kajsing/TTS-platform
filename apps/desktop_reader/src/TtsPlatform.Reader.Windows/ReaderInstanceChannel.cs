using System.Diagnostics;
using System.IO.Pipes;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;

namespace TtsPlatform.Reader.Windows;

public enum ReaderActivation : byte
{
    OpenReader = 1,
    OpenServiceCenter = 2,
    Background = 3,
}

// The first pipe instance is the ownership lock: no mutex/pipe startup race and
// no PID file to trust. Windows restricts both endpoints to the current user.
public sealed class ReaderInstanceChannel : IDisposable
{
    private readonly NamedPipeServerStream _server;
    private readonly CancellationTokenSource _lifetime = new();
    private Task? _listener;

    private ReaderInstanceChannel(NamedPipeServerStream server) => _server = server;

    public static string DefaultScope
    {
        get
        {
            using var identity = WindowsIdentity.GetCurrent();
            using var process = Process.GetCurrentProcess();
            return $"{identity.User?.Value}|{process.SessionId}|{DesktopPaths.SettingsPath}";
        }
    }

    public static string PipeName(string scope) => "TtsPlatform.Reader." +
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(scope)))[..32];

    public static bool TryAcquire(string scope, out ReaderInstanceChannel? owner)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(scope);
        try
        {
            owner = new ReaderInstanceChannel(new NamedPipeServerStream(
                PipeName(scope), PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly | PipeOptions.FirstPipeInstance));
            return true;
        }
        catch (IOException)
        {
            owner = null;
            return false;
        }
    }

    public void Listen(Action<ReaderActivation> activate)
    {
        ArgumentNullException.ThrowIfNull(activate);
        if (_listener is not null) throw new InvalidOperationException("Activation listener is already running.");
        _listener = ListenAsync(activate);
    }

    private async Task ListenAsync(Action<ReaderActivation> activate)
    {
        while (!_lifetime.IsCancellationRequested)
        {
            try
            {
                await _server.WaitForConnectionAsync(_lifetime.Token).ConfigureAwait(false);
                using var request = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
                request.CancelAfter(TimeSpan.FromSeconds(2));
                var command = new byte[1];
                if (await _server.ReadAsync(command, request.Token).ConfigureAwait(false) == 1 &&
                    Enum.IsDefined((ReaderActivation)command[0]))
                {
                    activate((ReaderActivation)command[0]);
                    await _server.WriteAsync(command, request.Token).ConfigureAwait(false);
                }
            }
            catch (Exception exception) when (exception is IOException or OperationCanceledException or ObjectDisposedException)
            {
                // A disconnected/stalled activation client never tears down the owner.
            }
            finally
            {
                if (!_lifetime.IsCancellationRequested && _server.IsConnected) _server.Disconnect();
            }
        }
    }

    public static async Task<bool> SendAsync(
        string scope, ReaderActivation activation, CancellationToken cancellationToken = default)
    {
        if (!Enum.IsDefined(activation)) throw new ArgumentOutOfRangeException(nameof(activation));
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(5));
        try
        {
            await using var pipe = new NamedPipeClientStream(".", PipeName(scope), PipeDirection.InOut,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            await pipe.ConnectAsync(timeout.Token).ConfigureAwait(false);
            byte[] command = [(byte)activation];
            await pipe.WriteAsync(command, timeout.Token).ConfigureAwait(false);
            var reply = new byte[1];
            return await pipe.ReadAsync(reply, timeout.Token).ConfigureAwait(false) == 1 && reply[0] == command[0];
        }
        catch (Exception exception) when (exception is IOException or OperationCanceledException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    public void Dispose()
    {
        if (_lifetime.IsCancellationRequested) return;
        _lifetime.Cancel();
        _server.Dispose();
        // Do not block the dispatcher while an activation is being delivered.
        _ = (_listener ?? Task.CompletedTask).ContinueWith(_ => _lifetime.Dispose(), TaskScheduler.Default);
    }
}
