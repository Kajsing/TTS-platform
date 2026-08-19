namespace TtsPlatform.Reader.Client;

public static class ServiceBaseUrl
{
    private static readonly HashSet<string> AllowedHosts =
        new(StringComparer.OrdinalIgnoreCase) { "localhost", "127.0.0.1" };

    public static Uri Parse(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri))
        {
            throw new ReaderClientConfigurationException("The service address must be an absolute URL.");
        }

        if (!string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase))
        {
            throw new ReaderClientConfigurationException("The service address must use HTTP.");
        }

        if (!AllowedHosts.Contains(uri.Host))
        {
            throw new ReaderClientConfigurationException("The service address must use localhost or 127.0.0.1.");
        }

        if (!string.IsNullOrEmpty(uri.UserInfo) ||
            uri.AbsolutePath != "/" ||
            !string.IsNullOrEmpty(uri.Query) ||
            !string.IsNullOrEmpty(uri.Fragment))
        {
            throw new ReaderClientConfigurationException(
                "The service address cannot contain credentials, a path, a query, or a fragment.");
        }

        return new UriBuilder(Uri.UriSchemeHttp, uri.Host, uri.IsDefaultPort ? 7777 : uri.Port, "/").Uri;
    }

    public static Uri ParseRemote(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri))
        {
            throw new ReaderClientConfigurationException(
                "The remote service address must be an absolute URL.");
        }
        if (!string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
        {
            throw new ReaderClientConfigurationException("The remote service address must use HTTPS.");
        }
        if (string.IsNullOrWhiteSpace(uri.Host) ||
            !string.IsNullOrEmpty(uri.UserInfo) ||
            uri.AbsolutePath != "/" ||
            !string.IsNullOrEmpty(uri.Query) ||
            !string.IsNullOrEmpty(uri.Fragment))
        {
            throw new ReaderClientConfigurationException(
                "The remote service address must be an HTTPS origin without credentials, a path, a query, or a fragment.");
        }
        return new UriBuilder(Uri.UriSchemeHttps, uri.Host, uri.IsDefaultPort ? 443 : uri.Port, "/").Uri;
    }
}

public sealed class ReaderClientConfigurationException : Exception
{
    public ReaderClientConfigurationException(string message)
        : base(message)
    {
    }

    public ReaderClientConfigurationException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

public sealed class ReaderTokenUnavailableException(string message) : Exception(message);

public sealed class ReaderServiceUnavailableException(string message, Exception? innerException = null)
    : Exception(message, innerException);

public sealed class ReaderApiException(
    string errorType,
    string message,
    int statusCode,
    string? requestId = null,
    IReadOnlyDictionary<string, object?>? details = null)
    : Exception(message)
{
    public string ErrorType { get; } = errorType;
    public int StatusCode { get; } = statusCode;
    public string? RequestId { get; } = requestId;
    public IReadOnlyDictionary<string, object?> Details { get; } =
        details ?? new Dictionary<string, object?>();
}
