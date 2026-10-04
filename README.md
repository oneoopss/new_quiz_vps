# AI-генератор квизов

Модуль AI-генерации обучающих квизов для сайта-конструктора квизов.
По выбранному разделу документации (Яндекс.Справка NMaps) генерирует пачку
вопросов с подтверждением фактов источником, проверяет их и передаёт куратору
на быстрый отбор.

## Структура

```
html.html / js.js / ai.js   — фронтенд (конструктор квизов + AI-панель)
backend/                    — FastAPI backend (генерация, база знаний, API)
deploy/                     — файлы для деплоя на VPS (nginx, systemd, инструкция)
Dockerfile, docker-compose.yml
референс вопросов.txt       — 118 reference-вопросов (образцы стиля, few-shot)
```

## Быстрый старт (локально)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example ..\.env                             # заполните LLM_API_KEY
python -m app.ingest --limit 5                        # ингест справки (LLM извлечёт знания)
python -m uvicorn app.main:app --app-dir . --port 8000
```

Откройте http://localhost:8000.

## Деплой на VPS

См. [deploy/README-DEPLOY.md](deploy/README-DEPLOY.md) (Docker и systemd варианты).

## Как это работает

1. **Ингест** (`POST /api/ingest` или `python -m app.ingest`): скачивает
   Markdown-страницы справки (llms.txt), строит секции/чанки, LLM извлекает
   правила, ограничения и списки допустимых значений (знание → документ → фрагмент).
2. **Генерация** (`POST /api/generate`):
   план покрытия (N разных знаний) → параллельная генерация пачками →
   детерминированные проверки (код) → дедупликация → LLM-Critic
   (accept/repair/reject) → точечный ремонт → вопросы с источником.
3. **Куратор** в AI-панели: просматривает карточки (вопрос, варианты, источник,
   обоснование) и принимает / правит / перегенерирует / удаляет вопросы.
   Принятые попадают в квиз в формате конструктора.

Бюджет: 7–9 LLM-вызовов и ~3–5 минут на пачку из 15 вопросов.

## Тесты

```bash
cd backend
python -m pytest tests
```
