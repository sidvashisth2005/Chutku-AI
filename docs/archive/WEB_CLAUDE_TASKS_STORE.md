# Instructions for the web (cloud) Claude Code session: Microsoft Store (MSIX) and winget

Written 2026-11-07 on the owner's PC. Read `AGENTS.md`, `docs/WEB_CLAUDE_TASKS.md` §1 (the rules: they all still
apply) and `docs/HANDOFF.md` §6 first.

## Why
- An unsigned `ChutkuSetup.exe` downloaded from the web shows SmartScreen's "Unknown publisher / Run anyway". No
  setup or script can run before that warning; the downloaded file is checked first. The owner does not want to
  break the user's trust.
- The owner's decision (2026-11-07):
  1. **Microsoft Store (MSIX):** the Store signs the package, so the user clicks "Get" and sees no warning.
  2. **winget:** `winget install Chutku`, with no SmartScreen prompt in practice.
- `ChutkuSetup.exe` stays as a third option on the GitHub releases page, with an honest note about the warning.
- Do not try to hide or get around SmartScreen in any other way.

## W9: The MSIX package for the Microsoft Store
1. **Build the package.** `scripts/build_release.py --msix` builds `dist/Chutku-<version>-x64.msix` from the same
   staged folder as the zip:
   - `AppxManifest.xml`, generated from `installer/msix/AppxManifest.template.xml`;
   - PNG assets made by `chutku/icon.py`: Square44x44, Square150x150, Wide310x150, StoreLogo and SplashScreen, at
     scale-100 and scale-200;
   - `makeappx pack` (Windows SDK, available on `windows-latest`).

   The package identity (`Identity Name`, `Publisher`, `PublisherDisplayName`) comes from
   `installer/store_identity.json`. These are not secrets; the owner copies them from Partner Center. Until then,
   use placeholders (`Chutku.Dev`, `CN=ChutkuDev`) for CI builds.
2. **Write the manifest:**
   - `TargetDeviceFamily Windows.Desktop`, MinVersion 10.0.19041.0;
   - `Application Executable="Chutku.exe" EntryPoint="Windows.FullTrustApplication"`;
   - capabilities `runFullTrust`, `internetClient`, `microphone`;
   - extension `desktop:StartupTask`: TaskId `ChutkuStartup`, `Enabled="false"`, so the user switches it on;
   - `uap5:AppExecutionAlias` `chutku.exe`. Scheduled tasks need it, because a task cannot start an exe inside
     `WindowsApps` directly.
3. **Code changes for packaged mode.** Detect packaging with `GetCurrentPackageFullName` (kernel32) through a new
   `chutku.core.paths.is_packaged()`.
   - **Autostart** (`chutku/autostart.py`): packaged, the toggle opens `ms-settings:startupapps` and reports the
     StartupTask state; there is no scheduled task and no Run key.
   - **Everything that creates scheduled tasks:**
     - find them with `grep -rn schtasks chutku` (reminders, night shift, `task.schedule`, blueprints);
     - packaged, they call the alias `%LOCALAPPDATA%\Microsoft\WindowsApps\chutku.exe` with arguments;
     - make the `installer/launcher.cs` launcher forward `--cli <args>` to `python -m chutku.cli <args>` with no
       window.
   - **AppData:** an MSIX app's writes to `%LOCALAPPDATA%` are redirected to the package's private folder. Make sure
     `paths.home()`, the Edge app window profile (`dashboard.open_app_window`), model packs and the browser profile
     all work through that redirection. Child processes inherit the package context.
   - **Evolve's code lane** (git worktree and merge) cannot work on a read-only package. Packaged, offer only the
     phrase/routine/preference/skill lanes, and say so in its replies. Keep it working unchanged in a git checkout.
   - **Uninstall:** Windows removes the package's data with it. Say so in the user guide.
4. **Prepare the Store submission** (`installer/store/`):
   - `listing.md`: name, short and long description, features, keywords;
   - `PRIVACY.md`: the privacy policy, in plain words. It covers what stays local, what goes to the cloud brain
     (only with the user's key), the mic, phone and Telegram, and that nothing is sold.

     The Store needs a public privacy-policy URL. The owner publishes the file in `Chutku-releases`.
   - `notes_for_certification.md`. It covers:
     - why `runFullTrust` is needed: desktop automation through UI Automation, hotkeys, microphone, local model
       runtime;
     - that downloads are data only (models with SHA-256 pins);
     - that user-made skills run only after the user's typed approval and a click;
     - how a tester can try Chutku without keys: text commands, Safe mode.
5. **CI** (`package.yml` and `release.yml`):
   - build the MSIX, sign it with a **throwaway test certificate** made in the job (never committed), trust it on the
     runner, and `Add-AppxPackage`;
   - launch through the alias, check the dashboard answers, run `doctor` and one text command;
   - check a reminder's scheduled task fires through the alias; `Remove-AppxPackage`;
   - upload the **unsigned** MSIX as the Store artifact (the Store signs it), and on a tag attach it to the release.
6. **Tests:**
   - unit tests for `is_packaged()` and each packaged branch (autostart, schtasks command, Evolve lanes), using fakes;
   - the manifest template renders valid XML with the identity filled in.
7. **Owner-PC check, for the PC session afterwards:** with Developer Mode on (it already is),
   `Add-AppxPackage -Register <layout>\AppxManifest.xml` installs the loose layout without signing. Then check the
   Start menu, the startup toggle, a reminder, the mic, and uninstall.

## W10: winget (`winget install Chutku`)
1. **An offline installer:** `installer/chutku.iss` with `/DOFFLINE=1` embeds the package zip, so there is no
   download step at install time (winget's validation runs installers in a sandbox, so a self-contained installer
   is safer).
   - `release.yml` builds and publishes `ChutkuSetup-<version>-offline.exe` next to the small setup.
   - Apply the same clean-machine test to it.
2. **Manifests:** `installer/winget/` holds templates for the version, installer and defaultLocale manifests,
   following the current winget-pkgs schema. Settings:
   - `PackageIdentifier: SidVashisth.Chutku`;
   - `InstallerType: inno`, `Scope: user`;
   - `InstallerUrl` = the offline exe's URL in the releases repo;
   - `InstallerSha256` from the build;
   - the publisher, licence (MIT), short description and tags;
   - silent switches: Inno defaults, plus `/MERGETASKS=!desktopicon`.

   `scripts/winget_manifest.py <version>` fills them from the published release.
3. **Validate on the CI runner:** `winget validate --manifest <dir>`, then `winget install --manifest <dir>` (with
   `winget settings --enable LocalManifestFiles`), launch and check, then uninstall.
4. **Submission is the owner's step**, after the first public release: a PR to `microsoft/winget-pkgs` with
   `wingetcreate submit` (the owner's GitHub token). Write the exact commands in `installer/winget/SUBMIT.md`.
   Do not open PRs to Microsoft's repos yourself.

## W11: Docs
- `installer/README_PUBLIC.md` lists three ways to install, in this order:
  1. Microsoft Store ("Get", no warning);
  2. `winget install Chutku`;
  3. `ChutkuSetup.exe` ("Windows may say Unknown publisher: More info → Run anyway; this is because the app is not
     signed yet").
- Update `docs/USER_GUIDE.md` (Store uninstall removes data; turning startup on), `docs/SECURITY.md` (packaged mode)
  and `THIRD_PARTY_LICENSES.md` if anything new is shipped.
- Ledger entries and `docs/MASTER_PLAN.md` boxes (W9–W11). The handback lists what is still for the owner.

## What only the owner can do (put this list in the handback)
1. **Create a Microsoft Partner Center developer account** (individual; Microsoft has made this free for
   individuals). Reserve the app name **Chutku**. Copy *Package/Identity/Name*, *Publisher* and
   *PublisherDisplayName* into `installer/store_identity.json`.
2. **Publish `installer/store/PRIVACY.md`** in the public `Chutku-releases` repo and give its URL to Partner Center.
3. **Upload the unsigned MSIX** from the release, with screenshots, age rating and listing text, then submit.
   Microsoft's review takes a few days.
4. **After the first public release:** `wingetcreate submit …` (from `installer/winget/SUBMIT.md`), then wait for
   winget-pkgs review.
