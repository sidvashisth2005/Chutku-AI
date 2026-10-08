# Windows Settings — feature map (App Mastery A0)

Sources (local copies in `data/apps/settings/sources/`): [Launch Windows Settings — ms-settings URI reference (official)](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings) (**219 URIs** extracted) · [Keyboard shortcuts in Windows (official)](https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec). Existing tools that already *change* settings with read-back: `audio.volume`, `audio.set_output`, `display.brightness`, `settings.theme_set/restore`, `desktop.wallpaper_set`, `network.adapter_set`, `power.schedule`, `system.lock`.

## Ways in
- **URI:** `ms-settings:<page>` opens a page directly (Win+I opens Settings home). Opening a page is always **safe**; changing a toggle on it is **changes**.
- **Quick settings:** Win+A (Wi-Fi, Bluetooth, airplane, battery saver, night light, focus); notifications Win+N.

## Page map (most useful of the 219)
| Area | URIs |
|---|---|
| System | `display` · `display-advanced` · `nightlight` · `sound` · `sound-devices` · `apps-volume` · `notifications` · `quiethours` (focus/DND) · `powersleep` · `batterysaver` · `batterysaver-usagedetails` · `storagesense` · `storagerecommendations` · `multitasking` · `clipboard` · `project` · `remotedesktop` · `about` · `troubleshoot` · `recovery` |
| Devices | `bluetooth` · `connecteddevices` · `printers` · `mousetouchpad` · `devices-touchpad` · `typing` · `pen` · `autoplay` · `usb` · `mobile-devices` · `camera` |
| Network | `network-status` · `network-wifi` · `network-ethernet` · `network-mobilehotspot` · `network-airplanemode` · `network-vpn` · `network-proxy` · `network-advancedsettings` |
| Personalisation | `personalization-background` · `colors` · `themes` · `lockscreen` · `personalization-start` · `taskbar` · `fonts` |
| Apps | `appsfeatures` · `defaultapps` · `defaultbrowsersettings` · `startupapps` · `optionalfeatures` · `appsforwebsites` · `videoplayback` |
| Accounts | `yourinfo` · `signinoptions` · `emailandaccounts` · `sync` · `backup` · `otherusers` |
| Time & language | `dateandtime` · `regionlanguage` · `regionformatting` · `keyboard` · `speech` |
| Gaming | `gaming-gamebar` · `gaming-gamemode` · `gaming-gamedvr` |
| Accessibility | `easeofaccess-display` · `easeofaccess-mousepointer` · `easeofaccess-magnifier` · `easeofaccess-colorfilter` · `easeofaccess-narrator` · `easeofaccess-closedcaptioning` · `easeofaccess-keyboard` |
| Privacy & security | `privacy` · `privacy-microphone` · `privacy-webcam` · `privacy-location` · `privacy-notifications` · `privacy-backgroundapps` · `windowsdefender` · `findmydevice` |
| Update | `windowsupdate` · `windowsupdate-history` · `windowsupdate-options` · `windowsupdate-activehours` · `delivery-optimization` |

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open_page(name) | any of the 219 pages by everyday name ("bluetooth settings kholo") | `ms-settings:` | safe | Settings window title/landmark |
| bluetooth_on / off | toggle | quick settings / page toggle (UIA "Bluetooth" switch) | changes (undo: toggle back) | toggle state |
| wifi_on / off | toggle | existing `network.adapter_set` (R4, asks) or page toggle | changes / R4 | `network.status` |
| night_light_on / off | toggle | page toggle | changes | toggle state |
| focus_on(minutes) / dnd_on / off | focus session / DND | quick settings / page | changes | toggle state |
| battery_saver_on / off | toggle | page | changes | toggle state |
| display_scale(%) / resolution | display | page dropdown | changes (undo: previous) | value OCR |
| default_browser_page | open "Default apps" for Brave | `defaultapps` | safe (changing default: changes, asks once) | — |
| startup_apps_list / toggle(app) | startup apps | `startupapps` page | safe / changes | toggle state |
| storage_sense_run | clean temp | page "Run Storage Sense now" | changes (deletes temp files → asks) | freed GB |
| notifications_app(app, on/off) | per-app notifications | `notifications` page | changes | toggle state |
| windows_update_check | check updates | `windowsupdate` → "Check for updates" | safe | status text |
| volume / output device / brightness / theme / wallpaper / lock | — | existing tools | as registered | existing read-back |

**New ideas:** "padhai mode" = DND + night light + battery saver off; "presentation mode" = DND + brightness 100 + volume 0; "ye kaunsi setting kahan hai" → `app.howto("settings", …)` answering with the exact page + opening it.
