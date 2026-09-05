using System.IO;
using System.Net.Http;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class AgentAccessPane : UserControl, IDisposable
{
    private AgentConnectionFiles _files = new();
    private readonly HttpClient _http = new(new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false })
    {
        Timeout = TimeSpan.FromSeconds(20),
    };
    private IReaderServiceClient? _client;
    private DesktopSettings? _settings;
    private bool _loaded;

    public AgentAccessPane()
    {
        InitializeComponent();
        IsVisibleChanged += async (_, _) =>
        {
            if (IsVisible && !_loaded && _client is not null)
            {
                _loaded = true;
                await GuardAsync(RefreshAsync, "Loading local agent access…");
            }
        };
    }

    public bool IsBusy { get; private set; }

    public void Configure(DesktopSettings settings, AgentConnectionFiles? files = null)
    {
        _files = files ?? new AgentConnectionFiles();
        _loaded = files is not null; // Isolated smoke explicitly controls its initial refresh.
        _settings = settings;
        AgentPythonTextBox.Text = AgentConnectionFiles.FindAgentPython() ?? "";
        if (!settings.ActiveConnection.IsLocal)
        {
            AgentControls.IsEnabled = false;
            AgentStatusText.Text = "MCP setup is local-only for now. Select the Local workspace in Reader first.";
            return;
        }
        _client = new ReaderServiceClient(_http, settings.ServiceBaseUrl,
            new FileTokenProvider(settings.EffectiveTokenSource.Path));
    }

    private async Task RefreshAsync()
    {
        if (_client is null)
        {
            return;
        }
        var selectedId = (AgentGrantsGrid.SelectedItem as GrantRow)?.Grant.Id;
        var foldersTask = _client.GetFoldersAsync();
        var grantsTask = _client.GetAgentGrantsAsync();
        await Task.WhenAll(foldersTask, grantsTask);
        var folders = (await foldersTask).Folders;
        var selectedFolderId = (AgentFolderCombo.SelectedItem as ReaderFolder)?.Id;
        AgentFolderCombo.ItemsSource = folders.Where(folder => !folder.PrivacyLocked).ToArray();
        AgentFolderCombo.SelectedItem = folders.FirstOrDefault(folder => !folder.PrivacyLocked && folder.Id == selectedFolderId);
        if (AgentFolderCombo.SelectedItem is null && AgentFolderCombo.Items.Count > 0)
        {
            AgentFolderCombo.SelectedIndex = 0;
        }
        var rows = (await grantsTask).Grants.Select(grant => new GrantRow(
            grant, folders.FirstOrDefault(folder => folder.Id == grant.FolderId)?.Name ?? "Unavailable folder")).ToArray();
        AgentGrantsGrid.ItemsSource = rows;
        AgentGrantsGrid.SelectedItem = rows.FirstOrDefault(row => row.Grant.Id == selectedId);
        AgentStatusText.Text = $"{rows.Count(row => row.Grant.RevokedAt is null)} active grant(s). " +
            (AgentFolderCombo.Items.Count == 0 ? "Create a normal folder in Library before enabling access." : "Choose a folder to enable access.");
        UpdateSelection();
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await GuardAsync(RefreshAsync, "Refreshing agent access…");

    private async void Provision_Click(object sender, RoutedEventArgs e)
    {
        if (IsBusy || _client is null || _settings is null || AgentFolderCombo.SelectedItem is not ReaderFolder folder)
        {
            return;
        }
        if (MessageBox.Show(Window.GetWindow(this),
            $"Allow an agent to read, create and edit articles in '{folder.Name}'?\n\n" +
            "Other folders, deletion and playback controls are not included. You can revoke access here at any time.",
            "Enable agent access", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes)
        {
            return;
        }
        await GuardAsync(async () =>
        {
            var grant = await ProvisionAsync(folder.Id, AgentNameTextBox.Text.Trim());
            await RefreshAsync();
            AgentGrantsGrid.SelectedItem = AgentGrantsGrid.Items.Cast<GrantRow>().FirstOrDefault(row => row.Grant.Id == grant.Id);
            AgentStatusText.Text = "Access enabled. Its key is protected by Windows. Use the connection configuration below, then test the connection.";
        }, "Enabling folder access…");
    }

    private async void Revoke_Click(object sender, RoutedEventArgs e)
    {
        if (IsBusy || _client is null || AgentGrantsGrid.SelectedItem is not GrantRow row)
        {
            return;
        }
        if (MessageBox.Show(Window.GetWindow(this),
            $"Revoke '{row.Name}'? Articles and imported chapter history will be kept.",
            "Revoke agent access", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes)
        {
            return;
        }
        await GuardAsync(async () =>
        {
            try
            {
                await RevokeAsync(row.Grant.Id);
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                await RefreshAsync();
                AgentStatusText.Text = "Access revoked. The now-unusable protected key could not be removed locally. Articles were kept.";
                return;
            }
            await RefreshAsync();
            AgentStatusText.Text = "Access revoked and the local connection/key files removed. Articles and chapter history were kept.";
        }, "Revoking agent access…");
    }

    internal async Task<ReaderAgentGrant> ProvisionAsync(string folderId, string name)
    {
        var provision = await _client!.ProvisionAgentAsync(new ReaderAgentGrantRequest(folderId, name));
        try
        {
            _files.Save(provision, _settings!.ServiceBaseUrl);
        }
        catch
        {
            try
            {
                await _client.RevokeAgentAsync(provision.Grant.Id);
            }
            catch
            {
                throw new IOException("Local key setup failed and the service could not confirm revocation. Refresh this list and revoke the new grant before retrying.");
            }
            throw;
        }
        return provision.Grant;
    }

    internal async Task RevokeAsync(string grantId)
    {
        await _client!.RevokeAgentAsync(grantId);
        _files.RemoveRevoked(grantId);
    }

    internal async Task RefreshForSmokeAsync(string? grantId = null)
    {
        await RefreshAsync();
        if (grantId is not null)
        {
            AgentGrantsGrid.SelectedItem = AgentGrantsGrid.Items.Cast<GrantRow>().Single(row => row.Grant.Id == grantId);
        }
    }

    private async void Check_Click(object sender, RoutedEventArgs e)
    {
        if (AgentGrantsGrid.SelectedItem is not GrantRow row)
        {
            return;
        }
        await GuardAsync(async () =>
        {
            var ready = await _files.CheckAsync(row.Grant.Id, AgentPythonTextBox.Text);
            AgentStatusText.Text = ready
                ? "Connection ready: the MCP adapter can unlock its Windows key and reach its granted folder."
                : "Connection failed. Check the agent environment, service and grant status. Recreate access if its key is missing.";
        }, "Testing the local MCP connection…");
    }

    private void PythonBrowse_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Choose Reader agent Python", Filter = "Python executable|python.exe|Executable|*.exe" };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true)
        {
            AgentPythonTextBox.Text = dialog.FileName;
        }
    }

    private void Python_TextChanged(object sender, TextChangedEventArgs e) => UpdateSelection();
    private void Grant_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateSelection();

    private void UpdateSelection()
    {
        if (AgentConfigurationTextBox is null)
        {
            return;
        }
        var grant = (AgentGrantsGrid.SelectedItem as GrantRow)?.Grant;
        RevokeAgentButton.IsEnabled = grant is not null;
        CheckAgentButton.IsEnabled = grant?.RevokedAt is null && grant is not null && _files.HasConnection(grant.Id);
        ProvisionAgentButton.IsEnabled = AgentFolderCombo.Items.Count > 0;
        if (grant is null || grant.RevokedAt is not null)
        {
            AgentConfigurationTextBox.Text = "Select an active grant created on this computer to see its client configuration.";
            return;
        }
        try
        {
            AgentConfigurationTextBox.Text = _files.ClientConfiguration(grant.Id, AgentPythonTextBox.Text);
        }
        catch (ReaderClientConfigurationException exception)
        {
            AgentConfigurationTextBox.Text = exception.Message;
        }
    }

    private async Task GuardAsync(Func<Task> action, string message)
    {
        if (IsBusy)
        {
            return;
        }
        IsBusy = true;
        AgentControls.IsEnabled = false;
        AgentStatusText.Text = message;
        try
        {
            await action();
        }
        catch (Exception exception) when (exception is ReaderApiException or ReaderClientConfigurationException or
            ReaderServiceUnavailableException or ReaderTokenUnavailableException or IOException or
            UnauthorizedAccessException or OperationCanceledException or System.Text.Json.JsonException or
            System.ComponentModel.Win32Exception)
        {
            AgentStatusText.Text = exception is OperationCanceledException
                ? "The connection check timed out. No article was changed."
                : $"Agent setup: {exception.Message}";
        }
        finally
        {
            IsBusy = false;
            AgentControls.IsEnabled = _client is not null;
            UpdateSelection();
        }
    }

    public void Dispose() => _http.Dispose();

    private sealed record GrantRow(ReaderAgentGrant Grant, string FolderName)
    {
        public string Name => Grant.Name;
    }
}
