# Деплой на VPS

## Вариант 1 — Docker (рекомендуется)

Требования: Docker + Docker Compose плагин (Ubuntu: `apt install docker.io docker-compose-v2`).

```bash
# 1. Скопируйте проект на сервер, например в /opt/quiz
cd /opt/quiz

# 2. Создайте .env с ключом LLM (шаблон: backend/.env.example)
cp backend/.env.example .env
nano .env          # заполните LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

# 3. Соберите и запустите
docker compose up -d --build

# 4. Проверьте
curl http://localhost:8000/api/health   # {"ok":true}
```

Приложение будет доступно на `http://<IP-сервера>:8000`.

После первого запуска откройте страницу и нажмите **«📚 Загрузить документацию»**
(скачает справку NMaps и извлечёт знания; выполняется один раз, повторно — только
при обновлении документации).

Данные (SQLite) хранятся в `./data/` на сервере — достаточно бэкапить эту папку.

## Вариант 2 — без Docker (systemd)

```bash
sudo apt install python3-venv python3-pip
cd /opt/quiz
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cp backend/.env.example .env   # заполните ключи
sudo cp deploy/quiz-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quiz-backend
```

## HTTPS (опционально)

Для домена поставьте nginx (шаблон — `deploy/nginx.conf`) и certbot:

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/quiz.conf
sudo ln -s /etc/nginx/sites-available/quiz.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d quiz.example.com
```

## Обновление

```bash
cd /opt/quiz
git pull            # или повторное копирование файлов
docker compose up -d --build
```
