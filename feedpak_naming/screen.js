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
    state.selectedPaths = state.selectedPaths instanceof Set ? state.selectedPaths : new Set();

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
            excluded: 'bg-amber-500/15 text-amber-300 border-amber-700/50',
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

    function actionableItems(preview) {
        const items = Array.isArray(preview && preview.items) ? preview.items : [];
        return items.filter(function (item) { return !!item.actionable; });
    }

    function resetSelection(preview) {
        state.selectedPaths = new Set(actionableItems(preview).map(function (item) {
            return item.current_relative_path;
        }));
    }

    function setSelectionFromItems(items) {
        state.selectedPaths = new Set(items.map(function (item) { return item.current_relative_path; }));
    }

    function derivePreview(preview) {
        const items = Array.isArray(preview && preview.items) ? preview.items : [];
        const selectedCurrent = new Set();
        const selectedTargetCounts = Object.create(null);

        items.forEach(function (item) {
            if (!item.actionable) return;
            if (state.selectedPaths.has(item.current_relative_path)) {
                selectedCurrent.add(item.current_relative_path);
                selectedTargetCounts[item.proposed_relative_path] = (selectedTargetCounts[item.proposed_relative_path] || 0) + 1;
            }
        });

        const derivedItems = [];
        let renameCount = 0;
        let unchangedCount = 0;
        let conflictCount = 0;
        let excludedCount = 0;
        let selectedCount = 0;

        items.forEach(function (item) {
            const selected = !!item.actionable && state.selectedPaths.has(item.current_relative_path);
            let status = 'unchanged';
            let error = null;
            if (!item.actionable) {
                unchangedCount += 1;
            } else if (!selected) {
                status = 'excluded';
                excludedCount += 1;
            } else {
                selectedCount += 1;
                if ((selectedTargetCounts[item.proposed_relative_path] || 0) > 1) {
                    status = 'conflict';
                    error = 'Another selected file would get the same name.';
                    conflictCount += 1;
                } else if (item.target_exists && !selectedCurrent.has(item.proposed_relative_path)) {
                    status = 'conflict';
                    error = 'A file with that name already exists.';
                    conflictCount += 1;
                } else {
                    status = 'rename';
                    renameCount += 1;
                }
            }
            derivedItems.push(Object.assign({}, item, {
                selected: selected,
                selectable: !!item.actionable,
                effectiveStatus: status,
                effectiveError: error,
            }));
        });

        return {
            items: derivedItems,
            renameCount: renameCount,
            unchangedCount: unchangedCount,
            conflictCount: conflictCount,
            excludedCount: excludedCount,
            selectedCount: selectedCount,
        };
    }

    function updateSummary(derived) {
        setSummary(
            derived.renameCount + ' selected rename, ' +
            derived.excludedCount + ' excluded, ' +
            derived.conflictCount + ' conflicts, ' +
            derived.unchangedCount + ' unchanged'
        );
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

    function bindPreviewSelectionRows() {
        const boxes = document.querySelectorAll('[data-feedpak-row-check]');
        boxes.forEach(function (box) {
            if (box.dataset.bound) return;
            box.dataset.bound = '1';
            box.addEventListener('change', function () {
                const path = box.getAttribute('data-path') || '';
                if (!path) return;
                if (box.checked) state.selectedPaths.add(path);
                else state.selectedPaths.delete(path);
                renderPreview(state.preview);
            });
        });
    }

    function renderPreview(preview) {
        const body = $('feedpak-naming-results');
        if (!body) return;
        const items = Array.isArray(preview && preview.items) ? preview.items : [];
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="6" class="px-4 py-6 text-center text-sm text-gray-500">No .feedpak files were found.</td></tr>';
            updateSummary({ renameCount: 0, excludedCount: 0, conflictCount: 0, unchangedCount: 0 });
            return;
        }
        const derived = derivePreview(preview);
        body.innerHTML = derived.items.map(function (item) {
            const check = item.selectable
                ? '<input type="checkbox" data-feedpak-row-check="1" data-path="' + esc(item.current_relative_path) + '" class="h-4 w-4 rounded border-dark-300 bg-dark-800 text-blue-500 focus:ring-blue-500"' + (item.selected ? ' checked' : '') + ' />'
                : '<span class="text-xs text-gray-500">—</span>';
            return '<tr>' +
                '<td class="px-4 py-3">' + check + '</td>' +
                '<td class="px-4 py-3">' + statusBadge(item.effectiveStatus) + '</td>' +
                '<td class="px-4 py-3">' + esc(item.artist || '') + '</td>' +
                '<td class="px-4 py-3">' + esc(item.title || '') + '</td>' +
                '<td class="px-4 py-3 font-mono text-xs text-gray-400">' + esc(item.current_relative_path || '') + '</td>' +
                '<td class="px-4 py-3 font-mono text-xs text-gray-200">' + esc(item.proposed_relative_path || '') + (item.effectiveError ? '<div class="mt-1 text-red-400">' + esc(item.effectiveError) + '</div>' : '') + '</td>' +
                '</tr>';
        }).join('');
        bindPreviewSelectionRows();
        updateSummary(derived);
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
            resetSelection(preview);
            renderPreview(preview);
            const derived = derivePreview(preview);
            setStatus(derived.conflictCount ? 'Preview ready. Uncheck any rows you want to exclude before applying.' : 'Preview ready.');
        } catch (err) {
            setStatus('Preview failed: ' + err.message, 'error');
        }
    }

    async function applyTemplate() {
        if (!state.preview) {
            setStatus('Run a preview first.', 'error');
            return;
        }
        const template = currentTemplate();
        const derived = derivePreview(state.preview);
        const selectedPaths = derived.items.filter(function (item) {
            return item.selected;
        }).map(function (item) {
            return item.current_relative_path;
        });
        if (!selectedPaths.length) {
            setStatus('Nothing is selected.', 'error');
            return;
        }
        setStatus('Applying selected renames…');
        try {
            const result = await api('/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ template: template, selected_current_paths: selectedPaths }),
            });
            setStatus('Applied ' + result.renamed_count + ' renames from ' + result.selected_count + ' selected rows.');
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
        const selectAllBtn = $('feedpak-naming-select-all');
        const selectReadyBtn = $('feedpak-naming-select-ready');
        const clearSelectionBtn = $('feedpak-naming-clear-selection');
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
        if (selectAllBtn && !selectAllBtn.dataset.bound) {
            selectAllBtn.dataset.bound = '1';
            selectAllBtn.addEventListener('click', function () {
                if (!state.preview) return;
                setSelectionFromItems(actionableItems(state.preview));
                renderPreview(state.preview);
            });
        }
        if (selectReadyBtn && !selectReadyBtn.dataset.bound) {
            selectReadyBtn.dataset.bound = '1';
            selectReadyBtn.addEventListener('click', function () {
                if (!state.preview) return;
                const derived = derivePreview(state.preview);
                setSelectionFromItems(derived.items.filter(function (item) { return item.effectiveStatus === 'rename'; }));
                renderPreview(state.preview);
            });
        }
        if (clearSelectionBtn && !clearSelectionBtn.dataset.bound) {
            clearSelectionBtn.dataset.bound = '1';
            clearSelectionBtn.addEventListener('click', function () {
                state.selectedPaths = new Set();
                if (state.preview) renderPreview(state.preview);
            });
        }
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
