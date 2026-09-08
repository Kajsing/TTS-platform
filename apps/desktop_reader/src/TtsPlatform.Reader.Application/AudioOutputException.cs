namespace TtsPlatform.Reader.Application;

public enum AudioOutputFailure { Unavailable, Stalled }

// Backend-neutral, safe UI/log failure: never expose driver/device details.
public sealed class AudioOutputException(AudioOutputFailure failure, Exception? innerException = null)
    : Exception(failure == AudioOutputFailure.Stalled
        ? "The audio device stopped responding. Press Play to reconnect and resume reading."
        : "The audio device is unavailable. Check Windows sound output, then press Play to reconnect.", innerException)
{
    public AudioOutputFailure Failure { get; } = failure;
}
