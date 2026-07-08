# Feedpak Naming Plugin

A Feedback plugin for previewing and applying naming rules to `.feedpak` files.

## What it does
- previews rename results before changing anything
- supports variables like `{artist}`, `{title}`, `{album}`, `{year}`, `{input_name}`
- supports flat names like `{artist}_{title}.feedpak`
- supports nested folder layouts like `{artist}/{title}.feedpak`
- lets you save preset naming rules
- stores a default rule and exposes a backend route to run that default later

## Install
1. Download this repo or the release zip.
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

## Example templates
- `{artist}_{title}.feedpak`
- `{title}_{artist}.feedpak`
- `{artist}/{title}.feedpak`
- `{year}_{artist}_{title}.feedpak`

## Notes
- The plugin only creates subfolders when your template includes `/`.
- It blocks apply when the preview detects naming conflicts.
- Saved defaults and presets are stored by the plugin backend in Feedback's config area.

## Development verification
Verified with:
- `pytest tests/test_feedpak_naming_plugin.py -q`
- `python -m py_compile plugins/feedpak_naming/routes.py`
- `node --check plugins/feedpak_naming/screen.js`
