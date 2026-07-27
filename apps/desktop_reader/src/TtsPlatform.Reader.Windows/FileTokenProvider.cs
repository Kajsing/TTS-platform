using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Windows;

public sealed class FileTokenProvider(string? tokenPath) : ITokenProvider
{
    public async ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(tokenPath) || !File.Exists(tokenPath))
        {
            return null;
        }

        var token = await File.ReadAllTextAsync(tokenPath, cancellationToken).ConfigureAwait(false);
        return string.IsNullOrWhiteSpace(token) ? null : token.Trim();
    }
}
