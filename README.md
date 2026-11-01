# UlianaMAIL 📧

**UlianaMAIL** — это легкий, быстрый и портативный десктопный почтовый клиент с поддержкой офлайн-режима.
**UlianaMAIL** is a lightweight, fast, and portable desktop email client with local offline storage.

---

## 🇷🇺 Описание (Russian)

Программа создана для тех, кому нужен полный контроль над своей почтой. Все письма сохраняются в локальную базу данных SQLite, что позволяет мгновенно открывать список писем, искать по архиву и читать корреспонденцию даже без подключения к интернету.

### 🌟 Основные возможности:
*   **Мультиаккаунт:** Поддержка неограниченного количества ящиков (Яндекс, Gmail, Mail.ru и др.).
*   **Офлайн-база:** Заголовки и тексты писем кэшируются локально. Доступ к переписке без интернета.
*   **Умные метки:** Создавайте цветные метки с правилами (по отправителю или теме). Письма автоматически маркируются при получении.
*   **Синхронизация в фоне:** Программа проверяет новые письма в фоне (когда окно свернуто) и показывает уведомления в системном трее.
*   **Экономия места:** Вложения и HTML-код писем скачиваются с сервера только по запросу (по клику), что экономит место на диске.
*   **Портативность:** Все настройки, база данных и ключи шифрования хранятся в папке с программой. Легко переносится на флешке.
*   **Безопасность:** Пароли от почтовых ящиков шифруются алгоритмом Fernet.

### 🛠 Установка и запуск:
1. Перейдите в раздел **Releases** (справа на странице).
2. Скачайте последний ZIP-архив (например, `UlianaMAIL_v1.0.zip`).
3. Распакуйте архив в любую папку.
4. Запустите `UlianaMAIL.exe`.

---

## 🇬🇧 Description (English)

The application is designed for those who want complete control over their email. All emails are stored in a local SQLite database, allowing you to instantly open the email list, search through the archive, and read correspondence even without an internet connection.

### 🌟 Key Features:
*   **Multi-account:** Support for an unlimited number of email accounts (Yandex, Gmail, Mail.ru, etc.).
*   **Offline Database:** Email headers and bodies are cached locally. Access your correspondence without the internet.
*   **Smart Labels:** Create colored labels with custom rules (by sender or subject). Emails are automatically tagged upon arrival.
*   **Background Sync:** The app checks for new emails in the background (when minimized) and shows system tray notifications.
*   **Space Saving:** Attachments and HTML content are downloaded from the server on-demand (by click), saving disk space.
*   **Portability:** All settings, the database, and encryption keys are stored in the app folder. Easily portable on a USB drive.
*   **Security:** Email passwords are encrypted using the Fernet algorithm.

### 🛠 Installation & Usage:
1. Go to the **Releases** section (on the right side of the page).
2. Download the latest ZIP archive (e.g., `UlianaMAIL_v1.0.zip`).
3. Extract the archive to any folder.
4. Run `UlianaMAIL.exe`.

---

## 💻 Technologies / Технологии
*   **Language:** Python 3
*   **GUI:** PySide6 (Qt for Python)
*   **Database:** SQLite 3
*   **Protocols:** IMAP4, SMTP

## ⚠️ Disclaimer / Отказ от ответственности
This software is provided "as is". Always keep backups of your important data. The author is not responsible for any data loss or issues with email providers.
Программа предоставляется "как есть". Всегда делайте резервные копии важных данных. Автор не несет ответственности за потерю данных или проблемы с почтовыми провайдерами.
