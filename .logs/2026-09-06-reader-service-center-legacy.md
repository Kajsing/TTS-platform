# Legacy owner integration and T1 acceptance

Completed the remaining T1 scheduled-owner compatibility. Added
`LegacyServiceTasks.cs`, native/fake regression coverage and startup discovery
integration. `LocalServiceProcessControl` keeps exact lease ownership for direct
launchers and now recognizes compatible current-user legacy tasks by definition,
live token/command line, instance and process ancestry. No task-name-only kill,
unowned Python adoption, registration rewrite or new dependency.

Implementation evidence influenced the local details, not the architecture:

- On this Windows host, the running task EnginePID identifies the actual
  PowerShell action. Shared-engine variants are explicitly refused.
- RunningTask.Stop did not complete the synthetic shutdown within the bounded
  reservation. Use the same immediate verified idle-tree termination as the
  existing direct-launcher controls. No delayed/forced fallback.
- Reading current task XML alone is insufficient when its action was edited
  while a previous command still runs. Added a local WMI read of only the held
  action PID and exact command comparison; COM Properties_.Item(...).Value is
  required to read the WMI value correctly. No command lines are logged.
- Native discovery/commands retain their lock after a twelve-second observation
  timeout and cancel any late mutation. A fake blocked read verifies that no
  duplicate or delayed launcher starts after timeout.

Validation: 223 .NET tests (45 client, 108 application, 70 Windows); 549 Python
tests, 2 optional skips in 55.50 s; Ruff and .NET format verification. The desktop
checker also passed isolated live HTTP/status/reservation/Reader workflows,
portable packaging and WPF lifecycle/folder checks. Physical audio/clipboard/
hotkey tests were not run against user applications. The exact root-shortcut win-x64 target
was republished while Reader was closed. Its isolated lifecycle/dashboard/
startup smoke passed, including dirty-edit preservation and hidden startup:
`logs/service-center-legacy-20260906/shortcut.json`. Task fixtures have no automatic
trigger, use synthetic child processes and ephemeral ports, and are removed.
Verified zero temporary TTS test tasks and zero new production autostart entries.

T1 acceptance is complete; T2 compatible-voice library is the next slice and
the goal remains active. No user data, clipboard, credentials, model manifest,
production service or startup registration changed. Preserve the pre-existing
`models/MANIFEST.json` working-tree change. U8 remains parked.
