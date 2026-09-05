# Service Center Windows startup

Open **Service Center > Windows startup**. Reader Options also has **Save options
and open Windows startup** under **Window & shortcuts**. That button explicitly
saves the Reader preferences before closing Options and opening the startup tab.

The checkbox is **off by default**. Merely installing, opening Reader, opening
the panel or checking status does not register startup. Changes are applied to
Windows immediately and read back; this is not a boolean in Reader settings.

## Behavior

- On: a current-user Task Scheduler logon task starts the published Reader
  executable with `--autostart`, after a ten-second logon delay. It uses an
  interactive user token and least privilege, without storing a Windows
  password or requesting elevation. It is not a machine-wide Windows service.
- Service Center remains in the tray. Neither Reader nor the dashboard opens.
  It verifies its actual enabled registration before starting the local service.
  An already ready/busy service is reused, not restarted. Duplicate startup
  activations are ignored by the existing single-instance host.
- Off: remove only this verified matching startup registration. Do not stop the
  current service, close Reader, delete content or re-enable a legacy task.
- The service connection remains the saved **local** URL/token-file selection,
  independently of Reader's selected remote workspace.
- Startup failures normally produce one tray notice with a route to status.
  Early host initialization failures use a failing process exit code rather than
  a modal login dialog. Actual Windows sign-out/logon is not part of automated
  validation; the published executable/activation path is exercised in isolation.

## Registration and safety

Task name: `TTS Platform Service Center <user hash>`, where the suffix is derived
from the current Windows SID. Different installations for the same user cannot
silently replace one another. Executable, arguments and working directory occupy
separate XML fields, preserving spaces/Unicode without shell concatenation.

The controller verifies the task source marker, current user, principal,
logon trigger, action/path/arguments, least privilege and relevant conditions.
Windows canonicalizes task XML: default values can be omitted and trigger users
can become account names. Matching handles those documented defaults and compares
only the current Windows identity; it does not resolve arbitrary domain users.
Mutations re-read the expected XML first; task creation uses create-only flags.

When the default legacy **TTS Platform Local Reader** task is enabled, the new
startup option explains the conflict and will not create a competing owner.
The legacy task remains untouched. Disable/remove it through its existing owner
before enabling the new option. Broader discovery and control of legacy/custom
scheduled launchers remain part of the next T1 integration slice.

Missing or moved installations, foreign/changed definitions, access denial and
unknown registration states are reported. Failed changes are read back when
possible; unknown is displayed as indeterminate, not falsely as Off. A ten-second
UI observation timeout does not imply that a native operation finished: its
serialization lock stays held until completion, so repeated clicks cannot queue
duplicate mutations. Refresh after Windows responds to see the actual state.

## Validation

Tests cover default-off/no writes, repeated enable/disable, spaces and Unicode,
current-user scoping, foreign/changed tasks, missing/moved runtime, legacy
conflicts/access denial, disabled registrations, failures/readback and in-flight
timeout safety. A real Windows test creates, reads and removes only a uniquely
named **disabled** fixture task. Production startup is never enabled for a test.

The WPF lifecycle smoke adds startup-page/contrast checks, the Options navigation
and saved-preference path, and hidden startup with fake service/registration
adapters: off performs no launch, on starts once, existing service is untouched.
The actual root-shortcut executable runs the same isolated smoke.

Windows API references:
[TaskFolder.RegisterTask](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertask),
[Task Scheduler schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema).
