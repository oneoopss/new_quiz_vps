/**
 * ai.js — модуль AI-генерации вопросов для конструктора квизов.
 *
 * Сценарий (§21): выбрать раздел → количество → сгенерировать →
 * быстро просмотреть → принять нужные → они попадают в квиз.
 *
 * Ручной сценарий конструктора не затрагивается: вопросы передаются
 * через window.QuizBuilder.addQuestion() в том же формате.
 */
(function() {
    'use strict';

    var state = {
        sections: [],
        stats: {},
        jobId: null,
        eventSource: null,
        pollTimer: null
    };

    // ---------- утилиты ----------
    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function toast(message, type) {
        var container = document.getElementById('toastContainer');
        if (!container || !window.QuizBuilder) { console.log(message); return; }
        if (window.showToast) { window.showToast(message, type || 'info'); return; }
        var t = el('div', 'toast ' + (type || 'info'), message);
        container.appendChild(t);
        setTimeout(function() { t.remove(); }, 3500);
    }

    function api(path, options) {
        options = options || {};
        if (options.body && typeof options.body !== 'string') {
            options.body = JSON.stringify(options.body);
            options.headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
        }
        return fetch(path, options).then(function(resp) {
            return resp.json().catch(function() { return {}; }).then(function(body) {
                if (!resp.ok) {
                    throw new Error(body.detail || ('Ошибка HTTP ' + resp.status));
                }
                return body;
            });
        });
    }

    function escapeText(s) {
        var div = document.createElement('div');
        div.textContent = s == null ? '' : String(s);
        return div.innerHTML;
    }

    function injectStyles() {
        var css = [
            '.ai-panel .ai-row{display:flex;gap:1rem;flex-wrap:wrap;align-items:flex-end;}',
            '.ai-panel .ai-row .form-group{flex:1;min-width:220px;margin-bottom:1rem;}',
            '.ai-panel .ai-progress{margin:1rem 0;padding:1rem;border-radius:10px;background:#f0f4ff;color:#2d3436;display:none;}',
            '.ai-panel .ai-progress.active{display:block;}',
            '.ai-panel .ai-progress-bar{height:8px;border-radius:4px;background:#dfe6e9;overflow:hidden;margin-top:.6rem;}',
            '.ai-panel .ai-progress-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#0984e3,#74b9ff);transition:width .6s ease;}',
            '.ai-panel .ai-eta{color:var(--text-secondary);font-size:.85rem;margin-top:.35rem;}',
            '.ai-categories{max-height:270px;overflow-y:auto;border:1px solid var(--border);border-radius:10px;padding:.8rem 1rem;background:#fff;}',
            '.ai-cat-group{margin-bottom:.7rem;}',
            '.ai-cat-group .ai-cat-title{font-weight:600;font-size:.88rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.4px;margin-bottom:.3rem;}',
            '.ai-cat-item{display:flex;align-items:center;gap:.55rem;padding:.18rem 0;cursor:pointer;}',
            '.ai-cat-item input{width:17px;height:17px;accent-color:var(--primary);cursor:pointer;}',
            '.ai-cat-tools{display:flex;gap:.5rem;margin:.4rem 0;}',
            '.ai-cat-tools button{padding:.35rem .8rem;font-size:.82rem;}',
            '.ai-statebox{padding:.95rem 1.15rem;border-radius:12px;margin-bottom:.9rem;font-size:.95rem;line-height:1.5;}',
            '.ai-statebox.missing{background:#f1f2f6;color:#2d3436;}',
            '.ai-statebox.preparing{background:#fff3e0;color:#6d4c41;}',
            '.ai-statebox.ready{background:#e8f8f0;color:#155724;}',
            '.ai-statebox.working{background:#e3f2fd;color:#0d47a1;}',
            '.ai-statebox.error{background:#fdecea;color:#8b1a1a;}',
            '.ai-spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.55);border-top-color:#fff;border-radius:50%;animation:aiSpin .8s linear infinite;vertical-align:-2px;margin-right:.35rem;}',
            '@keyframes aiSpin{to{transform:rotate(360deg)}}',
            '.ai-q-card.busy{opacity:.55;}',
            '.ai-secondary-link{background:none;border:none;color:var(--primary);cursor:pointer;font-size:.85rem;text-decoration:underline;padding:.15rem 0;display:block;margin-bottom:.9rem;}',
            '.ai-q-card{background:var(--bg-primary);border-radius:12px;padding:1.25rem;border-left:4px solid var(--primary);margin-bottom:1rem;}',
            '.ai-q-card.accepted{border-left-color:var(--success);opacity:.85;}',
            '.ai-q-card .ai-q-text{font-weight:600;margin-bottom:.6rem;}',
            '.ai-q-card ul.ai-q-options{margin:.4rem 0 .8rem 1.2rem;}',
            '.ai-q-card ul.ai-q-options li{margin:.2rem 0;}',
            '.ai-q-card .ai-q-correct{color:var(--success);font-weight:700;}',
            '.ai-q-card details{margin:.6rem 0;color:var(--text-secondary);font-size:.92rem;}',
            '.ai-q-card details summary{cursor:pointer;color:var(--primary);font-weight:600;}',
            '.ai-q-card blockquote{margin:.5rem 0;padding:.6rem .9rem;border-left:3px solid var(--warning);background:#fffbea;font-style:italic;}',
            '.ai-q-actions{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.8rem;}',
            '.ai-q-actions .btn{padding:.5rem .9rem;font-size:.88rem;}',
            '.ai-q-edit,.ai-q-regen{margin-top:.8rem;padding:.9rem;background:#fff;border-radius:10px;}',
            '.ai-q-edit .ai-edit-opt{display:flex;gap:.5rem;align-items:center;margin:.35rem 0;}',
            '.ai-q-edit .ai-edit-opt input[type=text]{flex:1;padding:.45rem;border:1px solid var(--border);border-radius:6px;}',
            '.ai-source-link{color:var(--primary);text-decoration:underline;}'
        ].join('\n');
        var style = document.createElement('style');
        style.textContent = css;
        document.head.appendChild(style);
    }

    // ---------- панель ----------
    var panel, categoriesBox, countInput, primaryBtn, refreshBtn, cancelBtn, progressEl, resultsEl, statusEl, stateBox;

    function buildPanel() {
        var root = document.getElementById('aiPanelRoot');
        if (!root) return;

        panel = el('div', 'card ai-panel');
        panel.appendChild(el('h2', 'card-title', '🤖 AI-генерация вопросов'));

        // Единая строка состояния: что происходит и что будет при нажатии
        stateBox = el('div', 'ai-statebox missing');
        statusEl = el('p', '', 'Загрузка данных...');
        stateBox.appendChild(statusEl);
        panel.appendChild(stateBox);

        refreshBtn = el('button', 'ai-secondary-link', 'Обновить знания выбранных категорий');
        refreshBtn.id = 'aiRefreshBtn';
        refreshBtn.type = 'button';
        panel.appendChild(refreshBtn);

        var groupSection = el('div', 'form-group');
        groupSection.appendChild(el('label', 'form-label', 'Категории (можно выбрать несколько)'));

        var tools = el('div', 'ai-cat-tools');
        var allBtn = el('button', 'btn btn-secondary', 'Выбрать всё');
        var noneBtn = el('button', 'btn btn-secondary', 'Снять всё');
        allBtn.type = 'button';
        noneBtn.type = 'button';
        allBtn.addEventListener('click', function() {
            categoriesBox.querySelectorAll('input[type=checkbox]').forEach(function(cb) { cb.checked = true; });
        });
        noneBtn.addEventListener('click', function() {
            categoriesBox.querySelectorAll('input[type=checkbox]').forEach(function(cb) { cb.checked = false; });
        });
        tools.appendChild(allBtn);
        tools.appendChild(noneBtn);
        groupSection.appendChild(tools);

        categoriesBox = el('div', 'ai-categories');
        categoriesBox.id = 'aiCategories';
        groupSection.appendChild(categoriesBox);
        panel.appendChild(groupSection);

        var groupCount = el('div', 'form-group');
        groupCount.appendChild(el('label', 'form-label', 'Количество вопросов'));
        countInput = document.createElement('input');
        countInput.type = 'number';
        countInput.id = 'aiCount';
        countInput.className = 'form-input';
        countInput.min = '1';
        countInput.max = '50';
        countInput.value = '10';
        groupCount.appendChild(countInput);
        panel.appendChild(groupCount);

        // Одна умная кнопка: «Подготовить документацию» или «Сгенерировать вопросы»
        primaryBtn = el('button', 'btn btn-primary btn-block', '📚 Подготовить документацию');
        primaryBtn.id = 'aiPrimaryBtn';
        panel.appendChild(primaryBtn);

        // Аварийная остановка всех фоновых процессов (извлечение, генерация, обновление)
        cancelBtn = el('button', 'btn btn-danger btn-block', '⏹ Остановить все процессы');
        cancelBtn.id = 'aiCancelBtn';
        cancelBtn.style.marginTop = '.6rem';
        panel.appendChild(cancelBtn);

        progressEl = el('div', 'ai-progress');
        progressEl.innerHTML = '<div class="ai-progress-text"></div><div class="ai-progress-bar"><i></i></div>';
        panel.appendChild(progressEl);

        resultsEl = el('div', 'ai-results');
        panel.appendChild(resultsEl);

        root.appendChild(panel);

        primaryBtn.addEventListener('click', onPrimary);
        refreshBtn.addEventListener('click', onRefreshKnowledge);
        cancelBtn.addEventListener('click', onCancelAll);
    }

    // ---------- категории / статус KB ----------
    function renderCategories() {
        var groups = state.groups || [];
        // Не перерисовываем список без изменений — иначе слетают галочки при долгом выборе
        var signature = JSON.stringify(groups);
        if (signature === state.groupsSignature && categoriesBox.childNodes.length) {
            return;
        }
        state.groupsSignature = signature;

        var selected = [];
        categoriesBox.querySelectorAll('input[type=checkbox]:checked').forEach(function(cb) {
            selected.push(cb.value);
        });

        categoriesBox.innerHTML = '';
        if (!groups.length) {
            categoriesBox.appendChild(el('p', 'question-preview',
                '— документация ещё не загружена —'));
            return;
        }
        groups.forEach(function(group) {
            var block = el('div', 'ai-cat-group');
            block.appendChild(el('div', 'ai-cat-title', group.title));
            (group.categories || []).forEach(function(cat) {
                var label = el('label', 'ai-cat-item');
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.value = cat.code;
                cb.dataset.title = cat.title;
                cb.checked = selected.indexOf(cat.code) >= 0;
                label.appendChild(cb);
                label.appendChild(document.createTextNode(cat.code + ' ' + cat.title));
                block.appendChild(label);
            });
            categoriesBox.appendChild(block);
        });
    }

    function selectedCategories() {
        var picked = [];
        categoriesBox.querySelectorAll('input[type=checkbox]:checked').forEach(function(cb) {
            picked.push({ code: cb.value, title: cb.dataset.title || cb.value });
        });
        return picked;
    }

    function renderStatus() {
        if (!stateBox || !primaryBtn) return;
        var st = state.stats || {};
        var docs = st.documents || 0;
        var extracted = st.extracted_documents || 0;
        var items = st.knowledge_items || 0;
        var job = state.activeJob;
        var running = job && (job.status === 'running' || job.status === 'queued');
        var kind = running ? ((job.params && job.params.type) || '') : '';
        var tone, text, action, label;

        if (running && kind === 'generate') {
            var p = job.progress || {};
            tone = 'working';
            text = 'Генерация вопросов: ' + (p.message || p.stage || 'работа...') +
                (p.eta_seconds > 0 ? ' · осталось ~' + Math.max(1, Math.round(p.eta_seconds / 60)) + ' мин' : '');
            action = 'busy';
            label = '⏳ Генерация...';
        } else if (running && (kind === 'prepare' || kind === 'ingest')) {
            tone = 'preparing';
            text = 'Подготовка документации: скачивание страниц... (один раз, около 2 минут).';
            action = 'busy';
            label = '⏳ Подготовка...';
        } else if (running && (kind === 'extract' || kind === 'refresh')) {
            var ep = job.progress || {};
            tone = 'preparing';
            text = 'Извлечение знаний: ' + (ep.message || 'обработка...') +
                '. Можно генерировать уже сейчас — знания выбранной категории извлекутся приоритетно.';
            action = 'generate';
            label = '✨ Сгенерировать вопросы';
        } else if (job && (job.status === 'failed' || job.status === 'partial' || job.status === 'cancelled')) {
            var wasGenerate = (job.params && job.params.type) === 'generate';
            tone = 'error';
            text = (job.status === 'cancelled'
                ? '⚠️ Остановлено пользователем'
                : '⚠️ ' + (wasGenerate ? 'Последняя генерация' : 'Последняя задача') +
                  ' завершилась с ошибкой: ' + (job.error || 'неизвестная ошибка')) +
                (job.result && job.result.count ? ' Готовые вопросы сохранены ниже.' : '');
            if (!docs) {
                action = 'prepare';
                label = '📚 Подготовить документацию';
            } else {
                action = 'generate';
                label = wasGenerate ? '🔁 Повторить генерацию' : '✨ Сгенерировать вопросы';
            }
        } else if (!docs) {
            tone = 'missing';
            text = 'Документация не загружена. Нажмите «Подготовить документацию» — это выполняется один раз.';
            action = 'prepare';
            label = '📚 Подготовить документацию';
        } else if (extracted < docs) {
            tone = 'ready';
            text = 'Документация готова: ' + docs + ' страниц. Знания извлечены для ' + extracted +
                ' из ' + docs + ' разделов — генерация работает и без полного извлечения.';
            action = 'generate';
            label = '✨ Сгенерировать вопросы';
        } else {
            tone = 'ready';
            text = 'Документация готова: ' + docs + ' страниц · ' + items +
                ' знаний. Выберите категории и нажмите «Сгенерировать вопросы».';
            action = 'generate';
            label = '✨ Сгенерировать вопросы';
        }

        stateBox.className = 'ai-statebox ' + tone;
        statusEl.textContent = text;
        primaryBtn.textContent = label;
        if (action !== 'busy') {
            state.primaryAction = action;
            primaryBtn.disabled = false;
        } else {
            primaryBtn.disabled = true;
        }
        if (refreshBtn) refreshBtn.style.display = docs ? 'block' : 'none';
    }

    function onPrimary() {
        if (state.primaryAction === 'prepare') {
            onPrepare();
        } else {
            onGenerate();
        }
    }

    function loadSections() {
        return api('/api/sections/categories').then(function(data) {
            state.groups = data.groups || [];
            state.stats = data.stats || {};
            renderCategories();
            renderStatus();
        }).catch(function(err) {
            statusEl.textContent = 'Не удалось связаться с backend: ' + err.message;
        });
    }

    // ---------- подготовка документации (одна кнопка, две фазы) ----------
    function onPrepare() {
        primaryBtn.disabled = true;
        showProgress('Подготовка документации: скачивание страниц...');
        api('/api/ingest/prepare', { method: 'POST' }).then(function(data) {
            trackJob(data.job_id, function() {
                hideProgress();
                toast('Документация скачана — можно генерировать', 'success');
                // Фаза 2 (фоновое извлечение знаний) запускается автоматически —
                // подхватываем её для строки состояния.
                loadSections().then(followLatestJob);
            }, function(err) {
                hideProgress();
                renderStatus();
                toast('Ошибка подготовки: ' + err, 'error');
            });
        }).catch(function(err) {
            hideProgress();
            renderStatus();
            toast(err.message, 'error');
        });
    }

    // ---------- остановка всех фоновых процессов ----------
    function onCancelAll() {
        cancelBtn.disabled = true;
        api('/api/jobs/cancel', { method: 'POST' }).then(function(res) {
            var n = (res.cancelled_job_ids || []).length;
            toast(n ? 'Процессы остановлены (' + n + ')' : 'Активных процессов не было', 'info');
            hideProgress();
            renderStatus();
            loadSections().then(followLatestJob);
        }).catch(function(err) {
            toast(err.message, 'error');
        }).then(function() {
            cancelBtn.disabled = false;
        });
    }

    function followLatestJob() {
        api('/api/jobs/latest').then(function(job) {
            if (!job || !job.id) return;
            state.activeJob = job;
            renderStatus();
            if (job.status === 'running' || job.status === 'queued') {
                trackJob(job.id, function(doneJob) {
                    state.activeJob = doneJob;
                    renderStatus();
                    loadSections();
                }, function(err) {
                    renderStatus();
                    loadSections();
                    toast('Фоновая задача завершилась с ошибкой: ' + err, 'warning');
                });
            }
        }).catch(function() { /* job-ов ещё нет */ });
    }

    // ---------- переизвлечение знаний выбранных категорий ----------
    function onRefreshKnowledge() {
        var picked = selectedCategories();
        if (!picked.length) {
            toast('Выберите категории, знания которых нужно обновить', 'warning');
            return;
        }
        if (!window.confirm('Переизвлечь знания для выбранных категорий? Это улучшит качество ' +
            'вопросов и займёт несколько минут.')) return;
        var btn = document.getElementById('aiRefreshBtn');
        btn.disabled = true;
        showProgress('Переизвлечение знаний...');
        api('/api/ingest/refresh', {
            method: 'POST',
            body: { section_codes: picked.map(function(p) { return p.code; }) }
        }).then(function(data) {
            trackJob(data.job_id, function() {
                hideProgress();
                btn.disabled = false;
                toast('Знания выбранных категорий обновлены', 'success');
                loadSections();
            }, function(err) {
                hideProgress();
                btn.disabled = false;
                toast('Ошибка обновления знаний: ' + err, 'error');
            });
        }).catch(function(err) {
            hideProgress();
            btn.disabled = false;
            toast(err.message, 'error');
        });
    }

    // ---------- генерация ----------
    function onGenerate() {
        var picked = selectedCategories();
        var count = parseInt(countInput.value, 10);
        if (!picked.length) { toast('Выберите хотя бы одну категорию', 'warning'); return; }
        if (!count || count < 1) { toast('Укажите количество вопросов', 'warning'); return; }
        if (count > 50) {
            toast('Максимум 50 вопросов за один запуск — будет сгенерировано 50', 'warning');
            count = 50;
            countInput.value = '50';
        }

        state.lastPicked = picked;
        primaryBtn.disabled = true;
        resultsEl.innerHTML = '';
        showProgress('Запуск генерации...');
        api('/api/generate', {
            method: 'POST',
            body: {
                section_codes: picked.map(function(p) { return p.code; }),
                count: count
            }
        }).then(function(data) {
            state.jobId = data.job_id;
            trackJob(data.job_id, function(job) {
                renderStatus();
                hideProgress();
                loadResults(data.job_id, job);
                toast('Вопросы готовы — добавьте их в квиз кнопкой «Добавить все» или по одному', 'info');
            }, function(err) {
                renderStatus();
                hideProgress();
                toast('Генерация не удалась: ' + err, 'error');
            });
        }).catch(function(err) {
            renderStatus();
            hideProgress();
            toast(err.message, 'error');
        });
    }

    function showProgress(text) {
        progressEl.classList.add('active');
        progressEl.querySelector('.ai-progress-text').textContent = text;
    }

    function hideProgress() {
        progressEl.classList.remove('active');
        if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
        if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
    }

    function updateProgress(progress) {
        if (!progress) return;
        var stages = {
            queued: 'В очереди...', fetch: 'Загрузка документации...',
            extract: 'Извлечение знаний...', plan: 'Планирование покрытия...',
            generate: 'Генерация вопросов...', validate: 'Проверка вопросов...',
            dedup: 'Поиск дубликатов...', critic: 'Оценка качества...',
            repair: 'Точечное исправление...', save: 'Сохранение...', done: 'Готово!'
        };
        var label = stages[progress.stage] || progress.stage || 'Работа...';
        var percent = (typeof progress.percent === 'number') ? progress.percent : null;
        var counts = '';
        if (progress.total > 1 && progress.stage !== 'plan') {
            counts = ' · ' + progress.done + ' из ' + progress.total;
        }
        var eta = '';
        if (progress.eta_seconds > 0) {
            var mins = Math.round(progress.eta_seconds / 60);
            eta = mins >= 1
                ? ' · ~' + mins + ' мин осталось'
                : ' · ~' + Math.max(progress.eta_seconds, 10) + ' сек осталось';
        }
        showProgress(label + counts + eta + (progress.message ? ' — ' + progress.message : ''));

        var bar = progressEl.querySelector('.ai-progress-bar i');
        if (bar) {
            bar.style.width = (percent !== null ? Math.max(percent, 2) : 25) + '%';
        }
    }

    function trackJob(jobId, onDone, onError) {
        var finished = false;
        var es = null;

        function finishCheck(job) {
            if (finished) return;
            state.activeJob = job;
            updateProgress(job.progress);
            renderStatus();
            if (job.status === 'completed') {
                finished = true;
                if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
                if (es) es.close();
                onDone(job);
            } else if (job.status === 'cancelled') {
                finished = true;
                if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
                if (es) es.close();
                if (job.result && job.result.count) {
                    onDone(job);  // частичные вопросы показываем как результат
                } else {
                    onError('Остановлено пользователем');
                }
            } else if (job.status === 'failed') {
                finished = true;
                if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
                if (es) es.close();
                onError(job.error || 'неизвестная ошибка');
            }
        }

        try {
            es = new EventSource('/api/jobs/' + jobId + '/stream');
            state.eventSource = es;
            es.onmessage = function(ev) {
                try { finishCheck(JSON.parse(ev.data)); } catch (e) { /* игнорируем сбой парсинга */ }
            };
            es.onerror = function() { es.close(); }; // fallback — polling ниже
        } catch (e) { /* EventSource недоступен — используем polling */ }

        state.pollTimer = setInterval(function() {
            api('/api/jobs/' + jobId).then(finishCheck).catch(function() { /* сеть моргнула */ });
        }, 2500);
        api('/api/jobs/' + jobId).then(finishCheck).catch(function() {});
    }

    // ---------- карточки результатов ----------
    function lossBreakdown(job) {
        var r = (job && job.result) || {};
        var losses = [];
        if (r.generated_raw !== undefined && r.plan_size !== undefined && r.generated_raw < r.plan_size) {
            losses.push('модель вернула ' + r.generated_raw + ' из ' + r.plan_size +
                (r.dobor_added ? ' (добор +' + r.dobor_added + ')' : ''));
        }
        if (r.batch_errors) losses.push('сбойные батчи: ' + r.batch_errors);
        if (r.dedup_dropped) {
            losses.push('дубликаты: −' + r.dedup_dropped + ' (повторный запуск даст новые вопросы)');
        }
        if (r.critic_rejected) losses.push('критик отклонил: −' + r.critic_rejected);
        if (r.repair_failed) losses.push('не починены: −' + r.repair_failed);
        return losses;
    }

    function loadResults(jobId, job) {
        api('/api/questions?job_id=' + jobId).then(function(data) {
            resultsEl.innerHTML = '';
            var questions = data.questions || [];
            var r = (job && job.result) || {};
            var requested = r.requested || r.count || questions.length;
            var note = r.note ? r.note : '';
            var catTitles = (state.lastPicked || []).map(function(p) { return p.title; });
            var header = el('h3', 'card-title',
                'Получено вопросов: ' + questions.length + ' из ' + requested +
                (catTitles.length ? ' · категории: ' + catTitles.join(', ') : ''));
            resultsEl.appendChild(header);

            if (questions.length) {
                var addAllBtn = el('button', 'btn btn-success', '✅ Добавить все в квиз');
                addAllBtn.id = 'aiAddAllBtn';
                addAllBtn.style.margin = '0 0 1rem 0';
                addAllBtn.addEventListener('click', function() { addAllToQuiz(); });
                resultsEl.appendChild(addAllBtn);
            }

            var losses = lossBreakdown(job);
            if (losses.length || note || (job && job.status === 'partial')) {
                var detail = el('p', 'question-preview');
                var parts = [];
                if (job && job.status === 'partial') {
                    parts.push('⚠️ Генерация завершилась частично (' + (job.error || 'сбой') + ') — ' +
                        'вопросы ниже сохранены.');
                }
                if (r.topup_added) {
                    parts.push('Добрано до запрошенного количества: +' + r.topup_added + '.');
                }
                if (losses.length) parts.push('Потери: ' + losses.join(' · ') + '.');
                if (note) parts.push(note);
                detail.textContent = parts.join(' ');
                detail.style.marginBottom = '1rem';
                resultsEl.appendChild(detail);
            }
            if (!questions.length) {
                resultsEl.appendChild(el('p', 'question-preview',
                    'Ни одного вопроса не прошло проверку. Попробуйте другой раздел или посмотрите логи job-а.'));
                return;
            }
            questions.forEach(function(q) {
                resultsEl.appendChild(renderQuestionCard(q));
            });
        }).catch(function(err) {
            toast(err.message, 'error');
        });
    }

    function renderQuestionCard(q) {
        var card = el('div', 'ai-q-card');
        card.dataset.id = q.id;
        card._q = q;

        var textEl = el('div', 'ai-q-text', q.text);
        card.appendChild(textEl);

        var list = el('ul', 'ai-q-options');
        (q.options || []).forEach(function(o) {
            var li = el('li');
            if (o.isCorrect) {
                var mark = el('span', 'ai-q-correct', '✓ ');
                li.appendChild(mark);
            }
            li.appendChild(document.createTextNode(o.text));
            list.appendChild(li);
        });
        card.appendChild(list);

        var details = document.createElement('details');
        var summary = el('summary', '', 'Источник и обоснование');
        details.appendChild(summary);
        if (q.source) {
            var srcLine = el('div');
            srcLine.innerHTML = 'Источник: ' + escapeText(q.source.section || q.source.document || '—') +
                (q.source.clause ? ' · п. ' + escapeText(q.source.clause) : '');
            if (q.source.reference) {
                srcLine.innerHTML += ' <a class="ai-source-link" target="_blank" rel="noopener" href="' +
                    escapeText(q.source.reference) + '">открыть</a>';
            }
            details.appendChild(srcLine);
            if (q.source.fragment) {
                details.appendChild(el('blockquote', '', q.source.fragment));
            }
        }
        if (q.rationale) {
            details.appendChild(el('div', '', 'Обоснование: ' + q.rationale));
        }
        if (q.explanation) {
            details.appendChild(el('div', '', 'Пояснение для ученика: ' + q.explanation));
        }
        card.appendChild(details);

        var actions = el('div', 'ai-q-actions');
        var acceptBtn = el('button', 'btn btn-success', '✅ Принять');
        var editBtn = el('button', 'btn btn-secondary', '✏️ Изменить');
        var regenBtn = el('button', 'btn btn-secondary', '🔄 Перегенерировать');
        var deleteBtn = el('button', 'btn btn-danger', '🗑 Удалить');
        actions.appendChild(acceptBtn);
        actions.appendChild(editBtn);
        actions.appendChild(regenBtn);
        actions.appendChild(deleteBtn);
        card.appendChild(actions);

        var editBox = buildEditBox(q, card);
        card.appendChild(editBox);
        var regenBox = buildRegenBox(q, card);
        card.appendChild(regenBox);

        acceptBtn.addEventListener('click', function() { acceptQuestion(q, card); });
        editBtn.addEventListener('click', function() { editBox.hidden = !editBox.hidden; });
        regenBtn.addEventListener('click', function() { regenBox.hidden = !regenBox.hidden; });
        deleteBtn.addEventListener('click', function() { deleteQuestion(q, card); });

        return card;
    }

    function buildEditBox(q, card) {
        var box = el('div', 'ai-q-edit');
        box.hidden = true;

        var textArea = document.createElement('textarea');
        textArea.className = 'form-textarea';
        textArea.value = q.text;
        textArea.style.minHeight = '60px';
        box.appendChild(textArea);

        var explArea = document.createElement('textarea');
        explArea.className = 'form-textarea';
        explArea.value = q.explanation || '';
        explArea.placeholder = 'Пояснение (после ответа)';
        explArea.style.minHeight = '40px';
        explArea.style.marginTop = '.5rem';
        box.appendChild(explArea);

        var optsWrap = el('div');
        optsWrap.style.marginTop = '.7rem';

        function addOptRow(text, isCorrect) {
            var row = el('div', 'ai-edit-opt');
            var check = document.createElement('input');
            check.type = 'checkbox';
            check.checked = !!isCorrect;
            var input = document.createElement('input');
            input.type = 'text';
            input.value = text || '';
            var remove = el('button', 'btn btn-secondary', '✕');
            remove.addEventListener('click', function() { row.remove(); });
            row.appendChild(check);
            row.appendChild(input);
            row.appendChild(remove);
            optsWrap.appendChild(row);
        }
        (q.options || []).forEach(function(o) { addOptRow(o.text, o.isCorrect); });

        box.appendChild(optsWrap);

        var addOpt = el('button', 'btn btn-secondary', '+ вариант');
        addOpt.style.marginTop = '.5rem';
        addOpt.addEventListener('click', function() { addOptRow('', false); });
        box.appendChild(addOpt);

        var saveRow = el('div', 'ai-q-actions');
        var saveBtn = el('button', 'btn btn-success', '💾 Сохранить');
        var cancelBtn = el('button', 'btn btn-secondary', 'Отмена');
        saveRow.appendChild(saveBtn);
        saveRow.appendChild(cancelBtn);
        box.appendChild(saveRow);

        cancelBtn.addEventListener('click', function() { box.hidden = true; });
        saveBtn.addEventListener('click', function() {
            var options = [];
            var rows = optsWrap.querySelectorAll('.ai-edit-opt');
            for (var i = 0; i < rows.length; i++) {
                var check = rows[i].querySelector('input[type=checkbox]');
                var input = rows[i].querySelector('input[type=text]');
                var text = input.value.trim();
                if (!text) { toast('Заполните все варианты ответов', 'warning'); return; }
                options.push({ text: text, isCorrect: check.checked });
            }
            if (options.length < 2) { toast('Нужно минимум 2 варианта', 'warning'); return; }
            if (!options.some(function(o) { return o.isCorrect; })) {
                toast('Отметьте хотя бы один правильный ответ', 'warning');
                return;
            }
            api('/api/questions/' + q.id, {
                method: 'PATCH',
                body: {
                    text: textArea.value.trim(),
                    explanation: explArea.value.trim(),
                    options: options
                }
            }).then(function(updated) {
                q.text = updated.text;
                q.explanation = updated.explanation;
                q.options = updated.options;
                replaceCard(card, updated);
                toast('Вопрос обновлён', 'success');
            }).catch(function(err) { toast(err.message, 'error'); });
        });
        return box;
    }

    function buildRegenBox(q, card) {
        var box = el('div', 'ai-q-regen');
        box.hidden = true;
        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-input';
        input.placeholder = 'Что исправить? Например: «сделай варианты правдоподобнее»';
        box.appendChild(input);
        var goBtn = el('button', 'btn btn-primary', '🔄 Перегенерировать');
        goBtn.style.marginTop = '.6rem';
        box.appendChild(goBtn);

        goBtn.addEventListener('click', function() {
            // Визуальная реакция: спиннер + блокировка карточки на время перегенерации
            goBtn.disabled = true;
            goBtn.innerHTML = '<span class="ai-spinner"></span>Перегенерация...';
            card.classList.add('busy');
            card.querySelectorAll('button').forEach(function(b) { b.disabled = true; });
            api('/api/questions/' + q.id + '/repair', {
                method: 'POST',
                body: { feedback: input.value.trim() }
            }).then(function(updated) {
                replaceCard(card, updated);
                toast('Вопрос перегенерирован', 'success');
            }).catch(function(err) {
                toast(err.message, 'error');
                goBtn.disabled = false;
                goBtn.textContent = '🔄 Перегенерировать';
                card.classList.remove('busy');
                card.querySelectorAll('button').forEach(function(b) { b.disabled = false; });
            });
        });
        return box;
    }

    function replaceCard(oldCard, q) {
        var newCard = renderQuestionCard(q);
        oldCard.parentNode.replaceChild(newCard, oldCard);
    }

    function acceptQuestion(q, card, done) {
        api('/api/questions/' + q.id + '/accept', { method: 'POST' }).then(function() {
            if (window.QuizBuilder && window.QuizBuilder.addQuestion) {
                window.QuizBuilder.addQuestion(q.builder_format || {
                    text: q.text,
                    explanation: q.explanation,
                    options: q.options
                });
                card.classList.add('accepted');
                toast('Вопрос добавлен в квиз', 'success');
            } else {
                toast('Конструктор квизов не инициализирован', 'error');
            }
            if (done) done(true);
        }).catch(function(err) {
            toast(err.message, 'error');
            if (done) done(false);
        });
    }

    function addAllToQuiz(done) {
        var cards = [];
        resultsEl.querySelectorAll('.ai-q-card').forEach(function(card) {
            if (!card.classList.contains('accepted') && card._q) cards.push(card);
        });
        if (!cards.length) {
            toast('Все вопросы уже добавлены в квиз', 'info');
            if (done) done();
            return;
        }
        var pending = cards.length;
        var added = 0;
        cards.forEach(function(card) {
            acceptQuestion(card._q, card, function(ok) {
                if (ok) added++;
                pending--;
                if (!pending) {
                    toast('Добавлено в квиз: ' + added + ' из ' + cards.length, 'success');
                    if (done) done();
                }
            });
        });
    }

    function deleteQuestion(q, card) {
        if (!window.confirm('Удалить этот вопрос?')) return;
        api('/api/questions/' + q.id, { method: 'DELETE' }).then(function() {
            card.remove();
            toast('Вопрос удалён', 'info');
        }).catch(function(err) { toast(err.message, 'error'); });
    }

    // ---------- восстановление после обновления страницы ----------
    function restoreLastJob() {
        api('/api/jobs/latest').then(function(job) {
            if (!job || !job.id) return;
            state.activeJob = job;
            if (job.params) {
                if (job.params.count) {
                    countInput.value = job.params.count;
                }
                var codes = job.params.section_codes ||
                    (job.params.section_code ? [job.params.section_code] : []);
                if (codes.length) {
                    state.lastPicked = codes.map(function(code) {
                        var title = code;
                        (state.groups || []).forEach(function(g) {
                            (g.categories || []).forEach(function(c) {
                                if (c.code === code) title = c.title;
                            });
                        });
                        return { code: code, title: title };
                    });
                    categoriesBox.querySelectorAll('input[type=checkbox]').forEach(function(cb) {
                        cb.checked = codes.indexOf(cb.value) >= 0;
                    });
                }
            }
            var isGenerate = (job.params && job.params.type) === 'generate';
            renderStatus();

            if (job.status === 'running' || job.status === 'queued') {
                // Задача ещё идёт — переподключаемся к прогрессу
                if (isGenerate) showProgress('Продолжаем предыдущую генерацию...');
                trackJob(job.id, function(doneJob) {
                    state.activeJob = doneJob;
                    renderStatus();
                    hideProgress();
                    if (isGenerate) loadResults(job.id, doneJob);
                    else loadSections();
                }, function(err) {
                    state.activeJob = job;
                    renderStatus();
                    hideProgress();
                    if (isGenerate) loadResults(job.id, job);
                    toast('Задача завершилась с ошибкой: ' + err, 'error');
                });
            } else if (isGenerate && (job.status === 'completed' || job.status === 'partial' || job.status === 'cancelled')) {
                if (job.result && job.result.count) loadResults(job.id, job);
                if (job.status === 'partial') {
                    toast('Прошлая генерация завершилась частично — вопросы сохранены', 'warning');
                }
                if (job.status === 'cancelled') {
                    toast('Прошлая генерация была остановлена — частичные вопросы показаны ниже', 'warning');
                }
            } else if (isGenerate && job.status === 'failed' && job.result && job.result.count) {
                loadResults(job.id, job);
            }
        }).catch(function() { /* job-ов ещё не было — обычный первый запуск */ });
    }

    // ---------- старт ----------
    function initAI() {
        if (!document.getElementById('aiPanelRoot')) return;
        injectStyles();
        buildPanel();
        loadSections().then(restoreLastJob);
        // Периодическое обновление статуса (видно прогресс фонового извлечения)
        setInterval(loadSections, 20000);
    }

    // API для конструктора (js.js): bulk-добавление сгенерированных вопросов в квиз
    window.AIPanel = {
        addAll: addAllToQuiz
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAI);
    } else {
        initAI();
    }

})();
