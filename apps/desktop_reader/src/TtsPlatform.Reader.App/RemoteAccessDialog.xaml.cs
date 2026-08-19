using System.Collections.ObjectModel;
using System.IO;
using System.Net.Http;
using System.Windows;
using System.Windows.Controls;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class RemoteAccessDialog : Window
{
    private readonly IDesktopSettingsStore _settingsStore;
    private readonly DpapiCredentialStore _credentialStore = new();
    private readonly WindowsFirewallRuleManager _firewall = new();
    private readonly HttpClient _adminHttpClient = new() { Timeout = TimeSpan.FromSeconds(20) };
    private readonly RemoteAccessAdminClient _adminClient;
    private readonly ObservableCollection<RemotePairingDevice> _devices = [];
    private bool _busy;
    private RemoteAccessStatus? _serverStatus;

    public RemoteAccessDialog(IDesktopSettingsStore settingsStore, DesktopSettings settings)
    {
        _settingsStore = settingsStore;
        Settings = settings;
        _adminClient = new RemoteAccessAdminClient(
            _adminHttpClient,
            settings.ServiceBaseUrl,
            new FileTokenProvider(settings.EffectiveTokenSource.Path));
        InitializeComponent();
        DeviceNameTextBox.Text = Environment.MachineName;
        DevicesGrid.ItemsSource = _devices;
        RefreshProfiles();
        Loaded += async (_, _) => await RefreshServerAsync();
        Closing += (_, args) => args.Cancel = _busy;
        Closed += (_, _) => _adminHttpClient.Dispose();
    }

    public DesktopSettings Settings { get; private set; }

    private async void PairButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy)
        {
            return;
        }
        SetBusy(true, "Pairing this computer…");
        string? savedCredentialId = null;
        var settingsSaved = false;
        try
        {
            var invitation = RemotePairingClient.ParseInvitation(InvitationTextBox.Text);
            var result = await new RemotePairingClient().PairAsync(invitation, DeviceNameTextBox.Text);
            var profileId = Guid.NewGuid().ToString();
            _credentialStore.Save(result.Device.Id, result.Credential);
            savedCredentialId = result.Device.Id;
            var profiles = Settings.EffectiveRemoteConnectionProfiles
                .Append(new RemoteConnectionProfileSettings(
                    profileId,
                    NormalizeWorkspaceName(WorkspaceNameTextBox.Text),
                    ServiceBaseUrl.ParseRemote(invitation.Endpoint).AbsoluteUri,
                    invitation.ServerSpkiPin,
                    result.Device.Id))
                .ToArray();
            Settings = Settings with
            {
                ActiveConnectionProfileId = profileId,
                RemoteConnectionProfiles = profiles,
            };
            await _settingsStore.SaveAsync(Settings);
            settingsSaved = true;
            InvitationTextBox.Clear();
            RefreshProfiles();
            DialogStatusText.Text = "Paired. The new remote workspace is selected.";
        }
        catch (Exception exception) when (
            exception is ReaderClientConfigurationException or
                ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException or
                IOException or
                UnauthorizedAccessException)
        {
            if (!settingsSaved && savedCredentialId is not null)
            {
                _credentialStore.Delete(savedCredentialId);
            }
            DialogStatusText.Text = $"Pairing failed: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void RemoveProfileButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || ProfilesList.SelectedItem is not RemoteConnectionProfileSettings profile)
        {
            return;
        }
        if (MessageBox.Show(
            this,
            "Remove this remote workspace and its protected credential from this computer? " +
            "This does not revoke the computer on the server; use the server's paired-computers list for that.",
            "Remove remote workspace",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No) is not MessageBoxResult.Yes)
        {
            return;
        }
        SetBusy(true, "Removing the remote workspace from this computer…");
        try
        {
            var updated = Settings with
            {
                ActiveConnectionProfileId = string.Equals(
                    Settings.ActiveConnectionProfileId,
                    profile.Id,
                    StringComparison.Ordinal) ? "local" : Settings.ActiveConnectionProfileId,
                RemoteConnectionProfiles = Settings.EffectiveRemoteConnectionProfiles
                    .Where(item => !string.Equals(item.Id, profile.Id, StringComparison.Ordinal))
                    .ToArray(),
            };
            await _settingsStore.SaveAsync(updated);
            Settings = updated;
            RefreshProfiles();
            try
            {
                _credentialStore.Delete(profile.CredentialId);
                DialogStatusText.Text = "Remote workspace removed from this computer.";
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException)
            {
                DialogStatusText.Text =
                    $"Workspace removed. Its unusable protected credential could not be deleted: {exception.Message}";
            }
        }
        catch (Exception exception) when (
            exception is ReaderClientConfigurationException or
                ReaderTokenUnavailableException or
                IOException or
                UnauthorizedAccessException)
        {
            DialogStatusText.Text = $"Remote workspace was not removed: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void RotateCredentialButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || ProfilesList.SelectedItem is not RemoteConnectionProfileSettings profile)
        {
            return;
        }
        SetBusy(true, "Rotating the selected device credential…");
        var confirmed = false;
        try
        {
            var current = _credentialStore.Load(profile.CredentialId)
                ?? throw new ReaderTokenUnavailableException(
                    "The protected credential is missing. Pair this computer again.");
            var client = new RemoteCredentialRotationClient();
            var rotation = await client.BeginAsync(
                profile.ServiceBaseUrl,
                profile.ServerSpkiPin,
                current);
            _credentialStore.SavePending(profile.CredentialId, rotation.PendingCredential);
            await client.ConfirmAsync(
                profile.ServiceBaseUrl,
                profile.ServerSpkiPin,
                current,
                rotation.RotationId,
                rotation.PendingCredential);
            confirmed = true;
            _credentialStore.PromotePending(profile.CredentialId);
            DialogStatusText.Text = "Credential rotated without changing the workspace.";
        }
        catch (Exception exception) when (
            exception is ReaderClientConfigurationException or
                ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException or
                IOException or
                UnauthorizedAccessException)
        {
            if (!confirmed)
            {
                _credentialStore.DeletePending(profile.CredentialId);
            }
            DialogStatusText.Text = confirmed
                ? "The server confirmed rotation, but Windows could not promote the protected credential. Pair again before removing this workspace."
                : $"Credential rotation failed safely: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void EnableServerButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy)
        {
            return;
        }
        SetBusy(true, "Preparing secure remote access…");
        try
        {
            var request = BuildSetupRequest(start: false);
            var prepared = await _adminClient.SetupAsync(request);
            var profile = prepared.Profile ?? throw new ReaderClientConfigurationException(
                "The local service did not return a remote profile.");
            if (MessageBox.Show(
                this,
                "Windows will ask for permission to create one narrow inbound firewall rule. " +
                "The rule is limited to the selected address, port, program, network profile, and peer. Continue?",
                "Create Reader firewall rule",
                MessageBoxButton.YesNo,
                MessageBoxImage.Information,
                MessageBoxResult.No) is not MessageBoxResult.Yes)
            {
                DialogStatusText.Text = "Remote access remains disabled; no firewall permission was requested.";
                return;
            }
            await _firewall.CreateAsync(profile);
            var enabled = await _adminClient.SetupAsync(request with { Start = true });
            DialogStatusText.Text = enabled.Running
                ? "Secure remote access is running."
                : "The profile was saved, but the secure gateway did not start.";
            await RefreshServerAsync();
        }
        catch (Exception exception) when (
            exception is ReaderClientConfigurationException or
                ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException or
                IOException or
                UnauthorizedAccessException)
        {
            DialogStatusText.Text = $"Remote setup failed safely: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void DisableServerButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || MessageBox.Show(
            this,
            "Disable remote access, revoke every paired computer, clear open invitations, and remove the exact firewall rule? The local library is not deleted.",
            "Disable remote access",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No) is not MessageBoxResult.Yes)
        {
            return;
        }
        SetBusy(true, "Stopping secure remote access…");
        try
        {
            var current = await _adminClient.GetStatusAsync();
            var disabled = await _adminClient.DisableAsync();
            if (current.Profile is not null)
            {
                await _firewall.RemoveAsync(current.Profile.ProfileId);
            }
            DialogStatusText.Text = disabled.Running
                ? "The gateway did not stop cleanly. Check status."
                : "Remote access is disabled; paired credentials were revoked.";
            await RefreshServerAsync();
        }
        catch (Exception exception) when (
            exception is ReaderClientConfigurationException or
                ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderTokenUnavailableException)
        {
            DialogStatusText.Text = $"Disable status: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void CreateInvitationButton_Click(object sender, RoutedEventArgs e)
    {
        SetBusy(true, "Creating a one-use invitation…");
        try
        {
            ServerInvitationTextBox.Text = RemotePairingClient.FormatInvitation(
                await _adminClient.CreateInvitationAsync());
            DialogStatusText.Text = "Invitation created. It expires in ten minutes and works once.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException or ReaderTokenUnavailableException)
        {
            DialogStatusText.Text = $"Invitation: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void CopyInvitationButton_Click(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(ServerInvitationTextBox.Text))
        {
            Clipboard.SetText(ServerInvitationTextBox.Text);
            DialogStatusText.Text = "Invitation copied. Transfer it through a channel you trust.";
        }
    }

    private async void RevokeDeviceButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || DevicesGrid.SelectedItem is not RemotePairingDevice device || device.RevokedAt is not null)
        {
            return;
        }
        if (MessageBox.Show(
            this,
            $"Revoke {device.DisplayName}? New requests will fail immediately and active playback will close.",
            "Revoke paired computer",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No) is not MessageBoxResult.Yes)
        {
            return;
        }
        SetBusy(true, "Revoking paired computer…");
        try
        {
            await _adminClient.RevokeDeviceAsync(device.Id);
            await RefreshServerAsync();
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException or ReaderTokenUnavailableException)
        {
            DialogStatusText.Text = $"Revoke: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void RefreshServerButton_Click(object sender, RoutedEventArgs e) =>
        await RefreshServerAsync();

    private async Task RefreshServerAsync()
    {
        try
        {
            var status = await _adminClient.GetStatusAsync();
            _serverStatus = status;
            ServerStatusText.Text = DescribeStatus(status);
            EnableServerButton.Content = status.Configured ? "Update secure access…" : "Set up secure access…";
            UpdateServerButtons();
            if (status.Profile is { } profile)
            {
                BindAddressTextBox.Text = profile.BindHost;
                PortTextBox.Text = profile.Port.ToString();
                RemoteAddressTextBox.Text = profile.FirewallRemoteAddress;
                InterfaceAliasTextBox.Text = profile.FirewallInterfaceAlias ?? string.Empty;
                SelectMode(profile.FirewallMode);
                SelectNetworkProfile(profile.FirewallProfile);
            }
            var page = await _adminClient.GetDevicesAsync();
            _devices.Clear();
            foreach (var device in page.Devices)
            {
                _devices.Add(device);
            }
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException or ReaderTokenUnavailableException)
        {
            ServerStatusText.Text = $"Local server controls unavailable: {exception.Message}";
            _serverStatus = null;
            UpdateServerButtons();
        }
    }

    private RemoteSetupRequest BuildSetupRequest(bool start)
    {
        if (!int.TryParse(PortTextBox.Text, out var port))
        {
            throw new ReaderClientConfigurationException("Port must be a number between 1024 and 65535.");
        }
        var mode = SelectedMode();
        return new RemoteSetupRequest(
            BindAddressTextBox.Text.Trim(),
            port,
            null,
            mode,
            mode == "lan" ? "LocalSubnet" : RemoteAddressTextBox.Text.Trim(),
            mode == "lan" ? null : InterfaceAliasTextBox.Text.Trim(),
            mode == "lan" ? "Private" : SelectedNetworkProfile(),
            start);
    }

    private void FirewallModeComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!IsInitialized)
        {
            return;
        }
        var lan = SelectedMode() == "lan";
        RemoteAddressTextBox.Text = lan ? "LocalSubnet" :
            RemoteAddressTextBox.Text == "LocalSubnet" ? string.Empty : RemoteAddressTextBox.Text;
        RemoteAddressTextBox.IsEnabled = !lan;
        InterfaceAliasTextBox.IsEnabled = !lan;
        NetworkProfileComboBox.IsEnabled = !lan;
        if (lan)
        {
            SelectNetworkProfile("Private");
        }
    }

    private void RefreshProfiles()
    {
        ProfilesList.ItemsSource = null;
        ProfilesList.ItemsSource = Settings.EffectiveRemoteConnectionProfiles;
        ProfilesList.SelectedItem = Settings.EffectiveRemoteConnectionProfiles.FirstOrDefault(profile =>
            string.Equals(profile.Id, Settings.ActiveConnectionProfileId, StringComparison.Ordinal));
    }

    private void SetBusy(bool busy, string? status = null)
    {
        _busy = busy;
        PairButton.IsEnabled = !busy;
        EnableServerButton.IsEnabled = !busy;
        RefreshServerButton.IsEnabled = !busy;
        RemoveProfileButton.IsEnabled = !busy;
        RotateCredentialButton.IsEnabled = !busy;
        RevokeDeviceButton.IsEnabled = !busy;
        UpdateServerButtons();
        if (status is not null)
        {
            DialogStatusText.Text = status;
        }
    }

    private void UpdateServerButtons()
    {
        CreateInvitationButton.IsEnabled = !_busy && _serverStatus is
        { Running: true, Firewall.Matches: true };
        DisableServerButton.IsEnabled = !_busy && _serverStatus?.Configured == true;
    }

    private static string NormalizeWorkspaceName(string value)
    {
        var name = string.Join(" ", value.Trim().Split(
            (char[]?)null,
            StringSplitOptions.RemoveEmptyEntries));
        if (name.Length is < 1 or > 80)
        {
            throw new ReaderClientConfigurationException(
                "Workspace name must contain 1 to 80 characters.");
        }
        return name;
    }

    private string SelectedMode() =>
        (FirewallModeComboBox.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "wireguard";

    private string SelectedNetworkProfile() =>
        (NetworkProfileComboBox.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "Public";

    private void SelectMode(string mode)
    {
        FirewallModeComboBox.SelectedItem = FirewallModeComboBox.Items
            .OfType<ComboBoxItem>()
            .First(item => string.Equals(item.Tag?.ToString(), mode, StringComparison.Ordinal));
    }

    private void SelectNetworkProfile(string profile)
    {
        NetworkProfileComboBox.SelectedItem = NetworkProfileComboBox.Items
            .OfType<ComboBoxItem>()
            .First(item => string.Equals(item.Content?.ToString(), profile, StringComparison.Ordinal));
    }

    private static string DescribeStatus(RemoteAccessStatus status)
    {
        if (!status.Configured)
        {
            return "Not configured. Local Reader is unchanged.";
        }
        var endpoint = status.Profile?.Endpoint ?? "unknown endpoint";
        if (status.Running && status.Firewall.Matches)
        {
            return $"Running securely at {endpoint}. Exact firewall rule verified. {status.DeviceCount} paired computer(s).";
        }
        var detail = status.StartupError ?? status.Firewall.Message ??
            "The gateway is stopped or the exact firewall rule is not verified.";
        return $"Disabled/stopped at {endpoint}. {detail}";
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();
}
