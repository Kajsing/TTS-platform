using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    // Opt-in --smoke-test only: synthetic service responses and isolated settings.
    // Unexpected API methods fail instead of accessing any live service or grant.
    private async Task RunFolderVisibilitySmokeAsync(string marker)
    {
        var root = Path.GetDirectoryName(Path.GetFullPath(marker))!;
        Directory.CreateDirectory(root);
        var client = DispatchProxy.Create<IReaderServiceClient, FolderVisibilitySmokeClient>();
        var fake = (FolderVisibilitySmokeClient)client;
        var now = DateTimeOffset.UtcNow;
        var folder = new ReaderFolder("synthetic-folder", "Agent-import (test)", now, now, 1, 1, false, true);
        var metadata = JsonSerializer.SerializeToElement(new { });
        var document = new ReaderDocument("synthetic-article", "Hidden story (test)", "plain_text",
            null, null, null, null, "inbox", now, now, now, null, 1, 1, 1, 1, 10, metadata,
            FolderId: folder.Id);
        var block = new ReaderBlock("synthetic-block", document.Id, null, 0, "paragraph",
            "Test story", 10, "hash", 1, metadata);
        fake.Folders = [folder];
        fake.Documents = [document, document with { Id = "root-article", Title = "Root article (test)", FolderId = null }];
        _client = client;
        _library = new LibraryPager(client);
        _editor = new DocumentEditor(client);
        DocumentsGrid.ItemsSource = _library.Documents;
        await RefreshLibraryAsync();
        _editor.LoadBlock(document, block);
        var dialog = new FolderManagerDialog(client, IsFolderOpen, SetFolderOpenAsync) { Owner = this };
        dialog.Show();
        await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);

        static void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
        }
        static IEnumerable<T> Descendants<T>(DependencyObject parent) where T : DependencyObject
        {
            for (var index = 0; index < VisualTreeHelper.GetChildrenCount(parent); index++)
            {
                var child = VisualTreeHelper.GetChild(parent, index);
                if (child is T match) yield return match;
                foreach (var descendant in Descendants<T>(child)) yield return descendant;
            }
        }
        async Task ToggleOpenAsync(FolderManagerDialog target)
        {
            target.UpdateLayout();
            var checkBox = Descendants<CheckBox>(target.FolderGrid).Single(box =>
                System.Windows.Automation.AutomationProperties.GetName(box) == "Show folder articles");
            var peer = new CheckBoxAutomationPeer(checkBox);
            ((IToggleProvider)peer.GetPattern(PatternInterface.Toggle)!).Toggle();
            var deadline = DateTime.UtcNow.AddSeconds(5);
            while (!target.CloseButton.IsEnabled && DateTime.UtcNow < deadline)
            {
                await Task.Delay(10);
            }
            Require(target.CloseButton.IsEnabled, "Folder checkbox operation timed out.");
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        }

        try
        {
            await ToggleOpenAsync(dialog);
            Require(!IsFolderOpen(folder.Id), "Open checkbox did not close the folder.");
            Require(_library.Documents.Count == 1 && _library.Documents[0].FolderId is null,
                "Closed folder remained in the library.");
            Require(_editor.Document is null, "Closing the current folder did not clear the editor.");
            Require(!FolderVisibility.IsOpen(await _settingsStore.LoadAsync(), folder.Id),
                "Closed folder state did not survive a settings reload.");
            await RefreshFoldersAsync();
            await RefreshLibraryAsync();
            Require(_folderFilters.Count == 1 && _library.Documents.Count == 1,
                "Refresh restored a closed folder.");
            CaptureSmokeWindow(dialog, Path.Combine(root, "folder-closed.png"));
            CaptureSmokeWindow(this, Path.Combine(root, "library-hidden.png"));

            await ToggleOpenAsync(dialog);
            await RefreshFoldersAsync();
            await RefreshLibraryAsync();
            Require(IsFolderOpen(folder.Id) && _library.Documents.Count == 2 && _folderFilters.Count == 2,
                "Reopening the folder did not restore the original library articles.");
            Require(FolderVisibility.IsOpen(await _settingsStore.LoadAsync(), folder.Id),
                "Reopened state did not survive a settings reload.");
            Require(!dialog.RelockButton.IsEnabled && dialog.SetPrivacyButton.IsEnabled,
                "Open checkbox changed the unlocked folder's Privacy controls.");

            _editor.LoadBlock(document, block);
            _editor.SetWorkingText("Unsaved test edit");
            await ToggleOpenAsync(dialog);
            Require(IsFolderOpen(folder.Id) && _editor.HasUnsavedChanges,
                "Closing the folder discarded an unsaved edit.");
            _editor.RevertLocalChanges();
        }
        finally
        {
            dialog.Close();
        }

        var failing = new FolderManagerDialog(client, IsFolderOpen,
            (_, _) => throw new IOException("Synthetic settings-save failure"))
        { Owner = this };
        failing.Show();
        await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        try
        {
            await ToggleOpenAsync(failing);
            var box = Descendants<CheckBox>(failing.FolderGrid).Single(item =>
                System.Windows.Automation.AutomationProperties.GetName(item) == "Show folder articles");
            Require(box.IsChecked == true && IsFolderOpen(folder.Id), "Save failure did not revert the checkbox.");
        }
        finally
        {
            failing.Close();
        }
        Require(fake.Documents.Count == 2 && !folder.PrivacyLocked,
            "Visibility changed source data or Privacy lock state.");
        var options = new OptionsDialog(_settings) { Owner = this };
        options.Show();
        options.UpdateLayout();
        options.Close();
        File.WriteAllText(marker, JsonSerializer.Serialize(new
        {
            rendered = true,
            options_rendered = true,
            title = Title,
            folder_toggle = true,
            hidden_after_refresh = true,
            editor_cleared = true,
            settings_reload = true,
            reopened = true,
            unsaved_edit_preserved = true,
            save_failure_reverted = true,
            service_reads_only = true,
        }));
    }
}

public class FolderVisibilitySmokeClient : DispatchProxy
{
    public IReadOnlyList<ReaderFolder> Folders { get; set; } = [];
    public IReadOnlyList<ReaderDocument> Documents { get; set; } = [];

    protected override object? Invoke(MethodInfo? targetMethod, object?[]? args) => targetMethod?.Name switch
    {
        nameof(IReaderServiceClient.GetFoldersAsync) => Task.FromResult(new ReaderFolderPage(Folders)),
        nameof(IReaderServiceClient.GetDocumentsByFolderAsync) => Task.FromResult(new DocumentPage(
            Documents.Where(item => args?[4] is not string folderId || item.FolderId == folderId).ToArray(), null)),
        _ => throw new InvalidOperationException($"Unexpected API in folder visibility smoke: {targetMethod?.Name}"),
    };
}
