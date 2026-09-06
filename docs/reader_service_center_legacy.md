# Service Center: legacy Windows service tasks

Service Center can reuse compatible tasks created by `tts service-install --user`,
including custom task names and nested task paths. It does not rename, disable,
delete or rewrite those registrations. Optional Service Center autostart remains
off until explicitly enabled; competing enabled automatic launchers block it.

## Supported owners

- Current Windows user, interactive token, least privilege; the exact trusted
  Windows PowerShell executable and this installation's `run_scheduled_service.ps1`.
- The CLI's argument structure with an absolute log path and optional loopback
  host/port overrides. A supplied port must match the selected local endpoint;
  absent overrides retain the legacy task's normal local configuration.
- One action, no restart-on-failure policy, no repeated/calendar/boot trigger.
  Ordinary logon triggers and manual/no-trigger tasks are supported.
- The running task's action process must itself be the expected PowerShell
  executable, not a shared `taskeng`/`svchost` host. Its actual process token must
  belong to the current user. Its live command line must match the task action.

Unsupported custom scripts, other installations/users, elevated tasks, remote
bindings, shared engines and unknown terminal-started services stay visible but
cannot be adopted by API PID. Use their original owner to stop them. A previously
Reader-started service instead uses its persisted verified launcher lease.

## Start, stop and restart

Start reuses a single compatible enabled legacy registration. Existing running
instances block duplicate launches, even before their HTTP listener is ready.
Disabled inactive legacy tasks do not prevent the normal direct launcher. If
selection is ambiguous or incompatible, there is no fallback second service.
Restart reuses the same verified registration after confirmed shutdown.

Stop retains the normal local-owner authentication, global idle check, Reader
confirmation/edit protection and short maintenance reservation. It verifies the
task XML, InstanceGuid, action PID/start time, actual process token/command and
service PID/start time/chronological ancestry again after confirmation. Task XML
and reservation/cancellation are rechecked immediately before mutation.

Native testing found that `RunningTask.Stop` could return without completing
shutdown within the maintenance window. The implementation therefore uses the
same immediate verified idle process-tree termination as Reader-owned launchers,
not a delayed WM_CLOSE followed by an unsafe fallback. It never terminates a
shared task engine. Registration remains unchanged, both processes must exit,
and the coordinator must confirm the endpoint is gone before restart.

Task discovery and command-line reads happen only for startup checks or explicit
commands, not each dashboard poll. Enumeration is bounded. WMI reads only the
held action PID, never collects/logs other process command lines. Twelve-second
observation limits keep the UI responsive; a pending native operation retains
its gate and is cancelled before any late mutation. Unknown completion does not
trigger retries, rollback claims or a forced fallback.

## Evidence and limitations

Real Windows tests create uniquely named **no-trigger** synthetic tasks, not
production login entries, using temporary PowerShell scripts/loopback ports.
They test start/stop/restart, unrelated PIDs, changed XML and an action edited
while its previous command is still running, reservation expiry, startup
conflicts and late-operation cancellation. Fixtures are removed after tests.
Windows logoff/login and physical audio remain separate opt-in manual checks.

Primary Windows references:
[RunningTask.EnginePID](https://learn.microsoft.com/en-us/windows/win32/taskschd/runningtask-enginepid),
[TaskSettings.AllowHardTerminate](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-allowhardterminate),
[Win32_Process](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-process).
