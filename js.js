(function() {
    'use strict';

    var questions = [];
    var editingIndex = -1;
    var confirmCallback = null;

    var newQuizBtn, openQuizBtn, saveQuizBtn, generateHtmlBtn;
    var addQuestionBtn, questionsListEl, totalQuestionsEl;
    var questionModal, closeQuestionModalBtn, cancelQuestionBtn, saveQuestionBtn;
    var questionTextInput, optionsContainer, explanationInput, questionErrorEl;
    var generatedHtmlModal, htmlOutput, copyHtmlBtn, downloadHtmlBtn, closeGeneratedHtmlBtn;
    var confirmModal, closeConfirmModalBtn, cancelConfirmBtn, confirmBtn, confirmMessage, confirmTitleEl;
    var fileInput, quizTitleInput;
    var showToastFunc, toastContainerEl;
    var addOptionBtn, removeOptionBtn;

    function init() {
        newQuizBtn = document.getElementById('newQuizBtn');
        openQuizBtn = document.getElementById('openQuizBtn');
        saveQuizBtn = document.getElementById('saveQuizBtn');
        generateHtmlBtn = document.getElementById('generateHtmlBtn');
        addQuestionBtn = document.getElementById('addQuestionBtn');
        questionsListEl = document.getElementById('questionsList');
        totalQuestionsEl = document.getElementById('totalQuestions');
        questionModal = document.getElementById('questionModal');
        closeQuestionModalBtn = document.getElementById('closeQuestionModalBtn');
        cancelQuestionBtn = document.getElementById('cancelQuestionBtn');
        saveQuestionBtn = document.getElementById('saveQuestionBtn');
        questionTextInput = document.getElementById('questionText');
        optionsContainer = document.getElementById('optionsContainer');
        explanationInput = document.getElementById('explanationInput');
        questionErrorEl = document.getElementById('questionError');
        generatedHtmlModal = document.getElementById('generatedHtmlModal');
        htmlOutput = document.getElementById('htmlOutput');
        copyHtmlBtn = document.getElementById('copyHtmlBtn');
        downloadHtmlBtn = document.getElementById('downloadHtmlBtn');
        closeGeneratedHtmlBtn = document.getElementById('closeGeneratedHtmlBtn');
        confirmModal = document.getElementById('confirmModal');
        closeConfirmModalBtn = document.getElementById('closeConfirmModalBtn');
        cancelConfirmBtn = document.getElementById('cancelConfirmBtn');
        confirmBtn = document.getElementById('confirmBtn');
        confirmMessage = document.getElementById('confirmMessage');
        confirmTitleEl = document.getElementById('confirmTitle');
        fileInput = document.getElementById('fileInput');
        quizTitleInput = document.getElementById('quizTitleInput');
        addOptionBtn = document.getElementById('addOptionBtn');
        removeOptionBtn = document.getElementById('removeOptionBtn');
        toastContainerEl = document.getElementById('toastContainer');

        if (!newQuizBtn || !questionsListEl || !questionModal) {
            console.error('Не найдены необходимые элементы DOM.');
            return;
        }

        initEventListeners();
        renderQuestionsList();
        loadFromLocalStorage();
        console.log('Конструктор квизов инициализирован');
    }

    function initEventListeners() {
        newQuizBtn.addEventListener('click', newQuiz);
        openQuizBtn.addEventListener('click', function() { fileInput.click(); });
        saveQuizBtn.addEventListener('click', saveQuiz);
        generateHtmlBtn.addEventListener('click', generateHtmlCode);
        fileInput.addEventListener('change', handleFileLoad);
        addQuestionBtn.addEventListener('click', function() { openQuestionModal(-1); });

        closeQuestionModalBtn.addEventListener('click', closeQuestionModal);
        cancelQuestionBtn.addEventListener('click', closeQuestionModal);
        saveQuestionBtn.addEventListener('click', saveQuestion);
        closeGeneratedHtmlBtn.addEventListener('click', function() { generatedHtmlModal.classList.remove('active'); });

        questionModal.addEventListener('click', function(e) {
            if (e.target === questionModal) closeQuestionModal();
        });

        generatedHtmlModal.addEventListener('click', function(e) {
            if (e.target === generatedHtmlModal) generatedHtmlModal.classList.remove('active');
        });

        confirmModal.addEventListener('click', function(e) {
            if (e.target === confirmModal) confirmModal.classList.remove('active');
        });

        downloadHtmlBtn.addEventListener('click', downloadHtml);
        copyHtmlBtn.addEventListener('click', function() {
            copyToClipboard(htmlOutput.value, copyHtmlBtn);
        });

        closeConfirmModalBtn.addEventListener('click', function() { confirmModal.classList.remove('active'); });
        cancelConfirmBtn.addEventListener('click', function() { confirmModal.classList.remove('active'); });
        confirmBtn.addEventListener('click', function() {
            if (confirmCallback) confirmCallback();
            confirmModal.classList.remove('active');
            confirmCallback = null;
        });

        questionTextInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && e.ctrlKey) {
                saveQuestion();
            }
        });

        addOptionBtn.addEventListener('click', handleAddOption);
        removeOptionBtn.addEventListener('click', handleRemoveOption);
    }

    function newQuiz() {
        if (questions.length > 0) {
            showConfirm('Создать новый квиз? Все несохраненные изменения будут потеряны.', function() {
                questions = [];
                editingIndex = -1;
                quizTitleInput.value = '';
                renderQuestionsList();
                saveToLocalStorage();
                showToastFunc('Новый квиз создан', 'success');
            });
        } else {
            questions = [];
            editingIndex = -1;
            quizTitleInput.value = '';
            renderQuestionsList();
            showToastFunc('Новый квиз создан', 'success');
        }
    }

    function saveQuiz(force) {
        // Страховка: квиз пуст, а в AI-панели есть сгенерированные вопросы
        if (!force && questions.length === 0 && window.AIPanel && window.AIPanel.addAll) {
            showConfirm('В квизе нет вопросов. Добавить сгенерированные из AI-панели и сохранить?', function() {
                window.AIPanel.addAll(function() { saveQuiz(true); });
            });
            return;
        }
        var title = quizTitleInput.value.trim() || 'Квиз';
        var data = { title: title, questions: questions };
        
        // Сохраняем в localStorage для автовосстановления
        localStorage.setItem('quizBuilderData', JSON.stringify(data));
        
        // Скачиваем JSON файл
        var blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = title.replace(/[^a-zа-яё0-9]/gi, '_') + '.json';
        a.click();
        URL.revokeObjectURL(url);
        
        showToastFunc('Квиз сохранен и скачан', 'success');
    }

    function loadFromLocalStorage() {
        var saved = localStorage.getItem('quizBuilderData');
        if (saved) {
            try {
                var data = JSON.parse(saved);
                quizTitleInput.value = data.title || '';
                questions = data.questions || [];
                renderQuestionsList();
            } catch (e) {
                console.error('Ошибка загрузки сохраненных данных', e);
            }
        }
    }

    function saveToLocalStorage() {
        var title = quizTitleInput.value.trim() || 'Квиз';
        var data = { title: title, questions: questions };
        localStorage.setItem('quizBuilderData', JSON.stringify(data));
    }

    function handleFileLoad(e) {
        var file = e.target.files[0];
        if (!file) return;

        var reader = new FileReader();
        reader.onload = function(event) {
            try {
                var data = JSON.parse(event.target.result);
                quizTitleInput.value = data.title || 'Импортированный квиз';
                questions = data.questions || [];
                renderQuestionsList();
                saveToLocalStorage();
                showToastFunc('Квиз загружен из файла', 'success');
            } catch (err) {
                showToastFunc('Ошибка чтения файла', 'error');
            }
        };
        reader.readAsText(file);
        e.target.value = '';
    }

    function openQuestionModal(index) {
        editingIndex = index;
        questionTextInput.value = '';
        explanationInput.value = '';
        optionsContainer.innerHTML = '';

        if (index >= 0 && index < questions.length) {
            var q = questions[index];
            questionTextInput.value = q.text;
            explanationInput.value = q.explanation || '';
            generateOptionsInputs(q.options);
        } else {
            generateOptionsInputs([]);
        }

        questionModal.classList.add('active');
        questionTextInput.focus();
    }

    function closeQuestionModal() {
        questionModal.classList.remove('active');
        editingIndex = -1;
    }

    function generateOptionsInputs(existingOptions) {
        optionsContainer.innerHTML = '';
        var count = existingOptions && existingOptions.length > 0 ? existingOptions.length : 4;
        if (count < 2) count = 2;
        if (count > 6) count = 6;

        var hasCorrect = false;
        if (existingOptions && existingOptions.length > 0) {
            for (var i = 0; i < existingOptions.length; i++) {
                if (existingOptions[i].isCorrect) {
                    hasCorrect = true;
                    break;
                }
            }
        }

        for (var j = 0; j < count; j++) {
            var optText = '';
            var isCorrect = false;
            
            if (existingOptions && existingOptions[j]) {
                optText = existingOptions[j].text;
                isCorrect = existingOptions[j].isCorrect;
            } else if (j === 0 && !hasCorrect) {
                isCorrect = true;
            }

            var item = document.createElement('div');
            item.className = 'option-item';
            item.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:10px;padding:10px;background:#f7fafc;border-radius:8px;';

            var radio = document.createElement('input');
            radio.type = 'checkbox';
            radio.name = 'correctOption';
            radio.className = 'custom-radio';
            radio.checked = isCorrect;
            
            // Чекбоксы: правильных ответов может быть несколько (1..N)

            var input = document.createElement('input');
            input.type = 'text';
            input.className = 'option-input';
            input.placeholder = 'Вариант ' + (j + 1);
            input.value = optText;
            input.style.cssText = 'flex:1;padding:8px;border:1px solid #e2e8f0;border-radius:6px;';

            var removeBtn = document.createElement('button');
            removeBtn.textContent = '✕';
            removeBtn.className = 'remove-option-btn';
            removeBtn.style.cssText = 'background:#fc8181;color:white;border:none;border-radius:50%;width:28px;height:28px;cursor:pointer;font-size:14px;';
            
            (function(currentItem) {
                removeBtn.addEventListener('click', function() {
                    var items = optionsContainer.querySelectorAll('.option-item');
                    if (items.length > 2) {
                        currentItem.remove();
                        reindexOptions();
                    } else {
                        showToastFunc('Минимум 2 варианта ответа', 'error');
                    }
                });
            })(item);

            item.appendChild(radio);
            item.appendChild(input);
            item.appendChild(removeBtn);
            optionsContainer.appendChild(item);
        }

        updateOptionButtons();
    }

    function reindexOptions() {
        var items = optionsContainer.querySelectorAll('.option-item');
        var anyCorrect = false;
        for (var i = 0; i < items.length; i++) {
            var radio = items[i].querySelector('.custom-radio');
            var input = items[i].querySelector('.option-input');
            input.placeholder = 'Вариант ' + (i + 1);

            if (radio.checked) {
                anyCorrect = true;
            }
        }

        if (!anyCorrect && items.length > 0) {
            items[0].querySelector('.custom-radio').checked = true;
        }

        updateOptionButtons();
    }

    function handleAddOption() {
        var items = optionsContainer.querySelectorAll('.option-item');
        if (items.length >= 6) {
            showToastFunc('Максимум 6 вариантов ответа', 'warning');
            return;
        }

        var item = document.createElement('div');
        item.className = 'option-item';
        item.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:10px;padding:10px;background:#f7fafc;border-radius:8px;';

        var radio = document.createElement('input');
        radio.type = 'checkbox';
        radio.name = 'correctOption';
        radio.className = 'custom-radio';
        radio.checked = false;

        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'option-input';
        input.placeholder = 'Вариант ' + (items.length + 1);
        input.value = '';
        input.style.cssText = 'flex:1;padding:8px;border:1px solid #e2e8f0;border-radius:6px;';

        var removeBtn = document.createElement('button');
        removeBtn.textContent = '✕';
        removeBtn.className = 'remove-option-btn';
        removeBtn.style.cssText = 'background:#fc8181;color:white;border:none;border-radius:50%;width:28px;height:28px;cursor:pointer;font-size:14px;';

        (function(currentItem) {
            removeBtn.addEventListener('click', function() {
                var currentItems = optionsContainer.querySelectorAll('.option-item');
                if (currentItems.length > 2) {
                    currentItem.remove();
                    reindexOptions();
                } else {
                    showToastFunc('Минимум 2 варианта ответа', 'error');
                }
            });
        })(item);

        item.appendChild(radio);
        item.appendChild(input);
        item.appendChild(removeBtn);
        optionsContainer.appendChild(item);

        updateOptionButtons();
    }

    function handleRemoveOption() {
        var items = optionsContainer.querySelectorAll('.option-item');
        if (items.length <= 2) {
            showToastFunc('Минимум 2 варианта ответа', 'error');
            return;
        }
        items[items.length - 1].remove();
        reindexOptions();
    }

    function updateOptionButtons() {
        var addBtn = document.getElementById('addOptionBtn');
        var items = optionsContainer.querySelectorAll('.option-item');

        if (addBtn) {
            if (items.length >= 6) {
                addBtn.disabled = true;
                addBtn.style.opacity = '0.5';
                addBtn.style.cursor = 'not-allowed';
            } else {
                addBtn.disabled = false;
                addBtn.style.opacity = '1';
                addBtn.style.cursor = 'pointer';
            }
        }
    }

    function saveQuestion() {
        var text = questionTextInput.value.trim();
        if (!text) {
            showToastFunc('Введите текст вопроса', 'error');
            return;
        }

        var items = optionsContainer.querySelectorAll('.option-item');
        var options = [];
        var correctIndex = -1;

        for (var i = 0; i < items.length; i++) {
            var input = items[i].querySelector('.option-input');
            var radio = items[i].querySelector('.custom-radio');
            var optText = input.value.trim();

            if (!optText) {
                showToastFunc('Заполните все варианты ответов', 'error');
                return;
            }

            options.push({
                text: optText,
                isCorrect: radio.checked
            });

            if (radio.checked) {
                correctIndex = i;
            }
        }

        if (correctIndex === -1) {
            showToastFunc('Выберите правильный ответ', 'error');
            return;
        }

        var explanation = explanationInput.value.trim();

        if (editingIndex >= 0) {
            questions[editingIndex] = {
                text: text,
                options: options,
                explanation: explanation
            };
            showToastFunc('Вопрос обновлен', 'success');
        } else {
            questions.push({
                text: text,
                options: options,
                explanation: explanation
            });
            showToastFunc('Вопрос добавлен', 'success');
        }

        closeQuestionModal();
        renderQuestionsList();
        saveToLocalStorage();
    }

    function renderQuestionsList() {
        questionsListEl.innerHTML = '';

        if (questions.length === 0) {
            questionsListEl.innerHTML = '<p style="text-align:center;color:#a0aec0;padding:2rem;">Список вопросов пуст. Добавьте первый вопрос!</p>';
            updateStats();
            return;
        }

        for (var i = 0; i < questions.length; i++) {
            var q = questions[i];
            var card = document.createElement('div');
            card.className = 'question-card-item';
            card.style.cssText = 'background:#fff;padding:1.5rem;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);margin-bottom:1rem;display:flex;justify-content:space-between;align-items:center;';

            var leftDiv = document.createElement('div');
            leftDiv.style.cssText = 'flex:1;';

            var numSpan = document.createElement('span');
            numSpan.style.cssText = 'display:inline-block;background:#667eea;color:white;padding:4px 10px;border-radius:20px;font-size:0.85rem;font-weight:600;margin-right:10px;';
            numSpan.textContent = 'Вопрос ' + (i + 1);

            var textSpan = document.createElement('span');
            textSpan.textContent = q.text;
            textSpan.style.cssText = 'font-weight:500;color:#2d3748;';

            leftDiv.appendChild(numSpan);
            leftDiv.appendChild(textSpan);

            // Бейдж «N верных» для вопросов с несколькими правильными ответами
            var correctN = (q.options || []).filter(function(o) { return o.isCorrect; }).length;
            if (correctN > 1) {
                var multiBadge = document.createElement('span');
                multiBadge.textContent = '✓ ' + correctN + ' верных';
                multiBadge.style.cssText = 'margin-left:8px;padding:2px 8px;border-radius:10px;background:#e8f8f0;color:#155724;font-size:.8rem;font-weight:600;';
                leftDiv.appendChild(multiBadge);
            }

            var rightDiv = document.createElement('div');
            rightDiv.style.cssText = 'display:flex;gap:8px;';

            var editBtn = document.createElement('button');
            editBtn.textContent = '✏️';
            editBtn.className = 'edit-question-btn';
            editBtn.dataset.index = i;
            editBtn.title = 'Редактировать';
            editBtn.style.cssText = 'background:#e2e8f0;border:none;padding:8px 12px;border-radius:8px;cursor:pointer;font-size:1rem;transition:background 0.2s;';
            editBtn.onmouseover = function() { this.style.background = '#cbd5e0'; };
            editBtn.onmouseout = function() { this.style.background = '#e2e8f0'; };

            var deleteBtn = document.createElement('button');
            deleteBtn.textContent = '🗑️';
            deleteBtn.className = 'delete-question-btn';
            deleteBtn.dataset.index = i;
            deleteBtn.title = 'Удалить';
            deleteBtn.style.cssText = 'background:#fed7d7;border:none;padding:8px 12px;border-radius:8px;cursor:pointer;font-size:1rem;transition:background 0.2s;';
            deleteBtn.onmouseover = function() { this.style.background = '#feb2b2'; };
            deleteBtn.onmouseout = function() { this.style.background = '#fed7d7'; };

            rightDiv.appendChild(editBtn);
            rightDiv.appendChild(deleteBtn);

            card.appendChild(leftDiv);
            card.appendChild(rightDiv);
            questionsListEl.appendChild(card);
        }

        questionsListEl.onclick = function(e) {
            var editBtn = e.target.closest('.edit-question-btn');
            var deleteBtn = e.target.closest('.delete-question-btn');

            if (editBtn) {
                var idx = parseInt(editBtn.dataset.index);
                openQuestionModal(idx);
            } else if (deleteBtn) {
                var idx = parseInt(deleteBtn.dataset.index);
                showDeleteConfirm(idx);
            }
        };

        updateStats();
    }

    function showDeleteConfirm(index) {
        showConfirm('Вы уверены, что хотите удалить этот вопрос?', function() {
            questions.splice(index, 1);
            renderQuestionsList();
            saveToLocalStorage();
            showToastFunc('Вопрос удален', 'success');
        });
    }

    function showConfirm(message, callback) {
        confirmMessage.textContent = message;
        confirmCallback = callback;
        confirmModal.classList.add('active');
    }

    function generateHtmlCode() {
        if (questions.length === 0) {
            showToastFunc('Добавьте хотя бы один вопрос', 'error');
            return;
        }

        var title = quizTitleInput.value.trim() || 'Мой квиз';
        var totalQuestions = questions.length;

        var navRadios = '';
        for (var nr = 0; nr < totalQuestions; nr++) {
            navRadios += '<input type="radio" name="quiz-nav" id="nav-q' + nr + '" class="nav-radio"' + (nr === 0 ? ' checked' : '') + '>\n';
        }
        navRadios += '<input type="radio" name="quiz-nav" id="nav-final" class="nav-radio">\n';
        navRadios += '<input type="radio" name="quiz-nav" id="nav-review" class="nav-radio">';

        var questionsHTML = '';
        var reviewHTML = '';

        for (var qIdx = 0; qIdx < totalQuestions; qIdx++) {
            var q = questions[qIdx];
            var questionNum = qIdx + 1;
            var progressWidth = ((qIdx + 1) / totalQuestions) * 100;

            var optionsHTML = '';
            var reviewOptionsHTML = '';
            var correctTexts = [];
            var multiCorrect = q.options.filter(function(o) { return o.isCorrect; }).length > 1;

            for (var optIdx = 0; optIdx < q.options.length; optIdx++) {
                var opt = q.options[optIdx];
                var isCorrect = opt.isCorrect;
                var optId = 'q' + qIdx + '-opt' + optIdx;

                optionsHTML += '<input type="' + (multiCorrect ? 'checkbox' : 'radio') + '" name="q' + qIdx + '" id="' + optId + '" class="answer-radio" data-correct="' + (isCorrect ? 'true' : 'false') + '">' +
                    '<label for="' + optId + '" class="option-label"><span class="option-marker"></span><span class="option-text">' + escapeHtml(opt.text) + '</span></label>';

                if (isCorrect) {
                    correctTexts.push(opt.text);
                    reviewOptionsHTML += '<div class="review-option review-correct"><span class="review-marker">✓</span><span class="review-text">' + escapeHtml(opt.text) + '</span></div>';
                } else {
                    reviewOptionsHTML += '<div class="review-option review-wrong"><span class="review-marker">○</span><span class="review-text">' + escapeHtml(opt.text) + '</span></div>';
                }
            }

            // Плашка для вопросов с несколькими верными ответами (без JS)
            if (multiCorrect) {
                optionsHTML = '<div class="multi-badge">✓ Несколько верных ответов — отметьте все верные</div>' + optionsHTML;
                reviewOptionsHTML = '<div class="multi-badge">Несколько верных ответов</div>' + reviewOptionsHTML;
            }

            var nextBtnText = (qIdx < totalQuestions - 1) ? 'Далее →' : 'Завершить →';
            var prevLabel = qIdx > 0 ? 'nav-q' + (qIdx - 1) : '';
            var nextLabel = qIdx < totalQuestions - 1 ? 'nav-q' + (qIdx + 1) : 'nav-final';
            var backBtn = qIdx > 0 ? '<label for="' + prevLabel + '" class="nav-btn nav-back">← Назад</label>' : '<span class="nav-btn nav-back disabled">← Назад</span>';

            var hintTitle = multiCorrect ? 'Правильные ответы:' : 'Правильный ответ:';
            var hintClass = multiCorrect ? 'answer-hint answer-hint-multi' : 'answer-hint';
            var hintHTML = '<div class="' + hintClass + '"><div class="answer-hint-title"><span class="answer-hint-icon">💡</span>' + hintTitle + ' <span class="answer-hint-correct">' + escapeHtml(correctTexts.join('; ')) + '</span></div>';
            if (q.explanation) {
                hintHTML += '<div class="answer-hint-text">' + escapeHtml(q.explanation) + '</div>';
            }
            hintHTML += '</div>';

            questionsHTML += '<div class="question-card" id="card-q' + qIdx + '"><div class="progress-bar"><div class="progress-fill" style="width: ' + progressWidth + '%"></div></div><div class="question-header"><span class="question-number">Вопрос ' + questionNum + '</span><span class="question-total">из ' + totalQuestions + '</span></div><div class="question-text">' + escapeHtml(q.text) + '</div><div class="options-container">' + optionsHTML + hintHTML + '</div><div class="navigation-buttons">' + backBtn + '<label for="' + nextLabel + '" class="nav-btn nav-next">' + nextBtnText + '</label></div></div>';

            var explanationText = q.explanation ? '<div class="review-explanation"><span class="review-explanation-icon">💡</span><span class="review-explanation-text">' + escapeHtml(q.explanation) + '</span></div>' : '';
            reviewHTML += '<div class="review-card"><div class="review-question-number">Вопрос ' + questionNum + '</div><div class="review-question-text">' + escapeHtml(q.text) + '</div><div class="review-correct-section"><div class="review-correct-title">Правильный ответ:</div><div class="review-options">' + reviewOptionsHTML + '</div></div>' + explanationText + '</div>';
        }

        var finalScreen = '<div class="final-screen" id="final-screen"><div class="final-header"><div class="final-icon">🏆</div><h2 class="final-title">Квиз завершён!</h2><p class="final-subtitle">Вы прошли все ' + totalQuestions + ' вопросов</p><div class="final-summary"><p class="final-message">Теперь вы можете посмотреть правильные ответы с пояснениями или пройти квиз заново.</p></div></div><div class="final-actions"><label for="nav-q0" class="nav-btn nav-restart">🔄 Пройти заново</label><label for="nav-review" class="nav-btn nav-review">📋 Посмотреть ответы</label></div></div>';

        var resultScreen = '<div class="result-screen" id="result-screen"><div class="result-header"><div class="result-icon">📊</div><h2 class="result-title">Правильные ответы</h2><p class="result-subtitle">Разбор всех вопросов</p></div><div class="review-container">' + reviewHTML + '</div><div class="result-actions"><label for="nav-q0" class="nav-btn nav-restart">🔄 Пройти заново</label><label for="nav-final" class="nav-btn nav-back">← К результатам</label></div></div>';

        var cssContent = '*{margin:0;padding:0;box-sizing:border-box}html,body{width:100%;overflow-x:hidden;position:relative}body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#2d3748;line-height:1.6;min-height:100vh;padding:2rem 1rem;-webkit-text-size-adjust:100%}.header{background:rgba(255,255,255,0.95);backdrop-filter:blur(10px);border-radius:24px;padding:3rem 2rem;text-align:center;margin-bottom:2rem;box-shadow:0 20px 60px rgba(0,0,0,0.15);max-width:700px;margin-left:auto;margin-right:auto}.header h1{font-size:2.5rem;font-weight:800;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:0.5rem;letter-spacing:-0.5px;word-wrap:break-word;overflow-wrap:break-word}.header p{color:#718096;font-size:1.1rem;font-weight:500}input.nav-radio,input.answer-radio{display:none}.quiz-container{max-width:700px;margin:0 auto;width:100%}.question-card,.final-screen,.result-screen{display:none}';

        var selectorParts = [];
        for (var selIdx = 0; selIdx < totalQuestions; selIdx++) {
            selectorParts.push('#nav-q' + selIdx + ':checked~.quiz-container #card-q' + selIdx);
        }
        selectorParts.push('#nav-final:checked~.quiz-container #final-screen');
        selectorParts.push('#nav-review:checked~.quiz-container #result-screen');
        cssContent += selectorParts.join(',') + '{display:block;animation:fadeIn .4s ease-in-out}@keyframes fadeIn{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}@keyframes slideIn{from{opacity:0;transform:translateX(-20px)}to{opacity:1;transform:translateX(0)}}@keyframes bounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}.final-screen,.result-screen{margin-bottom:2rem}.final-header,.result-header{text-align:center;padding:3rem 2rem;background:#fff;border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,0.15);position:relative;overflow:hidden;max-width:700px;margin:0 auto 2rem}.final-header::before,.result-header::before{content:\'\';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#667eea,#764ba2,#667eea);background-size:200% 100%;animation:shimmer 2s infinite}@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}.final-icon,.result-icon{font-size:5rem;margin-bottom:1rem;animation:bounce 2s infinite;display:inline-block}.final-title,.result-title{font-size:2rem;font-weight:700;color:#2d3748;margin-bottom:0.5rem;letter-spacing:-0.5px}.final-subtitle,.result-subtitle{color:#718096;font-size:1.1rem;font-weight:500}.final-summary{margin-top:2rem;padding:1.5rem;background:linear-gradient(135deg,#f7fafc,#edf2f7);border-radius:16px;border:1px solid #e2e8f0}.final-message{color:#4a5568;font-size:1rem;line-height:1.7;font-weight:500}.final-actions,.result-actions{display:flex;justify-content:center;gap:1rem;padding:2rem;flex-wrap:wrap}.nav-btn{display:inline-flex;align-items:center;gap:0.5rem;padding:1rem 2rem;border-radius:16px;font-weight:600;font-size:0.95rem;cursor:pointer;transition:all 0.3s cubic-bezier(0.4,0,0.2,1);text-align:center;box-shadow:0 4px 15px rgba(0,0,0,0.1);user-select:none;text-decoration:none;position:relative;overflow:hidden;white-space:nowrap}.nav-btn::before{content:\'\';position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(45deg,rgba(255,255,255,0.2),transparent);opacity:0;transition:opacity 0.3s}.nav-btn:hover::before{opacity:1}.nav-btn:hover{transform:translateY(-3px);box-shadow:0 8px 25px rgba(0,0,0,0.15)}.nav-restart{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}.nav-review{background:linear-gradient(135deg,#f093fb,#f5576c);color:#fff}.nav-next{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;margin-left:auto}.nav-back{background:#f7fafc;color:#4a5568;border:2px solid #e2e8f0}.nav-back:hover{background:#edf2f7;border-color:#cbd5e0}.nav-back.disabled{opacity:0.5;cursor:not-allowed;transform:none;box-shadow:none}.question-card{background:#fff;border-radius:24px;padding:2.5rem;margin-bottom:1.5rem;box-shadow:0 20px 60px rgba(0,0,0,0.15);position:relative;overflow:hidden;animation:slideIn 0.4s ease-out;max-width:700px;margin-left:auto;margin-right:auto}.question-card::before{content:\'\';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#667eea,#764ba2)}.progress-bar{width:100%;height:8px;background:#e2e8f0;border-radius:10px;margin-bottom:2rem;overflow:hidden;box-shadow:inset 0 2px 4px rgba(0,0,0,0.1)}.progress-fill{height:100%;background:linear-gradient(90deg,#667eea,#764ba2);border-radius:10px;transition:width 0.5s cubic-bezier(0.4,0,0.2,1);box-shadow:0 2px 10px rgba(102,126,234,0.4)}.question-header{display:flex;justify-content:space-between;margin-bottom:1.5rem;padding:0.75rem 1rem;background:linear-gradient(135deg,#f7fafc,#edf2f7);border-radius:12px;flex-wrap:wrap;gap:0.5rem}.question-number{color:#667eea;font-weight:700;text-transform:uppercase;font-size:0.8rem;letter-spacing:1px}.question-total{color:#a0aec0;font-size:0.8rem;font-weight:600}.question-text{font-size:1.4rem;font-weight:700;color:#2d3748;margin-bottom:2rem;line-height:1.4;letter-spacing:-0.3px;word-wrap:break-word;overflow-wrap:break-word}.options-container{display:flex;flex-direction:column;gap:1rem}.option-label{display:flex;align-items:center;padding:1.25rem 1.5rem;border:2px solid #e2e8f0;border-radius:16px;cursor:pointer;transition:all 0.3s cubic-bezier(0.4,0,0.2,1);background:#fff;position:relative;overflow:hidden;flex-wrap:wrap}.option-label::before{content:\'\';position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(135deg,#667eea,#764ba2);transform:scaleY(0);transition:transform 0.3s}.option-label:hover{border-color:#667eea;background:#f7fafc;transform:translateX(5px);box-shadow:0 4px 15px rgba(102,126,234,0.15)}.option-label:hover::before{transform:scaleY(1)}.option-marker{width:24px;height:24px;border:2px solid #cbd5e0;border-radius:8px;margin-right:1.25rem;flex-shrink:0;transition:all 0.3s;background:#fff;display:flex;align-items:center;justify-content:center;box-shadow:inset 0 2px 4px rgba(0,0,0,0.1)}.option-marker::after{content:\'\';width:12px;height:12px;background:#fff;border-radius:4px;transform:scale(0);transition:transform 0.3s}.option-text{flex:1;min-width:0;font-size:1rem;font-weight:500;color:#4a5568;transition:color 0.3s;word-wrap:break-word;overflow-wrap:break-word}input.answer-radio:checked+.option-label{border-color:#667eea;background:linear-gradient(135deg,#f7fafc,#edf2f7);box-shadow:0 4px 20px rgba(102,126,234,0.2);transform:translateX(5px)}input.answer-radio:checked+.option-label .option-marker{border-color:#667eea;background:linear-gradient(135deg,#667eea,#764ba2);box-shadow:0 2px 10px rgba(102,126,234,0.4)}input.answer-radio:checked+.option-label .option-marker::after{transform:scale(1)}input.answer-radio:checked+.option-label .option-text{color:#2d3748;font-weight:600}';

        cssContent += '.answer-hint{display:none;padding:1.25rem 1.5rem;background:linear-gradient(135deg,#f7fafc,#edf2f7);border-radius:12px;font-size:0.95rem;color:#4a5568;line-height:1.7;border-left:4px solid #667eea;word-wrap:break-word;overflow-wrap:break-word}.answer-hint-title{font-weight:700;color:#2d3748}.answer-hint-icon{margin-right:0.5rem}.answer-hint-correct{color:#28a745}.answer-hint-text{margin-top:0.5rem}.question-card .answer-radio:checked~.answer-hint{display:block;animation:fadeIn .4s ease-in-out}';

        for (var cssIdx = 0; cssIdx < totalQuestions; cssIdx++) {
            cssContent += 'input[name="q' + cssIdx + '"][data-correct="false"]:checked+.option-label{background:#f8d7da!important;border-color:#dc3545!important;color:#721c24}input[name="q' + cssIdx + '"][data-correct="false"]:checked+.option-label .option-marker{background:#dc3545!important;border-color:#dc3545!important}input[name="q' + cssIdx + '"][data-correct="true"]:checked+.option-label{background:#d4edda!important;border-color:#28a745!important;color:#155724}input[name="q' + cssIdx + '"][data-correct="true"]:checked+.option-label .option-marker{background:#28a745!important;border-color:#28a745!important}';
            // Мульти-вопрос: подсказка раскрывается только после выбора ВСЕХ верных ответов
            var mq = questions[cssIdx];
            var correctIdxs = [];
            for (var mi = 0; mi < mq.options.length; mi++) {
                if (mq.options[mi].isCorrect) correctIdxs.push(mi);
            }
            if (correctIdxs.length > 1) {
                var chain = correctIdxs.map(function(idx) {
                    return '#q' + cssIdx + '-opt' + idx + ':checked';
                }).join('~');
                cssContent += chain + '~.answer-hint-multi{display:block!important;animation:fadeIn .4s ease-in-out}';
            }
        }

        cssContent += '.multi-badge{display:inline-block;margin-bottom:1rem;padding:.55rem 1rem;background:#e8f8f0;color:#155724;border:1px solid #a3d9b1;border-radius:10px;font-weight:600;font-size:.92rem}.review-option .multi-badge{margin:0 0 .5rem 0}';
        // Мульти-ответы: подсказка скрыта и раскрывается только когда выбраны ВСЕ верные (без JS)
        cssContent += '.answer-hint-multi{display:none!important}';
        cssContent += '.navigation-buttons{display:flex;gap:1rem;margin-top:2rem;padding-top:1.5rem;border-top:2px solid #f7fafc;flex-wrap:wrap}.result-screen{margin-bottom:2rem}.review-container{background:#fff;border-radius:24px;padding:2rem;box-shadow:0 20px 60px rgba(0,0,0,0.15);max-width:700px;margin:0 auto}.review-card{padding:1.5rem;border-bottom:2px solid #f7fafc;transition:background 0.3s}.review-card:last-child{border-bottom:none}.review-card:hover{background:linear-gradient(135deg,#f7fafc,#edf2f7);border-radius:12px}.review-question-number{color:#667eea;font-weight:700;margin-bottom:0.5rem;font-size:0.8rem;text-transform:uppercase;letter-spacing:1px}.review-question-text{font-size:1.1rem;margin-bottom:1rem;font-weight:600;color:#2d3748;line-height:1.5;word-wrap:break-word;overflow-wrap:break-word}.review-option{display:flex;align-items:center;padding:1rem 1.25rem;margin-bottom:0.75rem;border-radius:12px;font-size:0.95rem;transition:all 0.3s;flex-wrap:wrap}.review-correct{background:linear-gradient(135deg,#d4edda,#c3e6cb);color:#155724;border:2px solid #a3d9b1;font-weight:600;box-shadow:0 2px 10px rgba(21,87,36,0.1)}.review-wrong{background:#f7fafc;color:#718096;border:2px solid #e2e8f0}.review-marker{margin-right:1rem;font-weight:700;font-size:1.2rem;width:24px;text-align:center;flex-shrink:0}.review-correct-section{margin-top:1.25rem}.review-correct-title{font-weight:700;color:#38a169;margin-bottom:1rem;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.5px}.review-explanation{margin-top:1rem;padding:1.25rem;background:linear-gradient(135deg,#f7fafc,#edf2f7);border-radius:12px;font-size:0.9rem;color:#4a5568;line-height:1.7;border-left:4px solid #667eea;word-wrap:break-word;overflow-wrap:break-word}.review-explanation-icon{margin-right:0.5rem}.result-actions{padding-top:1.5rem;border-top:2px solid #f7fafc}@media(max-width:600px){body{padding:1rem 0.5rem}.header{padding:2rem 1rem;border-radius:16px}.header h1{font-size:1.8rem}.header p{font-size:1rem}.question-card{padding:1.5rem;border-radius:16px}.question-text{font-size:1.2rem}.nav-btn{padding:0.85rem 1.5rem;font-size:0.9rem;width:100%;justify-content:center}.final-icon,.result-icon{font-size:4rem}.final-title,.result-title{font-size:1.5rem}.final-actions,.result-actions{padding:1rem;flex-direction:column}.option-label{padding:1rem}.option-text{font-size:0.95rem}}';

        var fullHTML = '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"><title>' + escapeHtml(title) + '</title><style>' + cssContent + '</style></head><body><div class="header"><h1>' + escapeHtml(title) + '</h1></div>' + navRadios + '\n<div class="quiz-container">' + questionsHTML + finalScreen + resultScreen + '</div></body></html>';

        htmlOutput.value = fullHTML;
        generatedHtmlModal.classList.add('active');
    }

    function copyToClipboard(text, button) {
        var originalText = button.textContent;
        
        // Попытка 1: Современный Clipboard API
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function() {
                button.textContent = '✅ Скопировано!';
                setTimeout(function() { button.textContent = originalText; }, 2000);
            }).catch(function(err) {
                console.log('Clipboard API failed:', err);
                fallbackCopy(text, button, originalText);
            });
        } else {
            fallbackCopy(text, button, originalText);
        }
        
        function fallbackCopy(text, button, originalText) {
            // Попытка 2: execCommand с textarea
            try {
                var textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.top = '0';
                textarea.style.left = '0';
                textarea.style.width = '2em';
                textarea.style.height = '2em';
                textarea.style.padding = '0';
                textarea.style.border = 'none';
                textarea.style.outline = 'none';
                textarea.style.boxShadow = 'none';
                textarea.style.background = 'transparent';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.focus();
                textarea.select();
                
                var successful = document.execCommand('copy');
                if (successful) {
                    button.textContent = '✅ Скопировано!';
                    setTimeout(function() { button.textContent = originalText; }, 2000);
                } else {
                    throw new Error('execCommand failed');
                }
                document.body.removeChild(textarea);
            } catch (err) {
                // Попытка 3: выделение текста в prompt (последний вариант)
                try {
                    window.prompt('Скопируйте текст вручную (Ctrl+C, Enter):', text);
                    button.textContent = '✅ Скопировано!';
                    setTimeout(function() { button.textContent = originalText; }, 2000);
                } catch (promptErr) {
                    showToastFunc('Не удалось скопировать. Выделите текст вручную.', 'error');
                }
            }
        }
    }

    function downloadHtml() {
        var htmlContent = htmlOutput.value;
        var quizTitle = quizTitleInput.value.trim() || 'Квиз';

        var blob = new Blob([htmlContent], {type: 'text/html'});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = quizTitle.replace(/[^a-zа-яё0-9]/gi, '_') + '.html';
        a.click();
        URL.revokeObjectURL(url);

        showToastFunc('Файл скачан', 'success');
    }

    function escapeHtml(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function updateStats() {
        if (totalQuestionsEl) {
            totalQuestionsEl.textContent = questions.length;
        }
    }

    function showToastFunc(message, type) {
        var toast = document.createElement('div');
        toast.textContent = message;
        toast.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:' + (type === 'error' ? '#fc8181' : '#68d391') + ';color:white;padding:12px 24px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:10000;font-weight:500;animation:toastFadeIn 0.3s ease-out;';
        document.body.appendChild(toast);

        setTimeout(function() {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(function() {
                document.body.removeChild(toast);
            }, 300);
        }, 2000);
    }

    // Экспортируем функции в глобальную область видимости для доступа из HTML
    window.editQuestion = function(idx) {
        openQuestionModal(idx);
    };
    window.deleteQuestion = function(idx) {
        showDeleteConfirm(idx);
    };
    window.openQuestionModal = openQuestionModal;
    window.showDeleteConfirm = showDeleteConfirm;
    window.saveQuestion = saveQuestion;
    window.closeQuestionModal = closeQuestionModal;
    window.newQuiz = newQuiz;
    window.saveQuiz = saveQuiz;
    window.generateHtmlCode = generateHtmlCode;
    window.downloadHtml = downloadHtml;
    window.copyToClipboard = copyToClipboard;
    window.showToast = showToastFunc;

    // API для AI-модуля (ai.js): добавление вопросов в текущий квиз
    window.QuizBuilder = {
        addQuestion: function(q) {
            questions.push({
                text: q.text,
                options: q.options.map(function(o) {
                    return { text: o.text, isCorrect: !!o.isCorrect };
                }),
                explanation: q.explanation || ''
            });
            renderQuestionsList();
            saveToLocalStorage();
        },
        getQuestions: function() {
            return questions.slice();
        },
        getCount: function() {
            return questions.length;
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
