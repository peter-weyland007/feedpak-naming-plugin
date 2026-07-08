# Feedpak Naming Plugin

A Feedback plugin for previewing and applying naming rules to `.feedpak` files.

## At a glance
- preview rename results before changing anything
- use variables like `{artist}`, `{title}`, `{album}`, `{year}`, `{input_name}`
- create flat filenames like `{artist}_{title}.feedpak`
- create artist/title folder layouts like `{artist}/{title}.feedpak`
- save reusable presets
- store a default rule and optionally run it later from one backend route

## Demo
### Example flow
1. Open the **Naming** plugin in Feedback.
2. Pick a preset or type a rule such as `{artist}/{title}.feedpak`.
3. Click **Preview** to see current name → new name for every `.feedpak` file.
4. If there are no conflicts, click **Apply**.
5. Optional: save that rule as the default and use **Run saved default now** later.

### Screenshot
![Feedpak Naming demo](assets/demo-preview.svg)

### Example rename results
- `Paramore_Hallelujah_v1_DD_p.feedpak` → `Paramore/Hallelujah.feedpak`
- `Weezer_Hold-Me_v1_DD_p.feedpak` → `Weezer/Hold Me.feedpak`
- `Toadies_Tyler_v1_DD_p.feedpak` → `Toadies/Tyler.feedpak`

## Install
1. Download this repo or the release zip from the Releases page.
2. Copy the `feedpak_naming` folder into your Feedback `plugins` folder.
3. Confirm you end up with this exact shape:

```text
<feedback-root>/plugins/feedpak_naming/plugin.json
```

4. Reload or restart Feedback.
5. Open the **Naming** plugin inside Feedback.

## Plugin folder contents
```text
feedpak_naming/
  plugin.json
  routes.py
  screen.html
  screen.js
```

## Template variables
- `{artist}`
- `{title}`
- `{album}`
- `{year}`
- `{input_name}`

## Example templates
- `{artist}_{title}.feedpak`
- `{title}_{artist}.feedpak`
- `{artist}/{title}.feedpak`
- `{year}_{artist}_{title}.feedpak`

## Behavior notes
- The plugin only creates subfolders when your template includes `/`.
- The preview blocks apply when naming conflicts are detected.
- Saved defaults and presets are stored by the plugin backend in Feedback's config area.
- The backend exposes a default-run route for future import/conversion hookups.

## Repo layout
```text
feedpak-naming-plugin/
  README.md
  LICENSE
  assets/
    demo-preview.svg
  feedpak_naming/
    plugin.json
    routes.py
    screen.html
    screen.js
```

## Development verification
Verified with:
- `pytest tests/test_feedpak_naming_plugin.py -q`
- `python -m py_compile plugins/feedpak_naming/routes.py`
- `node --check plugins/feedpak_naming/screen.js`
