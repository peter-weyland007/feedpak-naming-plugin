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
        const text = await res.text();
        let data = {};
        if (text) {
            try {
                data = JSON.parse(text);
            } catch (_err) {
                data = { error: text };
            }
        }
        if (!res.ok) throw new Error(data.error || ('Request failed (' + res.status + ')'));
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

    function duplicateHandlingValue() {
        const select = $('feedpak-naming-duplicate-handling');
        const value = select && select.value ? select.value : (state.settings && state.settings.duplicate_handling);
        return value || 'stop';
    }

    function duplicateHandlingLabel(mode) {
        return {
            stop: 'stop on conflicts',
            auto_number: 'auto-number duplicates',
            skip_conflicts: 'skip conflicting rows'
        }[mode || 'stop'] || 'stop on conflicts';
    }

    function statusBadge(status) {
        const map = {
            rename: 'bg-blue-500/15 text-blue-300 border-blue-700/50',
            unchanged: 'bg-dark-600 text-gray-300 border-dark-300',
            conflict: 'bg-red-500/15 text-red-300 border-red-700/50',
            skipped: 'bg-yellow-500/15 text-yellow-300 border-yellow-700/50',
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

    function derivePreviewState(preview, options) {
        const items = Array.isArray(preview && preview.items) ? preview.items : [];
        const selectedSet = new Set(((options && options.selectedPaths) || []).map(function (path) {
            return String(path);
        }));
        const duplicateHandling = (options && options.duplicateHandling) || 'stop';
        const selectedCurrent = new Set();
        const selectedTargetCounts = Object.create(null);

        items.forEach(function (item) {
            if (!item.actionable) return;
            if (selectedSet.has(item.current_relative_path)) {
                selectedCurrent.add(item.current_relative_path);
                selectedTargetCounts[item.proposed_relative_path] = (selectedTargetCounts[item.proposed_relative_path] || 0) + 1;
            }
        });

        const derivedItems = [];
        let renameCount = 0;
        let unchangedCount = 0;
        let conflictCount = 0;
        let excludedCount = 0;
        let skippedCount = 0;
        let selectedCount = 0;
        let autoNumberedCount = 0;

        items.forEach(function (item) {
            const selected = !!item.actionable && selectedSet.has(item.current_relative_path);
            let status = 'unchanged';
            let error = null;
            if (!item.actionable) {
                unchangedCount += 1;
            } else if (!selected) {
                status = 'excluded';
                excludedCount += 1;
            } else {
                selectedCount += 1;
                const duplicateSelectedTarget = (selectedTargetCounts[item.proposed_relative_path] || 0) > 1;
                const collidesWithExisting = item.target_exists && !selectedCurrent.has(item.proposed_relative_path);
                if (duplicateSelectedTarget || collidesWithExisting) {
                    if (duplicateHandling === 'skip_conflicts') {
                        status = 'skipped';
                        error = duplicateSelectedTarget
                            ? 'Will be skipped because another selected file would get the same name.'
                            : 'Will be skipped because a file with that name already exists.';
                        skippedCount += 1;
                    } else {
                        status = 'conflict';
                        error = duplicateSelectedTarget
                            ? 'Another selected file would get the same name.'
                            : 'A file with that name already exists.';
                        conflictCount += 1;
                    }
                } else {
                    status = 'rename';
                    renameCount += 1;
                    if (item.auto_numbered_from) autoNumberedCount += 1;
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
            skippedCount: skippedCount,
            selectedCount: selectedCount,
            autoNumberedCount: autoNumberedCount,
        };
    }

    function derivePreview(preview) {
        return derivePreviewState(preview, {
            selectedPaths: Array.from(state.selectedPaths || []),
            duplicateHandling: duplicateHandlingValue(),
        });
    }

    function updateSummary(derived) {
        var parts = [
            derived.renameCount + ' selected rename',
            derived.excludedCount + ' excluded'
        ];
        if (duplicateHandlingValue() === 'skip_conflicts') {
            parts.push((derived.skippedCount || 0) + ' skipped');
        } else {
            parts.push(derived.conflictCount + ' conflicts');
        }
        parts.push(derived.unchangedCount + ' unchanged');
        if (derived.autoNumberedCount) {
            parts.push(derived.autoNumberedCount + ' auto-numbered');
        }
        parts.push(duplicateHandlingLabel(duplicateHandlingValue()));
        setSummary(parts.join(', '));
    }

    state.__test = {
        derivePreview: derivePreviewState,
    };

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
                '<td class="px-4 py-3 font-mono text-xs text-gray-200">' + esc(item.proposed_relative_path || '') +
                    (item.auto_numbered_from ? '<div class="mt-1 text-amber-300">Auto-numbered from ' + esc(item.auto_numbered_from) + '</div>' : '') +
                    (item.effectiveError ? '<div class="mt-1 text-red-400">' + esc(item.effectiveError) + '</div>' : '') +
                '</td>' +
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
        if ($('feedpak-naming-duplicate-handling')) $('feedpak-naming-duplicate-handling').value = settings.duplicate_handling || 'stop';
        if ($('feedpak-naming-include-builtins')) $('feedpak-naming-include-builtins').checked = !!settings.include_builtin_content;
        renderPresetOptions();
        syncPresetNameFromSelection();
        setStatus('Ready.');
    }

    async function saveSettings(extra) {
        const payload = {
            default_template: currentTemplate(),
            auto_apply_after_import: !!($('feedpak-naming-auto-apply') && $('feedpak-naming-auto-apply').checked),
            duplicate_handling: duplicateHandlingValue(),
            include_builtin_content: !!($('feedpak-naming-include-builtins') && $('feedpak-naming-include-builtins').checked),
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
        const mode = duplicateHandlingValue();
        const includeBuiltins = !!($('feedpak-naming-include-builtins') && $('feedpak-naming-include-builtins').checked);
        setStatus('Building preview…');
        try {
            const preview = await api(
                '/preview?template=' + encodeURIComponent(template) +
                '&duplicate_handling=' + encodeURIComponent(mode) +
                '&include_builtin_content=' + encodeURIComponent(includeBuiltins ? 'true' : 'false')
            );
            state.preview = preview;
            state.settings = Object.assign({}, state.settings || {}, {
                duplicate_handling: preview.duplicate_handling || mode,
                auto_number_conflicts: preview.auto_number_conflicts === true,
                include_builtin_content: includeBuiltins
            });
            resetSelection(preview);
            renderPreview(preview);
            const derived = derivePreview(preview);
            const effectiveMode = preview.duplicate_handling || mode;
            setStatus(
                derived.conflictCount
                    ? (effectiveMode === 'skip_conflicts'
                        ? 'Preview ready. Conflicting rows will be skipped if you apply.'
                        : 'Preview ready. Choose how to handle the conflicts or deselect those rows before applying.')
                    : (derived.autoNumberedCount
                        ? 'Preview ready. Duplicate targets were auto-numbered.'
                        : 'Preview ready.')
            );
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
                body: JSON.stringify({
                    template: template,
                    selected_current_paths: selectedPaths,
                    duplicate_handling: duplicateHandlingValue(),
                    include_builtin_content: !!($('feedpak-naming-include-builtins') && $('feedpak-naming-include-builtins').checked)
                }),
            });
            const skipped = result.skipped_conflict_count || 0;
            setStatus(
                skipped
                    ? ('Applied ' + result.renamed_count + ' renames from ' + result.selected_count + ' selected rows. Skipped ' + skipped + ' conflicts.')
                    : ('Applied ' + result.renamed_count + ' renames from ' + result.selected_count + ' selected rows.')
            );
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

    function markPreviewStale(message) {
        if (!state.preview) return;
        setStatus(message || 'Settings changed. Run Preview again to refresh the results.');
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
        const duplicateHandling = $('feedpak-naming-duplicate-handling');
        const includeBuiltins = $('feedpak-naming-include-builtins');

        if (input && !input.dataset.bound) {
            input.dataset.bound = '1';
            input.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    runPreview();
                }
            });
            input.addEventListener('input', function () {
                markPreviewStale('Naming rule changed. Run Preview again to refresh the results.');
            });
        }
        if (select && !select.dataset.bound) {
            select.dataset.bound = '1';
            select.addEventListener('change', function () {
                const preset = selectedPreset();
                if (preset && input) input.value = preset.template || DEFAULT_TEMPLATE;
                syncPresetNameFromSelection();
                markPreviewStale('Preset changed. Run Preview again to refresh the results.');
            });
        }
        if (duplicateHandling && !duplicateHandling.dataset.bound) {
            duplicateHandling.dataset.bound = '1';
            duplicateHandling.addEventListener('change', function () {
                markPreviewStale('Duplicate handling changed. Run Preview again to refresh the results.');
            });
        }
        if (includeBuiltins && !includeBuiltins.dataset.bound) {
            includeBuiltins.dataset.bound = '1';
            includeBuiltins.addEventListener('change', function () {
                markPreviewStale('Built-in content setting changed. Run Preview again to refresh the results.');
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
