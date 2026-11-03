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

## Custom layouts / mappings

The folders searched for [custom layouts and mapping CSVs](layouts.md), including
their sub-folders:

* the **writable store**, where **Import…** puts files; it is listed first and cannot
  be removed;
* folders from the `TRAP_TESTER_LAYOUT_PATH` environment variable, if set;
* folders you added with **Add folder…**. Select one and press **Remove** to stop
  searching it.

The app only reads from the extra folders and never writes to them, so a git checkout
of your layouts can be added safely: pull, and the new layouts appear. The
**Folders…** buttons in the Analysis and Interfaces panels edit the same list.

## The app data folder

The settings themselves, the writable layout store and the default presets folder
live in one per-user folder:

| System | App data folder |
| --- | --- |
| Linux | `~/.local/share/trap-tester` (or `$XDG_DATA_HOME/trap-tester`) |
| macOS | `~/Library/Application Support/trap-tester` |
| Windows | `%APPDATA%\trap-tester` |

| File or folder | Contents |
| --- | --- |
| `app_config.json` | Results and presets folders, theme, UI scale. |
| `layout_sources.json` | The extra layout folders you added. |
| `layouts/` | The writable layout store. |
| `analysis_presets/` | Presets, unless moved. |

## Environment variables

| Variable | Effect |
| --- | --- |
| `TRAP_TESTER_LAYOUTS_DIR` | Moves the writable layout store, and with it the whole app data folder (its parent). Useful for a shared machine or for tests. |
| `TRAP_TESTER_LAYOUT_PATH` | Extra layout folders to search, separated by `:` on Linux and macOS and `;` on Windows. |
| `QT_SCALE_FACTOR` | Overrides the UI scale setting, for example `QT_SCALE_FACTOR=2`. |
