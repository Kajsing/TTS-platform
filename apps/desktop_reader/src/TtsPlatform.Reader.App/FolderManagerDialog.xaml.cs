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

    private void FolderGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        var selected = SelectedFolder;
        if (selected is not null)
        {
            FolderNameTextBox.Text = selected.Name;
        }
        RenameButton.IsEnabled = !_busy && selected is not null;
        DeleteButton.IsEnabled = !_busy && selected is not null;
    }

    private void SetBusy(bool busy)
    {
        _busy = busy;
        FolderGrid.IsEnabled = !busy;
        FolderNameTextBox.IsEnabled = !busy;
        RenameButton.IsEnabled = !busy && SelectedFolder is not null;
        DeleteButton.IsEnabled = !busy && SelectedFolder is not null;
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();
}
