# Settings

The Settings panel says where the app reads and writes its files, and how it looks.
Every change is saved and kept across restarts. Changes to folders take effect at
once: the other panels re-read their file lists.

## File locations

* **Results directory**: where results go. Measurements are written to its
  `measurements` sub-folder and analysis reports to its `analysis` sub-folder. The
  default is `results`, relative to the folder the app was started in; set an
  absolute path to keep all results in one place no matter how the app is started.
* **Analysis presets**: where [presets](analysis.md#presets) are stored and looked
  for (sub-folders included). The default is `analysis_presets` in the app data
  folder. Point it at a shared or version-controlled folder to share acceptance
  criteria within a team.

Type a path and press **Apply** (or Enter), or use **Browse…**. **Reset to default**
resets that one folder only. The lines below show the full paths the app actually
uses.

## Appearance

* **Theme**: Light or Dark. Applied immediately, including the plots and the
  manual.
* **UI scale**: enlarges the whole interface, for high-resolution screens where text
  and controls are too small. 100 % follows the desktop's own scaling. It takes
  effect when the app is restarted.

## Session

With **Reopen where I left off** ticked (the default), the app remembers on exit
what you were doing and restores it on the next start:

* the window's size and position, the panel you were on, and every column divider;
* **Measurement**: the chosen measurement, its settings (including edits never used
  in a run), the device if it is still attached, and whether the file column is
  hidden;
* **Analysis**: the view, layout, connector and mapping, the result that was loaded,
  the analysis mode and preset, and the parameters as you left them, including
  a golden reference, a loopback board or the FPC tickbox you did not save as a
  preset. The result is analysed again on start;
* **Interfaces**: both views' interfaces and connectors, the split view, the
  mapping, and the marks, even if you never pressed **Save**;
* **Self-Test** and **Device Info**: the selected test, its settings and device, and
  the *Simulate* tickbox.

Anything that is gone by the next start, such as a deleted result file or an
unplugged device, is skipped and the default is used instead. **Start fresh next
time** deletes the saved session and does not save the current one when you quit,
so the next start opens with the defaults. Clear the tickbox to stop saving
sessions.

## Custom layouts / mappings

**Default location** is the folder where **Import…** puts layouts and mapping CSVs
(and where loopback-board files are looked for first). Set it like the file
locations above: type a path and press **Apply**, or **Browse…**; **Reset to
default** returns to the `layouts/` folder in the app data folder. A git checkout of
your layouts is a good choice: imports then land in it, ready to commit. The folder
is created on the first import if it does not exist. Moving the default location
does not move the files already in the old one; add the old folder below if you
still want its layouts listed. When `TRAP_TESTER_LAYOUTS_DIR` is set, it decides the
default location and the field cannot be edited.

The folders searched for [custom layouts and mapping CSVs](layouts.md), including
their sub-folders:

* the **default location**, listed first; it cannot be removed;
* folders from the `TRAP_TESTER_LAYOUT_PATH` environment variable, if set;
* folders you added with **Add folder…**. Select one and press **Remove** to stop
  searching it.

The app only reads from the extra folders and never writes to them, so a git checkout
of your layouts can be added safely: pull, and the new layouts appear. The
**Folders…** buttons in the Analysis and Interfaces panels edit the same list.

## The app data folder

The settings themselves, the saved session, the default layout location and the
default presets folder live in one per-user folder. It stays put when you move the
default location or the presets folder:

| System | App data folder |
| --- | --- |
| Linux | `~/.local/share/trap-tester` (or `$XDG_DATA_HOME/trap-tester`) |
| macOS | `~/Library/Application Support/trap-tester` |
| Windows | `%APPDATA%\trap-tester` |

| File or folder | Contents |
| --- | --- |
| `app_config.json` | Results and presets folders, theme, UI scale. |
| `layout_sources.json` | The default location for layouts, if changed, and the extra layout folders you added. |
| `session.json` | The last session. Safe to delete at any time. |
| `layouts/` | The default location for layouts and mappings, unless moved. |
| `analysis_presets/` | Presets, unless moved. |

## Environment variables

| Variable | Effect |
| --- | --- |
| `TRAP_TESTER_LAYOUTS_DIR` | Sets the default location for layouts and mappings (overriding the Settings tab), and with it the whole app data folder (its parent). Useful for a shared machine or for tests. |
| `TRAP_TESTER_LAYOUT_PATH` | Extra layout folders to search, separated by `:` on Linux and macOS and `;` on Windows. |
| `QT_SCALE_FACTOR` | Overrides the UI scale setting, for example `QT_SCALE_FACTOR=2`. |
