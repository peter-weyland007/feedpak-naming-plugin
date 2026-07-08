(function () {
    'use strict';

    const state = window.__feedBackFeedpakNaming || (window.__feedBackFeedpakNaming = {});
    state.render = render;
    if (state.installed) return;
    state.installed = true;

    const API = '/api/plugins/feedpak_naming';
    const DEFAULT_TEMPLATE = '{artist}_{title}.feedpak';
    state.settings = state.settings || null;
    state.preview = state.preview || null;

    function $(id) { return document.getElementById(id); }

    function esc(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    async function api(path, options) {
        const res = await fetch(API + path, options || {});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Request failed');
        return data;
    }

    function setStatus(message, tone) {
        const el = $('feedpak-naming-status');
        if (!el) return;
        el.textContent = message || '';
        el.className = tone === 'error' ? 'text-xs text-red-400' : 'text-xs text-gray-400';
    }

    function setSummary(text) {
        const el = $('feedpak-naming-summary');
        if (!el) return;
        el.textContent = text || '';
    }

    function statusBadge(status) {
        const map = {
            rename: 'bg-blue-500/15 text-blue-300 border-blue-700/50',
            unchanged: 'bg-dark-600 text-gray-300 border-dark-300',
            conflict: 'bg-red-500/15 text-red-300 border-red-700/50',
        };
        const cls = map[status] || map.unchanged;
        return '<span class="inline-flex rounded-full border px-2 py-1 text-xs ' + cls + '">' + esc(status) + '</span>';
    }

    function templateInput() { return $('feedpak-naming-template'); }
    function presetSelect() { return $('feedpak-naming-preset'); }

    function currentTemplate() {
        const input = templateInput();
        return (input && input.value.trim()) || DEFAULT_TEMPLATE;
    }

    function currentPresets() {
        return (state.settings && Array.isArray(state.settings.presets) ? state.settings.presets : []).slice();
    }

    function renderPresetOptions() {
        const select = presetSelect();
        if (!select) return;
        const presets = currentPresets();
        const current = currentTemplate();
        select.innerHTML = presets.map(function (preset, index) {
            const selected = preset.template === current ? ' selected' : '';
            return '<option value="' + String(index) + '"' + selected + '>' + esc(preset.name) + '</option>';
        }).join('');
        if (!presets.length) {
            select.innerHTML = '<option value="">No presets saved</option>';
        }
    }

    function selectedPreset() {
        const select = presetSelect();
        const presets = currentPresets();
        if (!select || !presets.length) return null;
        const index = Number(select.value);
        return Number.isInteger(index) && index >= 0 && index < presets.length ? presets[index] : presets[0];
    }

    function syncPresetNameFromSelection() {
        const input = $('feedpak-naming-preset-name');
        const preset = selectedPreset();
        if (input && preset) input.value = preset.name || '';
    }

    function renderPreview(preview) {
        const body = $('feedpak-naming-results');
        if (!body) return;
        const items = Array.isArray(preview && preview.items) ? preview.items : [];
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="5" class="px-4 py-6 text-center text-sm text-gray-500">No .feedpak files were found.</td></tr>';
            return;
        }
        body.innerHTML = items.map(function (item) {
            return '<tr>' +
                '<td class="px-4 py-3">' + statusBadge(item.status) + '</td>' +
                '<td class="px-4 py-3">' + esc(item.artist || '') + '</td>' +
                '<td class="px-4 py-3">' + esc(item.title || '') + '</td>' +
                '<td class="px-4 py-3 font-mono text-xs text-gray-400">' + esc(item.current_relative_path || '') + '</td>' +
                '<td class="px-4 py-3 font-mono text-xs text-gray-200">' + esc(item.proposed_relative_path || '') + (item.error ? '<div class="mt-1 text-red-400">' + esc(item.error) + '</div>' : '') + '</td>' +
                '</tr>';
        }).join('');
    }

    async function loadSettings() {
        setStatus('Loading settings…');
        const settings = await api('/settings');
        state.settings = settings;
        if (templateInput()) templateInput().value = settings.default_template || DEFAULT_TEMPLATE;
        if ($('feedpak-naming-auto-apply')) $('feedpak-naming-auto-apply').checked = !!settings.auto_apply_after_import;
        renderPresetOptions();
        syncPresetNameFromSelection();
        setStatus('Ready.');
    }

    async function saveSettings(extra) {
        const payload = {
            default_template: currentTemplate(),
            auto_apply_after_import: !!($('feedpak-naming-auto-apply') && $('feedpak-naming-auto-apply').checked),
            presets: currentPresets(),
        };
        if (extra) {
            Object.keys(extra).forEach(function (key) { payload[key] = extra[key]; });
        }
        const settings = await api('/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        state.settings = settings;
        renderPresetOptions();
        syncPresetNameFromSelection();
        return settings;
    }

    async function runPreview() {
        const template = currentTemplate();
        setStatus('Building preview…');
        try {
            const preview = await api('/preview?template=' + encodeURIComponent(template));
            state.preview = preview;
            renderPreview(preview);
            setSummary(preview.rename_count + ' rename, ' + preview.unchanged_count + ' unchanged, ' + preview.conflict_count + ' conflicts');
            setStatus(preview.conflict_count ? 'Preview has conflicts. Fix the template before applying.' : 'Preview ready.');
        } catch (err) {
            setStatus('Preview failed: ' + err.message, 'error');
        }
    }

    async function applyTemplate() {
        const template = currentTemplate();
        setStatus('Applying renames…');
        try {
            const result = await api('/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ template: template }),
            });
            setStatus('Applied ' + result.renamed_count + ' renames.');
            await runPreview();
        } catch (err) {
            setStatus('Apply failed: ' + err.message, 'error');
        }
    }

    async function runDefault() {
        setStatus('Running saved default…');
        try {
            const result = await api('/run-default', { method: 'POST' });
            if (result && result.enabled === false) {
                setStatus(result.message || 'Auto-apply is disabled.', 'error');
                return;
            }
            setStatus('Applied ' + result.renamed_count + ' renames using the saved default.');
            await runPreview();
        } catch (err) {
            setStatus('Run default failed: ' + err.message, 'error');
        }
    }

    async function savePreset() {
        const nameInput = $('feedpak-naming-preset-name');
        const template = currentTemplate();
        const name = (nameInput && nameInput.value.trim()) || 'Preset';
        const presets = currentPresets();
        const existingIndex = presets.findIndex(function (preset) { return preset.name === name; });
        const nextPreset = { name: name, template: template };
        if (existingIndex >= 0) presets[existingIndex] = nextPreset;
        else presets.push(nextPreset);
        setStatus('Saving preset…');
        try {
            await saveSettings({ presets: presets });
            renderPresetOptions();
            const select = presetSelect();
            if (select) select.value = String(Math.max(0, presets.findIndex(function (preset) { return preset.name === name; })));
            setStatus('Preset saved.');
        } catch (err) {
            setStatus('Save preset failed: ' + err.message, 'error');
        }
    }

    async function deletePreset() {
        const preset = selectedPreset();
        if (!preset) {
            setStatus('No preset selected.', 'error');
            return;
        }
        const presets = currentPresets().filter(function (item) { return !(item.name === preset.name && item.template === preset.template); });
        setStatus('Deleting preset…');
        try {
            await saveSettings({ presets: presets });
            renderPresetOptions();
            const first = selectedPreset();
            if (first && templateInput()) templateInput().value = first.template;
            syncPresetNameFromSelection();
            setStatus('Preset deleted.');
        } catch (err) {
            setStatus('Delete preset failed: ' + err.message, 'error');
        }
    }

    async function saveDefaults() {
        setStatus('Saving defaults…');
        try {
            await saveSettings();
            setStatus('Defaults saved.');
        } catch (err) {
            setStatus('Save defaults failed: ' + err.message, 'error');
        }
    }

    function bind() {
        const previewBtn = $('feedpak-naming-preview');
        const applyBtn = $('feedpak-naming-apply');
        const runDefaultBtn = $('feedpak-naming-run-default');
        const savePresetBtn = $('feedpak-naming-save-preset');
        const deletePresetBtn = $('feedpak-naming-delete-preset');
        const saveSettingsBtn = $('feedpak-naming-save-settings');
        const input = templateInput();
        const select = presetSelect();

        if (input && !input.dataset.bound) {
            input.dataset.bound = '1';
            input.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    runPreview();
                }
            });
        }
        if (select && !select.dataset.bound) {
            select.dataset.bound = '1';
            select.addEventListener('change', function () {
                const preset = selectedPreset();
                if (preset && input) input.value = preset.template || DEFAULT_TEMPLATE;
                syncPresetNameFromSelection();
            });
        }
        if (previewBtn && !previewBtn.dataset.bound) { previewBtn.dataset.bound = '1'; previewBtn.addEventListener('click', runPreview); }
        if (applyBtn && !applyBtn.dataset.bound) { applyBtn.dataset.bound = '1'; applyBtn.addEventListener('click', applyTemplate); }
        if (runDefaultBtn && !runDefaultBtn.dataset.bound) { runDefaultBtn.dataset.bound = '1'; runDefaultBtn.addEventListener('click', runDefault); }
        if (savePresetBtn && !savePresetBtn.dataset.bound) { savePresetBtn.dataset.bound = '1'; savePresetBtn.addEventListener('click', savePreset); }
        if (deletePresetBtn && !deletePresetBtn.dataset.bound) { deletePresetBtn.dataset.bound = '1'; deletePresetBtn.addEventListener('click', deletePreset); }
        if (saveSettingsBtn && !saveSettingsBtn.dataset.bound) { saveSettingsBtn.dataset.bound = '1'; saveSettingsBtn.addEventListener('click', saveDefaults); }
    }

    async function render() {
        bind();
        try {
            await loadSettings();
        } catch (err) {
            setStatus('Load failed: ' + err.message, 'error');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', render, { once: true });
    } else {
        render();
    }
})();
