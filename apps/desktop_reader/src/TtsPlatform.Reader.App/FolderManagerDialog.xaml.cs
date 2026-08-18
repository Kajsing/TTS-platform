using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Controls;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class FolderManagerDialog : Window
{
    private readonly IReaderServiceClient _client;
    private readonly ObservableCollection<ReaderFolder> _folders = [];
    private bool _busy;

    public FolderManagerDialog(IReaderServiceClient client)
    {
        _client = client;
        InitializeComponent();
        FolderGrid.ItemsSource = _folders;
        Loaded += async (_, _) => await RefreshAsync();
    }

    public bool Changed { get; private set; }

    private ReaderFolder? SelectedFolder => FolderGrid.SelectedItem as ReaderFolder;

    private async Task RefreshAsync(string? selectedId = null)
    {
        SetBusy(true);
        try
        {
            var page = await _client.GetFoldersAsync();
            _folders.Clear();
            foreach (var folder in page.Folders)
            {
                _folders.Add(folder);
            }
            FolderGrid.SelectedItem = _folders.FirstOrDefault(item => item.Id == selectedId);
            StatusText.Text = $"{_folders.Count} folder(s).";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            StatusText.Text = $"Folders: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void CreateButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || string.IsNullOrWhiteSpace(FolderNameTextBox.Text))
        {
            return;
        }
        SetBusy(true);
        try
        {
            var folder = await _client.CreateFolderAsync(
                new CreateFolderRequest(FolderNameTextBox.Text.Trim()));
            Changed = true;
            FolderNameTextBox.Clear();
            await RefreshAsync(folder.Id);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            StatusText.Text = $"Create folder: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void RenameButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null || string.IsNullOrWhiteSpace(FolderNameTextBox.Text))
        {
            return;
        }
        SetBusy(true);
        try
        {
            var folder = await _client.UpdateFolderAsync(
                selected.Id,
                new UpdateFolderRequest(FolderNameTextBox.Text.Trim(), selected.RowVersion));
            Changed = true;
            await RefreshAsync(folder.Id);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            StatusText.Text = $"Rename folder: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void DeleteButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null)
        {
            return;
        }
        var choice = MessageBox.Show(
            this,
            $"This folder contains {selected.ArticleCount:N0} article(s).\n\n" +
            "Yes: move its articles to All articles, then delete the folder.\n" +
            "No: delete its articles and the folder.\n" +
            "Cancel: keep everything.",
            "Delete article folder",
            MessageBoxButton.YesNoCancel,
            MessageBoxImage.Warning,
            MessageBoxResult.Cancel);
        if (choice is MessageBoxResult.Cancel)
        {
            return;
        }
        var mode = choice is MessageBoxResult.Yes ? "move_to_root" : "delete_articles";
        SetBusy(true);
        try
        {
            var result = await _client.DeleteFolderAsync(
                selected.Id,
                selected.RowVersion,
                mode);
            Changed = true;
            FolderNameTextBox.Clear();
            await RefreshAsync();
            StatusText.Text = result.DeletedArticles > 0
                ? $"Folder and {result.DeletedArticles:N0} article(s) deleted."
                : $"Folder deleted; {result.MovedArticles:N0} article(s) moved to All articles.";
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            StatusText.Text = $"Delete folder: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void SetPrivacyButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null || selected.PrivacyLocked)
        {
            return;
        }
        var dialog = new FolderPrivacyDialog(FolderPrivacyDialogMode.Setup, selected.Name)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() is not true)
        {
            return;
        }
        await RunPrivacyActionAsync(
            selected.Id,
            async () =>
            {
                var result = await _client.SetupPrivacyLockAsync(
                    selected.Id,
                    new ReaderPrivacySetupRequest(dialog.PrimarySecret, selected.RowVersion));
                ShowRecoveryKey(result.RecoveryKey);
            },
            "Set Privacy lock");
    }

    private async void UnlockButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null || !selected.PrivacyLocked || selected.PrivacyUnlocked)
        {
            return;
        }
        var dialog = new FolderPrivacyDialog(FolderPrivacyDialogMode.Unlock, selected.Name)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() is not true)
        {
            return;
        }
        await RunPrivacyActionAsync(
            selected.Id,
            () => _client.UnlockPrivacyLockAsync(
                selected.Id,
                new ReaderPrivacyUnlockRequest(dialog.PrimarySecret)),
            "Unlock folder");
    }

    private async void RelockButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null || !selected.PrivacyUnlocked)
        {
            return;
        }
        await RunPrivacyActionAsync(
            selected.Id,
            () => _client.RelockPrivacyLockAsync(selected.Id),
            "Relock folder");
    }

    private async void ChangeCodeButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null || !selected.PrivacyUnlocked)
        {
            return;
        }
        var dialog = new FolderPrivacyDialog(FolderPrivacyDialogMode.Change, selected.Name)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() is not true)
        {
            return;
        }
        await RunPrivacyActionAsync(
            selected.Id,
            async () =>
            {
                var result = await _client.ChangePrivacyLockAsync(
                    selected.Id,
                    new ReaderPrivacyChangeRequest(
                        dialog.PrimarySecret,
                        dialog.NewCode,
                        selected.RowVersion));
                ShowRecoveryKey(result.RecoveryKey);
            },
            "Change Privacy lock code");
    }

    private async void RecoverButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null || !selected.PrivacyLocked || selected.PrivacyUnlocked)
        {
            return;
        }
        var dialog = new FolderPrivacyDialog(FolderPrivacyDialogMode.Recover, selected.Name)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() is not true)
        {
            return;
        }
        await RunPrivacyActionAsync(
            selected.Id,
            async () =>
            {
                var result = await _client.RecoverPrivacyLockAsync(
                    selected.Id,
                    new ReaderPrivacyRecoveryRequest(
                        dialog.PrimarySecret,
                        dialog.NewCode,
                        selected.RowVersion));
                ShowRecoveryKey(result.RecoveryKey);
            },
            "Recover Privacy lock");
    }

    private async void RemovePrivacyButton_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectedFolder;
        if (_busy || selected is null || !selected.PrivacyUnlocked)
        {
            return;
        }
        if (MessageBox.Show(
            this,
            "Remove the Privacy lock? The articles remain in the folder and become visible whenever Reader is open.",
            "Remove Privacy lock",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No) is not MessageBoxResult.Yes)
        {
            return;
        }
        var dialog = new FolderPrivacyDialog(FolderPrivacyDialogMode.Remove, selected.Name)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() is not true)
        {
            return;
        }
        await RunPrivacyActionAsync(
            selected.Id,
            () => _client.RemovePrivacyLockAsync(
                selected.Id,
                new ReaderPrivacyRemoveRequest(dialog.PrimarySecret, selected.RowVersion)),
            "Remove Privacy lock");
    }

    private async Task RunPrivacyActionAsync(
        string folderId,
        Func<Task> operation,
        string operationName)
    {
        SetBusy(true);
        try
        {
            await operation();
            Changed = true;
            await RefreshAsync(folderId);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            StatusText.Text = $"{operationName}: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void ShowRecoveryKey(string recoveryKey)
    {
        var dialog = new RecoveryKeyDialog(recoveryKey) { Owner = this };
        dialog.ShowDialog();
    }

    private void FolderGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        var selected = SelectedFolder;
        if (selected is not null)
        {
            FolderNameTextBox.Text = selected.Name;
        }
        UpdateActionButtons();
    }

    private void SetBusy(bool busy)
    {
        _busy = busy;
        FolderGrid.IsEnabled = !busy;
        FolderNameTextBox.IsEnabled = !busy;
        UpdateActionButtons();
    }

    private void UpdateActionButtons()
    {
        var selected = SelectedFolder;
        var available = !_busy && selected is not null;
        var accessible = available && (!selected!.PrivacyLocked || selected.PrivacyUnlocked);
        RenameButton.IsEnabled = accessible;
        DeleteButton.IsEnabled = accessible;
        SetPrivacyButton.IsEnabled = available && !selected!.PrivacyLocked;
        UnlockButton.IsEnabled = available && selected!.PrivacyLocked && !selected.PrivacyUnlocked;
        RelockButton.IsEnabled = available && selected!.PrivacyUnlocked;
        ChangeCodeButton.IsEnabled = available && selected!.PrivacyUnlocked;
        RecoverButton.IsEnabled = available && selected!.PrivacyLocked && !selected.PrivacyUnlocked;
        RemovePrivacyButton.IsEnabled = available && selected!.PrivacyUnlocked;
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();
}
