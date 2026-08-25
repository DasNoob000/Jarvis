# First run on macOS — permissions, in order

Jarvis needs four or five separate grants, and macOS asks for them in inconsistent
ways: some appear as a prompt the first time the feature is used, others must be
switched on by hand before they will work at all. Work through this once, in order.

Paths below are for macOS 13 Ventura and later (System Settings, not the old System
Preferences). On macOS 15 Sequoia and later, "Screen Recording" is called **Screen &
System Audio Recording**.

---

## 0. Get past Gatekeeper

The bundle is not notarised, so the first launch is refused:

> "Jarvis" can't be opened because Apple cannot check it for malicious software.

Fix it once:

1. **Right-click** (or Control-click) `Jarvis.app` in `/Applications` → **Open** →
   **Open** in the dialog. Double-clicking will not offer this.
2. If that dialog does not appear: **System Settings → Privacy & Security**, scroll to
   the bottom, and click **Open Anyway** next to the message about Jarvis.

If you copied the `.app` from another machine or a disk image, strip the quarantine
flag first:

```bash
xattr -dr com.apple.quarantine /Applications/Jarvis.app
```

### Sign it, or you will do this repeatedly

macOS keys every permission grant to the app's code signature. An unsigned bundle gets
a new identity on every rebuild, so **your grants silently stop applying and Jarvis
appears to lose permissions for no reason**. An ad-hoc signature is free and fixes it:

```bash
codesign --force --deep --sign - /Applications/Jarvis.app
```

Run this after every rebuild. If you have a Developer ID certificate, use that instead
and the grants persist properly.

---

## 1. Microphone — required

**Prompted automatically.** The first time Jarvis opens the mic you get a dialog
quoting the reason string from `Info.plist`.

- Click **Allow**.
- If you clicked Don't Allow, or no dialog appeared:
  **System Settings → Privacy & Security → Microphone** → switch **Jarvis** on.

Without this, wake and speech recognition do nothing at all.

---

## 2. Speech Recognition — required only if you switch to Apple's STT

**Prompted automatically**, if ever.

Jarvis transcribes locally with Whisper by default, which needs no permission — audio
never leaves the Mac. This grant only comes into play if you set `stt.backend` to an
Apple Speech framework backend later. The `Info.plist` key is declared now so that
switching does not require a rebuild.

- **System Settings → Privacy & Security → Speech Recognition** → **Jarvis** on.

---

## 3. Screen Recording — required for "what's on my screen"

**Must be granted by hand. There is no `Info.plist` key for this one** — macOS writes
the prompt itself, and there is no way to explain the request in your own words.

1. Use the menu-bar item once (or ask Jarvis about your screen). macOS shows a prompt.
2. **System Settings → Privacy & Security → Screen & System Audio Recording**
   (called **Screen Recording** before macOS 15) → switch **Jarvis** on.
3. **Quit and relaunch Jarvis.** This grant does not take effect in a running process;
   macOS may offer a "Quit & Reopen" button, which does the same thing.

Symptom of a missing grant: screenshots come back showing only your wallpaper, with
every window absent. Jarvis checks for this with `CGPreflightScreenCaptureAccess` and
refuses rather than sending a useless image to the model.

---

## 4. Automation (Apple Events) — required to control other apps

**Prompted per-application, on first use.** The first time Jarvis asks Safari to do
something, you get a dialog naming both apps. Every new target app prompts again.

- Click **OK**.
- To review or repair: **System Settings → Privacy & Security → Automation** → expand
  **Jarvis** → tick each app it may control.

Denying one here is sticky and there is no re-prompt; you have to come back to this
panel to undo it.

Note that Jarvis ships with `actions.allow_automation = false`. Narrow, named actions
(open an app, open a URL) work regardless; the general AppleScript escape hatch stays
off until you enable it in config.

---

## 5. Accessibility — not needed yet

**Must be granted by hand; no `Info.plist` key, no prompt.**

Nothing in Jarvis needs this today. It becomes relevant if you later want it to click
buttons or read UI elements in other applications.

- **System Settings → Privacy & Security → Accessibility** → **+** → choose
  `/Applications/Jarvis.app` → switch it on.

---

## 6. Start at Login

Use the **Start at Login** item in the Jarvis menu. It writes
`~/Library/LaunchAgents/de.home-martin.jarvis.plist` and registers it with `launchctl`.
No Terminal required, and no use of the deprecated Login Items API.

Verify:

```bash
launchctl print gui/$UID/de.home-martin.jarvis
```

See `launchagent.plist.template` for exactly what gets written.

---

## Checking what you have granted

TCC decisions live in a database you can read but should not edit:

```bash
sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \
  "select service, client, auth_value from access where client like '%jarvis%';"
```

`auth_value` is 0 = denied, 2 = allowed. Reading it may itself require Full Disk Access
for your terminal.

To start completely fresh — useful when a rebuild has confused things:

```bash
tccutil reset All de.home-martin.jarvis
```

Every prompt then reappears on next launch.

---

## When something does not work

| Symptom | Cause |
|---|---|
| Crashes instantly on first mic use, no dialog | A usage-description key is missing from `Info.plist`. macOS kills rather than prompts. |
| Screenshots show only the wallpaper | Screen Recording not granted, or granted but the app was not relaunched. |
| Permissions worked, then stopped after a rebuild | Unsigned bundle changed identity. Ad-hoc sign it (section 0). |
| Prompts name your terminal, not Jarvis | You are running from source. Permissions attach to the host process; build the `.app`. |
| "Start at Login" does nothing at login | Check `~/Library/Logs/Jarvis/launchagent.err.log`. |
