import sys
import os
import sqlite3
import imaplib
import smtplib
import email
import email.utils
import re
import html
import time
import base64
import webbrowser
import tempfile
import mimetypes
import uuid
from datetime import datetime, timedelta
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from cryptography.fernet import Fernet
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                               QVBoxLayout, QPushButton, QLabel, QScrollArea, 
                               QSplitter, QTextEdit, QTextBrowser, QListWidget, QListWidgetItem,
                               QFrame, QInputDialog, QMessageBox, QDialog, QMenu,
                               QLineEdit, QFormLayout, QDialogButtonBox,
                               QTreeWidget, QTreeWidgetItem, QTabWidget, QCheckBox,
                               QSpinBox, QComboBox, QFileDialog, QAbstractItemView,
                               QSystemTrayIcon, QStyle, QColorDialog, QSizePolicy, QProgressBar, QToolBar)
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QObject, QBuffer, QIODevice, QTranslator, QLibraryInfo, QUrl, QByteArray
from PySide6.QtGui import (QIcon, QFont, QAction, QCloseEvent, QColor, QTextCursor, 
                           QTextCharFormat, QDesktopServices, QTextDocument, QTextImageFormat, QImage)
from PySide6.QtNetwork import QLocalSocket, QLocalServer

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_icon_path():
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, "app.ico")
    return os.path.join(get_base_dir(), "app.ico")

BASE_DIR = get_base_dir()
DB_PATH = os.path.join(BASE_DIR, "mail.db")
KEY_PATH = os.path.join(BASE_DIR, "secret.key")
ICON_PATH = get_icon_path()
TEMP_ATT_DIR = os.path.join(tempfile.gettempdir(), "UlianaMAIL")

if not os.path.exists(TEMP_ATT_DIR):
    os.makedirs(TEMP_ATT_DIR, exist_ok=True)

def gc_temp_files():
    """Удаляет временные файлы старше 1 дня из TEMP_ATT_DIR."""
    try:
        now = time.time()
        for fname in os.listdir(TEMP_ATT_DIR):
            fpath = os.path.join(TEMP_ATT_DIR, fname)
            try:
                if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > 24 * 3600:
                    os.remove(fpath)
            except Exception:
                pass
    except Exception:
        pass

def get_or_create_key():
    if not os.path.exists(KEY_PATH):
        key = Fernet.generate_key()
        with open(KEY_PATH, "wb") as key_file:
            key_file.write(key)
    else:
        with open(KEY_PATH, "rb") as key_file:
            key = key_file.read()
    return key

cipher = Fernet(get_or_create_key())

def encrypt_password(password: str) -> str:
    return cipher.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password: str) -> str:
    try:
        return cipher.decrypt(encrypted_password.encode()).decode()
    except Exception:
        return ""

def format_size(size_bytes, lang="RU"):
    if size_bytes is None: size_bytes = 0
    if lang == "RU":
        if size_bytes < 1024: return f"{size_bytes} Б"
        elif size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} КБ"
        elif size_bytes < 1024 * 1024 * 1024: return f"{size_bytes / (1024 * 1024):.1f} МБ"
        else: return f"{size_bytes / (1024 * 1024 * 1024):.2f} ГБ"
    else:
        if size_bytes < 1024: return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024: return f"{size_bytes / (1024 * 1024):.1f} MB"
        else: return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def resolve_imap_folder(mail, code):
    """Определяет реальное имя папки на сервере по канонич. коду (INBOX/Sent/Spam)."""
    if code == "INBOX":
        return "INBOX"
    try:
        status, folder_list = mail.list()
        if status != 'OK':
            return code
        for item in folder_list:
            try:
                line = item.decode('utf-8', errors='replace')
            except Exception:
                line = str(item)
            m = re.match(r'\(([^)]*)\)\s+(?:NIL|"[^"]*")\s+(?:"([^"]*)"|(\S+))', line)
            if not m:
                continue
            attrs = m.group(1).lower()
            name = m.group(2) if m.group(2) is not None else m.group(3)
            name_lower = name.lower()
            if code == "Spam":
                if ('\\spam' in attrs or '\\junk' in attrs
                        or 'spam' in name_lower or 'junk' in name_lower
                        or 'спам' in name_lower):
                    return name
            if code == "Sent":
                if ('\\sent' in attrs
                        or name_lower == 'sent'
                        or 'отправ' in name_lower
                        or 'sent' in name_lower):
                    return name
    except Exception:
        pass
    return code

def parse_raw_email_bytes(raw_bytes):
    """Универсальный парсер: возвращает (subject, from_, to_, cc_, date_, body_text, body_html, attachments)."""
    msg = email.message_from_bytes(raw_bytes)
    subject, from_, to_, cc_, date_ = parse_email_headers(msg)
    
    body_text = None
    body_html = None
    attachments = []
    cid_map = {}
    
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition"))
            content_type = part.get_content_type()
            content_id = part.get("Content-ID")
            
            if content_id:
                cid = content_id.strip('<>')
                payload = part.get_payload(decode=True)
                if payload:
                    b64_data = base64.b64encode(payload).decode('utf-8')
                    cid_map[cid] = f"data:{content_type};base64,{b64_data}"
                    
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    payload = part.get_payload(decode=True)
                    if payload:
                        attachments.append({'filename': decode_mime_words(filename), 'data': payload})
            elif "attachment" not in content_disposition:
                if content_type == "text/plain" and body_text is None:
                    try:
                        body_text = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                    except Exception:
                        pass
                elif content_type == "text/html" and body_html is None:
                    try:
                        body_html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                    except Exception:
                        pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')
                if msg.get_content_type() == "text/plain":
                    body_text = text
                elif msg.get_content_type() == "text/html":
                    body_html = text
        except Exception:
            pass
    
    if body_html and cid_map:
        for cid, data_uri in cid_map.items():
            body_html = body_html.replace(f'src="cid:{cid}"', f'src="{data_uri}"')
            body_html = body_html.replace(f"src='cid:{cid}'", f"src='{data_uri}'")
            body_html = body_html.replace(f'src="{cid}"', f'src="{data_uri}"')
            body_html = body_html.replace(f"src='{cid}'", f"src='{data_uri}'")
    
    if not body_text and body_html:
        clean_html = re.sub(r'<(style|script)[^>]*>.*?</\1>', ' ', body_html, flags=re.DOTALL | re.IGNORECASE)
        clean_html = re.sub(r'<br\s*/?>', '\n', clean_html, flags=re.IGNORECASE)
        clean_html = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n\n', clean_html, flags=re.IGNORECASE)
        body_text = re.sub(r'<[^>]+>', '', clean_html)
        body_text = html.unescape(body_text)
        body_text = re.sub(r'[ \t]+', ' ', body_text)
        body_text = re.sub(r'\n\s*\n', '\n\n', body_text)
        body_text = body_text.strip()
    
    if not body_text:
        body_text = "HTML-письмо без текста. Нажмите 'Открыть в браузере' для просмотра."
    
    return subject, from_, to_, cc_, date_, body_text, body_html, attachments

TRANSLATIONS = {
    "RU": {
        "app_title": "UlianaMAIL", "compose": "✉️ Написать", "refresh": "🔄 Проверить почту",
        "settings": "⚙️ Настройки", "inbox": "Входящие", "sent": "Отправленные", "spam": "Спам",
        "important": "⭐ Важные", "unread": "✉️ Непрочитанные", "attachments_folder": "📎 С вложениями", "drafts_folder": "📝 Черновики", "templates_folder": "📋 Шаблоны", "contacts_title": "Контакты",
        "copy_email_tooltip": "Копировать email",
        "contact_search_ph": "Поиск по контактам...", "add_contact": "+", "import_vcf": "Импорт", "export_vcf": "Экспорт",
        "no_contacts": "Контакты не найдены", "no_email_err": "У контакта нет указан email.",
        "search_ph": "Поиск за 3 года (нажмите Enter)...", "bulk_del": "🗑️ Удалить выделенные",
        "mark_read_selected": "✅ Отметить прочитанными", "mark_unread_selected": "✉️ Отметить непрочитанными",
        "reply": "↩️ Ответить", "forward": "➡️ Переслать", "src_view": "👁️ Исходник", "src_back": "✉️ К письму",
        "open_browser": "🌐 Открыть в браузере", "save_imp": "⭐ В важные", "remove_imp": "☆ Убрать из важных",
        "mark_unread": "✉️ Отметить как непрочитанное",
        "copy_email": "📋 Копировать", "create_contact": "👤 В контакты", "copied_toast": "Скопировано!",
        "select_email": "Выберите письмо", "loading": "⏳ Загрузка...", "empty_folder": "В этой папке нет писем.",
        "searching": "⏳ Поиск...", "not_found": "Писем не найдено.", "save_att": "Сохранить файл", "saved_ok": "Файл сохранен:",
        "about_title": "О программе", "lang_btn": "EN", "close": "Закрыть", "yes_btn": "Да", "no_btn": "Нет",
        "cc_display": "Копия:", "dlg_add_acc_title": "Добавить аккаунт", "dlg_edit_acc_title": "Редактировать аккаунт",
        "dlg_email": "Email:", "dlg_pass": "Пароль:", "dlg_imap_srv": "IMAP сервер:", "dlg_imap_port": "IMAP порт:",
        "dlg_smtp_srv": "SMTP сервер:", "dlg_smtp_port": "SMTP порт:", "dlg_save": "Сохранить", "dlg_cancel": "Отмена", "dlg_ok": "ОК",
        "dlg_compose_title": "Написание письма", "dlg_to": "Кому:", "dlg_cc": "Копия (через запятую):", "dlg_subj": "Тема:",
        "dlg_from": "От кого:", "dlg_sig": "Подпись:", "dlg_attach": "📎 Прикрепить файл", "dlg_send": "✉️ Отправить", "dlg_no_sig": "Без подписи",
        "dlg_save_draft": "📝 В черновик", "dlg_save_template": "📋 В шаблоны", "dlg_update_template": "📋 Обновить шаблон",
        "draft_saved": "Черновик сохранен!", "template_saved": "Шаблон сохранен!",
        "dlg_settings_title": "Настройки", "dlg_tab_sigs": "Подписи", "dlg_tab_accs": "Аккаунты", "dlg_tab_labels": "Метки",
        "dlg_add": "+ Добавить", "dlg_edit": "✏️ Изменить", "dlg_del": "❌ Удалить",
        "dlg_sig_title": "Подпись", "dlg_sig_name": "Название подписи:", "dlg_sig_text": "Текст подписи:",
        "dlg_sig_default": "Использовать по умолчанию", "dlg_contact_title": "Контакт", "dlg_contact_name": "Имя:",
        "dlg_contact_email": "Email:", "dlg_contact_phone": "Телефон:", "dlg_contact_notes": "Заметки:",
        "dlg_label_title": "Метка", "dlg_label_name": "Название метки:", "dlg_label_color": "Цвет фона:",
        "dlg_label_emails": "Email отправителей (через запятую):", "dlg_label_subject": "Текст в теме:",
        "imp_saved": "Письмо сохранено в Важные!", "removed_imp": "Убрано из Важных.",
        "del_confirm": "Удалить выделенные письма?",
        "acc_del_confirm": "Удалить этот аккаунт и все его локальные данные?",
        "label_del_confirm": "Удалить эту метку?",
        "reply_choice_title": "Ответ на письмо", "reply_choice_text": "В письме были получатели копии.\nКому отправить ответ?",
        "reply_only_sender": "Только отправителю", "reply_to_all": "Ответить всем", "email_sent": "Письмо успешно отправлено!",
        "email_sent_no_append": "Письмо отправлено, но не удалось сохранить копию в папку «Отправленные» на сервере.\nВозможно, папка не существует или сервер не поддерживает эту операцию.",
        "email_err": "Ошибка отправки:", "tray_msg_title": "Новое письмо",
        "sync_started": "Синхронизация почты...", "sync_cancel": "Отменить", "sync_done": "Синхронизация завершена",
        "fetching_html": "⏳ Скачивание HTML с сервера...", "fetching_att": "⏳ Скачивание файла с сервера...",
        "sync_cancelled": "Синхронизация отменена.", "space_limit_reached": "Достигнут лимит хранилища (10 ГБ). Удалены самые старые письма.",
        "load_older": "📥 Скачать более старые письма", "no_more_emails": "Более старых писем не найдено.",
        "link_text": "Текст ссылки:", "link_url": "URL:", "insert_link": "Вставить ссылку", "make_link": "Сделать ссылкой", "insert_img": "Вставить картинку",
        "ctx_undo": "Отменить", "ctx_redo": "Повторить", "ctx_cut": "Вырезать", "ctx_copy": "Копировать", "ctx_paste": "Вставить", "ctx_del": "Удалить", "ctx_all": "Выделить всё",
        "file_limit_warn": "Рекомендуется общий размер файлов не более 10-25 МБ.",
        "err_no_to": "Пожалуйста, укажите адрес получателя (Кому)!",
        "err_no_subj": "Вы не указали тему письма. Отправить письмо без темы?",
        "html_banner": "<div style='color: #9aa0a6; font-size: 11px; border-bottom: 1px solid #e8eaed; padding-bottom: 10px; margin-bottom: 10px; font-family: sans-serif;'>Письмо содержит HTML-форматирование. Для полноценного просмотра нажмите «Открыть в браузере».</div>",
        "btn_insert_link": "🔗 Вставить ссылку",
        "btn_make_link": "Сделать ссылкой",
        "btn_insert_img": "🖼️ Картинка",
        "warn_title": "Внимание",
        "err_title": "Ошибка",
        "success_title": "Успех",
        "info_title": "Информация",
        "confirm_title": "Подтверждение",
        "select_text_to_link": "Сначала выделите текст, который хотите сделать ссылкой!",
        "img_load_err": "Не удалось загрузить картинку.",
        "total_size_label": "Общий размер: {size}. Рекомендуется не более 10-25 МБ.",
        "sync_starting": "⏳ Синхронизация...",
        "sync_progress_fmt": "⏳ Синхронизация: {current}/{total}",
        "sync_acc_status_fmt": "⏳ Синхронизация: {email}",
        "sync_error_msg_fmt": "Ошибка синхронизации: {err}",
        "loading_archive": "⏳ Загрузка архива...",
        "loading_archive_progress_fmt": "⏳ Загрузка архива ({current}/{total})...",
        "local_search_not_found": "Ничего не найдено в локальной базе. Нажмите «Проверить почту», чтобы скачать больше писем.",
        "dbl_click_to_edit": "Двойной клик для редактирования",
        "no_html_version": "В этом письме нет HTML-версии.",
        "load_data_err_fmt": "Не удалось загрузить данные.\nВозможно, письмо было удалено с сервера.\n\n{err}",
        "browser_open_err_fmt": "Не удалось открыть в браузере:\n{err}",
        "import_success_fmt": "Импортировано контактов: {count}",
        "export_success_fmt": "Экспортировано контактов: {count}",
        "import_err_fmt": "Не удалось импортировать: {err}",
        "export_err_fmt": "Не удалось экспортировать: {err}",
        "tray_show": "Развернуть",
        "tray_quit": "Выход",
        "about_content": "<h3>UlianaMAIL</h3><p><b>Спроектировано:</b> Дмитрий Анохин, 2026 год.<br><b>Контакты:</b> <a href='mailto:d.anokhine@yandex.ru' style='color: #1a73e8;'>d.anokhine@yandex.ru</a><br><b>При участии:</b> ИИ-ассистент DeepSeek.</p><p style='color: #666; font-size: 12px;'><b>Конфиденциальность:</b> Все данные хранятся локально в зашифрованном виде. Автор не имеет к ним доступа.</p>",
        "spam_loading": "⏳ Загрузка спама...",
        "spam_empty": "В папке Спам нет писем.",
        "spam_load_error": "Не удалось загрузить спам:",
        "spam_searching": "⏳ Поиск на сервере...",
        "spam_search_empty": "В спаме по вашему запросу ничего не найдено.",
        "saving_to_important": "⏳ Сохранение в Важные...",
        "saving_attachment_fmt": "Скачивание вложений ({current}/{total}): {filename}",
        "save_to_imp_err_fmt": "Не удалось сохранить: {err}",
        "fetch_body_err_fmt": "Не удалось загрузить письмо: {err}",
        "fetch_body_title": "⏳ Загрузка письма..."
    },
    "EN": {
        "app_title": "UlianaMAIL", "compose": "✉️ Compose", "refresh": "🔄 Check Mail", "settings": "⚙️ Settings",
        "inbox": "Inbox", "sent": "Sent", "spam": "Spam", "important": "⭐ Important", "unread": "✉️ Unread", "attachments_folder": "📎 With Attachments",
        "drafts_folder": "📝 Drafts", "templates_folder": "📋 Templates",
        "copy_email_tooltip": "Copy email",
        "contacts_title": "Contacts", "contact_search_ph": "Search contacts...", "add_contact": "+", "import_vcf": "Import",
        "export_vcf": "Export", "no_contacts": "No contacts found", "no_email_err": "Contact has no email specified.",
        "search_ph": "Search last 3 years (press Enter)...", "bulk_del": "🗑️ Delete Selected", "mark_read_selected": "✅ Mark as read",
        "mark_unread_selected": "✉️ Mark as unread", "reply": "↩️ Reply", "forward": "➡️ Forward", "src_view": "👁️ Source",
        "src_back": "✉️ To Email", "open_browser": "🌐 Open in browser", "save_imp": "⭐ To Important", "remove_imp": "☆ Remove from Important", "mark_unread": "✉️ Mark as unread",
        "copy_email": "📋 Copy", "create_contact": "👤 To contacts", "copied_toast": "Copied!", "select_email": "Select an email",
        "loading": "⏳ Loading...", "empty_folder": "No emails in this folder.", "searching": "⏳ Searching...", "not_found": "No emails found.",
        "save_att": "Save File", "saved_ok": "File saved:", "about_title": "About", "lang_btn": "RU", "close": "Close",
        "yes_btn": "Yes", "no_btn": "No", "cc_display": "Cc:", "dlg_add_acc_title": "Add Account", "dlg_edit_acc_title": "Edit Account",
        "dlg_email": "Email:", "dlg_pass": "Password:", "dlg_imap_srv": "IMAP Server:", "dlg_imap_port": "IMAP Port:",
        "dlg_smtp_srv": "SMTP Server:", "dlg_smtp_port": "SMTP Port:", "dlg_save": "Save", "dlg_cancel": "Cancel", "dlg_ok": "OK",
        "dlg_compose_title": "Compose Email", "dlg_to": "To:", "dlg_cc": "Cc (comma separated):", "dlg_subj": "Subject:",
        "dlg_from": "From:", "dlg_sig": "Signature:", "dlg_attach": "📎 Attach File", "dlg_send": "✉️ Send", "dlg_no_sig": "No signature",
        "dlg_save_draft": "📝 To Drafts", "dlg_save_template": "📋 To Templates", "dlg_update_template": "📋 Update Template",
        "draft_saved": "Draft saved!", "template_saved": "Template saved!",
        "dlg_settings_title": "Settings", "dlg_tab_sigs": "Signatures", "dlg_tab_accs": "Accounts", "dlg_tab_labels": "Labels",
        "dlg_add": "+ Add", "dlg_edit": "✏️ Edit", "dlg_del": "❌ Delete", "dlg_sig_title": "Signature",
        "dlg_sig_name": "Signature name:", "dlg_sig_text": "Signature text:", "dlg_sig_default": "Use as default",
        "dlg_contact_title": "Contact", "dlg_contact_name": "Name:", "dlg_contact_email": "Email:", "dlg_contact_phone": "Phone:",
        "dlg_contact_notes": "Notes:", "dlg_label_title": "Label", "dlg_label_name": "Label name:", "dlg_label_color": "Background color:",
        "dlg_label_emails": "Sender emails (comma separated):", "dlg_label_subject": "Text in subject:",
        "imp_saved": "Email saved to Important!", "removed_imp": "Removed from Important.",
        "del_confirm": "Delete selected emails?",
        "acc_del_confirm": "Delete this account and all local data?",
        "label_del_confirm": "Delete this label?",
        "reply_choice_title": "Reply to Email", "reply_choice_text": "This email had CC recipients.\nWho should receive the reply?",
        "reply_only_sender": "Reply to sender", "reply_to_all": "Reply to all", "email_sent": "Email sent successfully!",
        "email_sent_no_append": "Email sent, but failed to save a copy to the Sent folder on the server.\nThe folder may not exist or the server may not support this operation.",
        "email_err": "Send error:", "tray_msg_title": "New Email",
        "sync_started": "Email synchronization...", "sync_cancel": "Cancel", "sync_done": "Synchronization complete",
        "fetching_html": "⏳ Downloading HTML from server...", "fetching_att": "⏳ Downloading file from server...",
        "sync_cancelled": "Synchronization cancelled.", "space_limit_reached": "Storage limit (10 GB) reached. Oldest emails deleted.",
        "load_older": "📥 Load older emails", "no_more_emails": "No older emails found.",
        "link_text": "Link text:", "link_url": "URL:", "insert_link": "Insert link", "make_link": "Make link", "insert_img": "Insert image",
        "ctx_undo": "Undo", "ctx_redo": "Redo", "ctx_cut": "Cut", "ctx_copy": "Copy", "ctx_paste": "Paste", "ctx_del": "Delete", "ctx_all": "Select All",
        "file_limit_warn": "Recommended total file size no more than 10-25 MB.",
        "err_no_to": "Please specify the recipient (To)!",
        "err_no_subj": "You didn't specify a subject. Send without subject?",
        "html_banner": "<div style='color: #9aa0a6; font-size: 11px; border-bottom: 1px solid #e8eaed; padding-bottom: 10px; margin-bottom: 10px; font-family: sans-serif;'>This email contains HTML formatting. For full view click 'Open in browser'.</div>",
        "btn_insert_link": "🔗 Insert link",
        "btn_make_link": "Make link",
        "btn_insert_img": "🖼️ Image",
        "warn_title": "Warning",
        "err_title": "Error",
        "success_title": "Success",
        "info_title": "Information",
        "confirm_title": "Confirmation",
        "select_text_to_link": "First select the text you want to make a link!",
        "img_load_err": "Failed to load image.",
        "total_size_label": "Total size: {size}. Recommended no more than 10-25 MB.",
        "sync_starting": "⏳ Synchronizing...",
        "sync_progress_fmt": "⏳ Synchronizing: {current}/{total}",
        "sync_acc_status_fmt": "⏳ Syncing: {email}",
        "sync_error_msg_fmt": "Sync error: {err}",
        "loading_archive": "⏳ Loading archive...",
        "loading_archive_progress_fmt": "⏳ Loading archive ({current}/{total})...",
        "local_search_not_found": "Nothing found in local database. Click 'Check Mail' to download more emails.",
        "dbl_click_to_edit": "Double-click to edit",
        "no_html_version": "This email has no HTML version.",
        "load_data_err_fmt": "Failed to load data.\nThe email may have been deleted from the server.\n\n{err}",
        "browser_open_err_fmt": "Failed to open in browser:\n{err}",
        "import_success_fmt": "Contacts imported: {count}",
        "export_success_fmt": "Contacts exported: {count}",
        "import_err_fmt": "Import failed: {err}",
        "export_err_fmt": "Export failed: {err}",
        "tray_show": "Show",
        "tray_quit": "Exit",
        "about_content": "<h3>UlianaMAIL</h3><p><b>Designed by:</b> Dmitry Anokhin, 2026.<br><b>Contact:</b> <a href='mailto:d.anokhine@yandex.ru' style='color: #1a73e8;'>d.anokhine@yandex.ru</a><br><b>With assistance of:</b> DeepSeek AI assistant.</p><p style='color: #666; font-size: 12px;'><b>Privacy:</b> All data is stored locally in encrypted form. The author has no access to it.</p>",
        "spam_loading": "⏳ Loading spam...",
        "spam_empty": "No emails in Spam folder.",
        "spam_load_error": "Failed to load spam:",
        "spam_searching": "⏳ Searching on server...",
        "spam_search_empty": "No emails found in Spam by your query.",
        "saving_to_important": "⏳ Saving to Important...",
        "saving_attachment_fmt": "Downloading attachments ({current}/{total}): {filename}",
        "save_to_imp_err_fmt": "Failed to save: {err}",
        "fetch_body_err_fmt": "Failed to load email: {err}",
        "fetch_body_title": "⏳ Loading email..."
    }
}

def init_db():
    if os.path.exists(DB_PATH):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='saved_emails'")
                if cursor.fetchone():
                    conn.close()
                    os.rename(DB_PATH, os.path.join(BASE_DIR, "mail_old.db"))
        except Exception:
            pass

    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, password_enc TEXT NOT NULL, imap_server TEXT NOT NULL, smtp_server TEXT NOT NULL, imap_port INTEGER DEFAULT 993, smtp_port INTEGER DEFAULT 465, is_active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS signatures (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, text TEXT NOT NULL, is_default INTEGER DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, phone TEXT, notes TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS labels (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, bg_color TEXT, text_color TEXT, filter_emails TEXT, filter_subject TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS cached_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            folder TEXT,
            uid TEXT,
            subject TEXT,
            from_addr TEXT,
            to_addr TEXT,
            cc_addr TEXT,
            date_str TEXT,
            body_text TEXT,
            body_html TEXT,
            has_attachments INTEGER DEFAULT 0,
            attachment_names TEXT,
            is_read INTEGER DEFAULT 0,
            is_important INTEGER DEFAULT 0,
            is_html INTEGER DEFAULT 0,
            UNIQUE(account_id, folder, uid)
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS drafts_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            account_id INTEGER,
            to_addr TEXT,
            cc_addr TEXT,
            subject TEXT,
            html_body TEXT,
            created_at TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS draft_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER,
            filename TEXT,
            data BLOB
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS cached_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            data BLOB NOT NULL
        )''')
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_acc_folder ON cached_emails(account_id, folder)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_read ON cached_emails(is_read)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cached_att_email ON cached_attachments(email_id)")
        
        try: cursor.execute("ALTER TABLE cached_emails ADD COLUMN is_html INTEGER DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE cached_emails ADD COLUMN body_html TEXT")
        except: pass
        conn.commit()

def get_russian_plural(n, form1, form2, form5):
    n = abs(n) % 100
    n1 = n % 10
    if 10 < n < 20: return form5
    if 1 < n1 < 5: return form2
    if n1 == 1: return form1
    return form5

def decode_mime_words(s):
    if not s: return ""
    decoded_fragments = decode_header(s)
    fragments = []
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            try:
                fragments.append(fragment.decode(encoding or 'utf-8', errors='replace'))
            except LookupError:
                fragments.append(fragment.decode('utf-8', errors='replace'))
        else:
            fragments.append(fragment)
    return "".join(fragments)

def parse_email_headers(msg):
    subject = decode_mime_words(msg.get("Subject", "No Subject"))
    from_ = decode_mime_words(msg.get("From", "Unknown"))
    to_ = decode_mime_words(msg.get("To", ""))
    cc_ = decode_mime_words(msg.get("Cc", ""))
    date_ = msg.get("Date", "")
    if date_:
        try: date_ = email.utils.parsedate_to_datetime(date_).strftime("%d.%m.%Y %H:%M")
        except: pass
    return subject, from_, to_, cc_, date_

def parse_email_body(msg):
    body_text = None
    body_html = None
    attachments = []
    
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition"))
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    attachments.append(decode_mime_words(filename))
            elif "attachment" not in content_disposition:
                ctype = part.get_content_type()
                if ctype == "text/plain" and body_text is None:
                    try: body_text = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                    except: pass
                elif ctype == "text/html" and body_html is None:
                    try: body_html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                    except: pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')
                if msg.get_content_type() == "text/plain":
                    body_text = text
                elif msg.get_content_type() == "text/html":
                    body_html = text
        except: pass
                
    if not body_text and body_html:
        clean_html = re.sub(r'<(style|script)[^>]*>.*?</\1>', ' ', body_html, flags=re.DOTALL | re.IGNORECASE)
        clean_html = re.sub(r'<br\s*/?>', '\n', clean_html, flags=re.IGNORECASE)
        clean_html = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n\n', clean_html, flags=re.IGNORECASE)
        body_text = re.sub(r'<[^>]+>', '', clean_html)
        body_text = html.unescape(body_text)
        body_text = re.sub(r'[ \t]+', ' ', body_text)
        body_text = re.sub(r'\n\s*\n', '\n\n', body_text)
        body_text = body_text.strip()
        
    if not body_text:
        body_text = "HTML-письмо без текста. Нажмите 'Открыть в браузере' для просмотра."
        
    return body_text, attachments, (1 if body_html else 0)

def show_custom_confirm(parent, title, text, lang):
    t = TRANSLATIONS[lang]
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle(title); msg.setText(text)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.button(QMessageBox.StandardButton.Yes).setText(t["yes_btn"])
    msg.button(QMessageBox.StandardButton.No).setText(t["no_btn"])
    return msg.exec() == QMessageBox.StandardButton.Yes

def get_contrast_color(hex_color):
    if not hex_color: return "#000000"
    hex_color = hex_color.lstrip('#')
    try:
        r = int(hex_color[0:2], 16); g = int(hex_color[2:4], 16); b = int(hex_color[4:6], 16)
    except Exception: return "#000000"
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.55 else "#ffffff"

def email_matches_label(from_addr, subject, filter_emails, filter_subject):
    sender_email = email.utils.parseaddr(from_addr or "")[1].lower()
    subject_lower = (subject or "").lower()
    emails_list = [e.strip().lower() for e in filter_emails.split(',') if e.strip()] if filter_emails else []
    text_cond = filter_subject.strip().lower() in subject_lower if filter_subject and filter_subject.strip() else True
    email_cond = sender_email in emails_list if emails_list else True
    return email_cond and text_cond

def shorten_text(text, max_len=18):
    if not text: return ""
    return text[:max_len - 3] + "..." if len(text) > max_len else text
# ==========================================
# ФОНОВЫЕ ПОТОКИ
# ==========================================

class SyncWorker(QThread):
    progress = Signal(int, int)
    account_status = Signal(str)
    finished = Signal(list)
    error = Signal(str)
    
    def __init__(self, accounts):
        super().__init__()
        self.accounts = accounts
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        new_notifications = []
        try:
            for acc in self.accounts:
                if self._is_cancelled: break
                acc_id, email_addr, pass_enc, imap_srv, imap_port = acc
                password = decrypt_password(pass_enc)
                
                self.account_status.emit(email_addr)
                
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM cached_emails WHERE account_id=? AND is_read=0", (acc_id,))
                    old_unread = cursor.fetchone()[0]
                
                try:
                    mail = imaplib.IMAP4_SSL(imap_srv, imap_port, timeout=30)
                    mail.login(email_addr, password)
                    
                    folders_to_sync = [("INBOX", 1000), ("Sent", 200)]
                    
                    for folder, limit in folders_to_sync:
                        if self._is_cancelled: break
                        real_name = resolve_imap_folder(mail, folder)
                        res, _ = mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
                        if res != 'OK': continue
                        
                        status, messages = mail.uid('search', None, 'ALL')
                        if status != 'OK': continue
                        
                        all_uids = messages[0].split()
                        all_uids = all_uids[-limit:]
                        total = len(all_uids)
                        live_uids = set(u.decode() for u in all_uids)
                        
                        # === Авто-очистка фантомов (D) ===
                        if live_uids:
                            try:
                                min_live = min(int(u) for u in live_uids)
                                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                                    cursor = conn.cursor()
                                    placeholders = ','.join('?' * len(live_uids))
                                    cursor.execute(
                                        f"SELECT id FROM cached_emails WHERE account_id=? AND folder=? AND CAST(uid AS INTEGER) >= ? AND uid NOT IN ({placeholders})",
                                        [acc_id, folder, min_live] + list(live_uids)
                                    )
                                    phantom_ids = [r[0] for r in cursor.fetchall()]
                                    for pid in phantom_ids:
                                        cursor.execute("DELETE FROM cached_attachments WHERE email_id=?", (pid,))
                                    if phantom_ids:
                                        cursor.execute(
                                            f"DELETE FROM cached_emails WHERE id IN ({','.join('?' * len(phantom_ids))})",
                                            phantom_ids
                                        )
                                    conn.commit()
                            except Exception as e:
                                print(f"Phantom cleanup error: {e}")
                        
                        for idx, uid in enumerate(reversed(all_uids)):
                            if self._is_cancelled: break
                            
                            uid_str = uid.decode()
                            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                                cursor = conn.cursor()
                                cursor.execute("SELECT id FROM cached_emails WHERE account_id=? AND folder=? AND uid=?", (acc_id, folder, uid_str))
                                if cursor.fetchone():
                                    self.progress.emit(idx + 1, total)
                                    continue

                            res, msg_data = mail.uid('fetch', uid, '(RFC822)')
                            if res != 'OK': continue
                            
                            raw_email = None
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    raw_email = response_part[1]
                                    break
                            
                            if not raw_email: continue
                            
                            msg = email.message_from_bytes(raw_email)
                            subject, from_, to_, cc_, date_ = parse_email_headers(msg)
                            body_text, attachments, is_html = parse_email_body(msg)
                            has_attach = 1 if attachments else 0
                            att_names = ", ".join(attachments)
                            
                            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                                cursor = conn.cursor()
                                cursor.execute('''
                                    INSERT OR REPLACE INTO cached_emails 
                                    (account_id, folder, uid, subject, from_addr, to_addr, cc_addr, date_str, body_text, has_attachments, attachment_names, is_read, is_html)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                                ''', (acc_id, folder, uid_str, subject, from_, to_, cc_, date_, body_text, has_attach, att_names, is_html))
                                conn.commit()
                            
                            time.sleep(0.1)
                            self.progress.emit(idx + 1, total)
                    
                    mail.logout()
                    
                    with sqlite3.connect(DB_PATH, timeout=30) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM cached_emails WHERE account_id=? AND is_read=0", (acc_id,))
                        new_unread = cursor.fetchone()[0]
                        
                    if new_unread > old_unread:
                        new_notifications.append((email_addr, new_unread - old_unread))
                        
                except Exception as e:
                    print(f"Error syncing {email_addr}: {e}")
                    self.error.emit(f"{email_addr}: {e}")
                    continue
            
            # === Авто-очистка при переполнении 10 ГБ ===
            if os.path.exists(DB_PATH):
                db_size = os.path.getsize(DB_PATH)
                if db_size > 10 * 1024 * 1024 * 1024:
                    with sqlite3.connect(DB_PATH, timeout=30) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM cached_emails WHERE is_important = 0 ORDER BY id ASC LIMIT 500")
                        old_ids = [row[0] for row in cursor.fetchall()]
                        for oid in old_ids:
                            cursor.execute("DELETE FROM cached_attachments WHERE email_id=?", (oid,))
                            cursor.execute("DELETE FROM cached_emails WHERE id=?", (oid,))
                        conn.commit()
                    with sqlite3.connect(DB_PATH, timeout=30) as conn:
                        conn.execute("VACUUM")
                        
            self.finished.emit(new_notifications)
            
        except Exception as e:
            self.error.emit(str(e))


class LoadOlderWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(bool)
    error = Signal(str)
    def __init__(self, acc_id, email_addr, password, imap_server, imap_port, folder):
        super().__init__()
        self.acc_id = acc_id
        self.email_addr = email_addr
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.folder = folder
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MIN(CAST(uid AS INTEGER)) FROM cached_emails WHERE account_id=? AND folder=?", (self.acc_id, self.folder))
                min_uid = cursor.fetchone()[0]
                
            if not min_uid:
                self.finished.emit(False)
                return

            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
            mail.login(self.email_addr, self.password)
            real_name = resolve_imap_folder(mail, self.folder)
            mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
            
            status, messages = mail.uid('search', None, 'ALL')
            if status != 'OK':
                mail.logout()
                self.finished.emit(False)
                return
                
            all_uids = messages[0].split()
            older_uids = []
            for uid in reversed(all_uids):
                if int(uid.decode()) < min_uid:
                    older_uids.append(uid)
                if len(older_uids) >= 500:
                    break
                    
            if not older_uids:
                mail.logout()
                self.finished.emit(False)
                return
                
            total = len(older_uids)
            for idx, uid in enumerate(older_uids):
                if self._is_cancelled: break
                
                res, msg_data = mail.uid('fetch', uid, '(RFC822)')
                if res != 'OK': continue
                
                raw_email = None
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        raw_email = response_part[1]
                        break
                
                if not raw_email: continue
                
                msg = email.message_from_bytes(raw_email)
                subject, from_, to_, cc_, date_ = parse_email_headers(msg)
                body_text, attachments, is_html = parse_email_body(msg)
                has_attach = 1 if attachments else 0
                att_names = ", ".join(attachments)
                uid_str = uid.decode()
                
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO cached_emails 
                        (account_id, folder, uid, subject, from_addr, to_addr, cc_addr, date_str, body_text, has_attachments, attachment_names, is_read, is_html)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ''', (self.acc_id, self.folder, uid_str, subject, from_, to_, cc_, date_, body_text, has_attach, att_names, is_html))
                    conn.commit()
                    
                time.sleep(0.1)
                self.progress.emit(idx + 1, total)
                
            mail.logout()
            self.finished.emit(True)
            
        except Exception as e:
            self.error.emit(str(e))


class FetchFullEmailWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)
    def __init__(self, email_addr, password, imap_server, imap_port, folder, uid):
        super().__init__()
        self.email_addr = email_addr
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.folder = folder
        self.uid = uid
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
            mail.login(self.email_addr, self.password)
            real_name = resolve_imap_folder(mail, self.folder)
            mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
            
            res, msg_data = mail.uid('fetch', self.uid.encode(), '(RFC822)')
            raw_bytes = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            mail.logout()
            
            if self._is_cancelled:
                self.error.emit("Cancelled")
                return

            if raw_bytes:
                subject, from_, to_, cc_, date_, body_text, body_html, attachments = parse_raw_email_bytes(raw_bytes)
                self.finished.emit({
                    'body_text': body_text,
                    'body_html': body_html,
                    'raw_bytes': raw_bytes,
                    'attachments': attachments,
                    'subject': subject,
                    'from_addr': from_,
                    'to_addr': to_,
                    'cc_addr': cc_,
                    'date_str': date_
                })
            else:
                self.error.emit("Failed to fetch email body. The email might have been deleted from the server.")
        except Exception as e:
            self.error.emit(str(e))


class MarkAsReadWorker(QThread):
    error = Signal(str)
    def __init__(self, acc_id, email_addr, password, imap_server, imap_port, folder, uid, is_read):
        super().__init__()
        self.acc_id = acc_id; self.email_addr = email_addr; self.password = password
        self.imap_server = imap_server; self.imap_port = imap_port; self.folder = folder; self.uid = uid; self.is_read = is_read
        
    def run(self):
        try:
            if self.folder != "Spam":
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE cached_emails SET is_read=? WHERE account_id=? AND folder=? AND uid=?", (1 if self.is_read else 0, self.acc_id, self.folder, self.uid))
                    conn.commit()
            
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
            mail.login(self.email_addr, self.password)
            real_name = resolve_imap_folder(mail, self.folder)
            mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
            if self.is_read:
                mail.uid('store', self.uid.encode(), '+FLAGS', '\\Seen')
            else:
                mail.uid('store', self.uid.encode(), '-FLAGS', '\\Seen')
            mail.logout()
        except Exception as e: self.error.emit(str(e))


class DeleteEmailsWorker(QThread):
    finished = Signal(bool)
    error = Signal(str)
    def __init__(self, email_addr, password, imap_server, imap_port, folder, uids):
        super().__init__()
        self.email_addr = email_addr; self.password = password
        self.imap_server = imap_server; self.imap_port = imap_port; self.folder = folder; self.uids = uids
    def run(self):
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
            mail.login(self.email_addr, self.password)
            real_name = resolve_imap_folder(mail, self.folder)
            mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
            mail.uid('store', ','.join(self.uids).encode(), '+FLAGS', '\\Deleted')
            mail.expunge()
            mail.logout()
            self.finished.emit(True)
        except Exception as e: self.error.emit(str(e))


class SendEmailWorker(QThread):
    finished = Signal(bool, str)
    error = Signal(str)
    def __init__(self, email_addr, password, smtp_server, smtp_port, to_addr, cc_addr, subject, html_body, attachments, inline_images=None, imap_server=None, imap_port=None):
        super().__init__()
        self.email_addr = email_addr; self.password = password
        self.smtp_server = smtp_server; self.smtp_port = smtp_port
        self.to_addr = to_addr; self.cc_addr = cc_addr; self.subject = subject; self.html_body = html_body; self.attachments = attachments
        self.inline_images = inline_images or {}
        self.imap_server = imap_server
        self.imap_port = imap_port

    def run(self):
        try:
            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=30)
            server.login(self.email_addr, self.password)
            
            msg = MIMEMultipart('related')
            msg['From'] = self.email_addr; msg['To'] = self.to_addr
            if self.cc_addr: msg['Cc'] = self.cc_addr
            msg['Subject'] = self.subject
            
            html_part = MIMEText(self.html_body, 'html', 'utf-8')
            msg.attach(html_part)
            
            for cid, img_data in self.inline_images.items():
                img = img_data[0]
                ba = QByteArray()
                buffer = QBuffer(ba)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buffer, "PNG")
                
                part = MIMEImage(ba.data(), 'png')
                part.add_header('Content-ID', f'<{cid}>')
                part.add_header('Content-Disposition', 'inline', filename=f'{cid}.png')
                msg.attach(part)
            
            for file_path in self.attachments:
                if os.path.exists(file_path):
                    filename = os.path.basename(file_path)
                    with open(file_path, "rb") as f:
                        data = f.read()
                    
                    ctype, encoding = mimetypes.guess_type(file_path)
                    if ctype is None or encoding is not None:
                        ctype = 'application/octet-stream'
                    
                    maintype, subtype = ctype.split('/', 1)
                    
                    if maintype == 'image':
                        part = MIMEImage(data, _subtype=subtype)
                    else:
                        part = MIMEApplication(data, _subtype=subtype)
                        
                    part.add_header('Content-Disposition', 'attachment', filename=filename)
                    msg.attach(part)
                    
            server.send_message(msg)
            server.quit()
            
            # === APPEND в папку "Отправленные" через IMAP ===
            append_status = "ok"
            if self.imap_server and self.imap_port:
                try:
                    raw_bytes = msg.as_bytes()
                    raw_bytes = re.sub(br'(?:\r\n|\n|\r(?!\n))', b'\r\n', raw_bytes)
                    
                    imap_conn = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
                    imap_conn.login(self.email_addr, self.password)
                    sent_folder = resolve_imap_folder(imap_conn, "Sent")
                    target_folder = f'"{sent_folder}"' if sent_folder != "INBOX" else "INBOX"
                    imap_conn.append(target_folder, '\\Seen', imaplib.Time2Internaldate(time.time()), raw_bytes)
                    imap_conn.logout()
                except Exception as e:
                    print(f"APPEND to Sent failed: {e}")
                    append_status = "append_failed"
            
            self.finished.emit(True, append_status)
        except Exception as e: 
            self.error.emit(str(e))


# ==========================================
# ФОНОВЫЕ ПОТОКИ ДЛЯ СПАМА (LIVE-РЕЖИМ)
# ==========================================

class FetchSpamListWorker(QThread):
    """Загружает список последних 50 писем из папки Спам (live, без записи в БД)."""
    finished = Signal(list)
    error = Signal(str)
    
    def __init__(self, email_addr, password, imap_server, imap_port, acc_id, limit=50):
        super().__init__()
        self.email_addr = email_addr
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.acc_id = acc_id
        self.limit = limit
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
            mail.login(self.email_addr, self.password)
            real_name = resolve_imap_folder(mail, "Spam")
            res, _ = mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
            if res != 'OK':
                mail.logout()
                self.error.emit(f"Cannot select folder: {real_name}")
                return
            
            status, messages = mail.uid('search', None, 'ALL')
            if status != 'OK':
                mail.logout()
                self.finished.emit([])
                return
            
            all_uids = messages[0].split()
            last_uids = all_uids[-self.limit:] if len(all_uids) > self.limit else all_uids
            results = []
            
            for uid in reversed(last_uids):
                if self._is_cancelled: break
                uid_str = uid.decode()
                
                try:
                    res, data = mail.uid('fetch', uid, '(FLAGS BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (DATE SUBJECT FROM TO CC)])')
                    if res != 'OK': continue
                    
                    flags_str = ""
                    header_bytes = None
                    bodystructure_str = ""
                    
                    for part in data:
                        if isinstance(part, tuple):
                            header_bytes = part[1]
                            prefix = part[0].decode('utf-8', errors='replace') if isinstance(part[0], bytes) else str(part[0])
                            flags_str = prefix
                        elif isinstance(part, bytes):
                            bodystructure_str += part.decode('utf-8', errors='replace')
                    
                    if header_bytes is None: continue
                    
                    msg = email.message_from_bytes(header_bytes)
                    subject = decode_mime_words(msg.get("Subject", "No Subject"))
                    from_ = decode_mime_words(msg.get("From", "Unknown"))
                    to_ = decode_mime_words(msg.get("To", ""))
                    cc_ = decode_mime_words(msg.get("Cc", ""))
                    date_ = msg.get("Date", "")
                    if date_:
                        try: date_ = email.utils.parsedate_to_datetime(date_).strftime("%d.%m.%Y %H:%M")
                        except: pass
                    
                    is_read = 1 if ('\\Seen' in flags_str or '\\Seen' in bodystructure_str) else 0
                    has_attachments = 1 if ('attachment' in bodystructure_str.lower()) else 0
                    
                    results.append({
                        'account_id': self.acc_id,
                        'folder': 'Spam',
                        'uid': uid_str,
                        'subject': subject,
                        'from_addr': from_,
                        'to_addr': to_,
                        'cc_addr': cc_,
                        'date_str': date_,
                        'body_text': '',
                        'body_html': None,
                        'has_attachments': has_attachments,
                        'attachment_names': '',
                        'is_read': is_read,
                        'is_important': 0,
                        'is_html': 0,
                        'is_spam_live': True,
                        'id': None
                    })
                except Exception as e:
                    print(f"Spam item fetch error: {e}")
                    continue
            
            mail.logout()
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class FetchSpamSearchWorker(QThread):
    """Серверный поиск в спаме по теме/отправителю."""
    finished = Signal(list)
    error = Signal(str)
    
    def __init__(self, email_addr, password, imap_server, imap_port, acc_id, query):
        super().__init__()
        self.email_addr = email_addr
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.acc_id = acc_id
        self.query = query
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
            mail.login(self.email_addr, self.password)
            real_name = resolve_imap_folder(mail, "Spam")
            res, _ = mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
            if res != 'OK':
                mail.logout()
                self.error.emit(f"Cannot select folder: {real_name}")
                return
            
            search_ok = False
            uids = []
            
            try:
                query_escaped = self.query.replace('\\', '\\\\').replace('"', '\\"')
                search_criteria = f'CHARSET UTF-8 OR SUBJECT "{query_escaped}" FROM "{query_escaped}"'
                status, messages = mail.uid('search', None, search_criteria)
                if status == 'OK':
                    uids = messages[0].split()
                    search_ok = True
            except Exception:
                pass
            
            if not search_ok:
                try:
                    query_escaped = self.query.replace('\\', '\\\\').replace('"', '\\"')
                    search_criteria = f'OR SUBJECT "{query_escaped}" FROM "{query_escaped}"'
                    status, messages = mail.uid('search', None, search_criteria)
                    if status == 'OK':
                        uids = messages[0].split()
                        search_ok = True
                except Exception:
                    pass
            
            if not search_ok:
                try:
                    query_escaped = self.query.replace('\\', '\\\\').replace('"', '\\"')
                    status, messages = mail.uid('search', None, f'TEXT "{query_escaped}"')
                    if status == 'OK':
                        uids = messages[0].split()
                        search_ok = True
                except Exception:
                    pass
            
            if not uids:
                mail.logout()
                self.finished.emit([])
                return
            
            last_uids = uids[-100:] if len(uids) > 100 else uids
            results = []
            
            for uid in reversed(last_uids):
                if self._is_cancelled: break
                uid_str = uid.decode()
                try:
                    res, data = mail.uid('fetch', uid, '(FLAGS BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (DATE SUBJECT FROM TO CC)])')
                    if res != 'OK': continue
                    
                    flags_str = ""
                    header_bytes = None
                    bodystructure_str = ""
                    
                    for part in data:
                        if isinstance(part, tuple):
                            header_bytes = part[1]
                            prefix = part[0].decode('utf-8', errors='replace') if isinstance(part[0], bytes) else str(part[0])
                            flags_str = prefix
                        elif isinstance(part, bytes):
                            bodystructure_str += part.decode('utf-8', errors='replace')
                    
                    if header_bytes is None: continue
                    
                    msg = email.message_from_bytes(header_bytes)
                    subject = decode_mime_words(msg.get("Subject", "No Subject"))
                    from_ = decode_mime_words(msg.get("From", "Unknown"))
                    to_ = decode_mime_words(msg.get("To", ""))
                    cc_ = decode_mime_words(msg.get("Cc", ""))
                    date_ = msg.get("Date", "")
                    if date_:
                        try: date_ = email.utils.parsedate_to_datetime(date_).strftime("%d.%m.%Y %H:%M")
                        except: pass
                    
                    is_read = 1 if ('\\Seen' in flags_str or '\\Seen' in bodystructure_str) else 0
                    has_attachments = 1 if ('attachment' in bodystructure_str.lower()) else 0
                    
                    results.append({
                        'account_id': self.acc_id,
                        'folder': 'Spam',
                        'uid': uid_str,
                        'subject': subject,
                        'from_addr': from_,
                        'to_addr': to_,
                        'cc_addr': cc_,
                        'date_str': date_,
                        'body_text': '',
                        'body_html': None,
                        'has_attachments': has_attachments,
                        'attachment_names': '',
                        'is_read': is_read,
                        'is_important': 0,
                        'is_html': 0,
                        'is_spam_live': True,
                        'id': None
                    })
                except Exception as e:
                    print(f"Spam search item error: {e}")
                    continue
            
            mail.logout()
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class SaveToImportantWorker(QThread):
    """Скачивает письмо из спама полностью и сохраняет в cached_emails + cached_attachments."""
    progress = Signal(int, int, str)  # current, total, filename
    finished = Signal(dict)  # результат: {'success': bool, 'email_id': int, 'partial': bool}
    error = Signal(str)
    
    def __init__(self, email_addr, password, imap_server, imap_port, acc_id, folder, uid):
        super().__init__()
        self.email_addr = email_addr
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.acc_id = acc_id
        self.folder = folder
        self.uid = uid
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=30)
            mail.login(self.email_addr, self.password)
            real_name = resolve_imap_folder(mail, self.folder)
            mail.select(f'"{real_name}"' if real_name != "INBOX" else "INBOX")
            
            res, msg_data = mail.uid('fetch', self.uid.encode(), '(RFC822)')
            raw_bytes = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            mail.logout()
            
            if not raw_bytes:
                self.error.emit("Email not found on server.")
                return
            
            subject, from_, to_, cc_, date_, body_text, body_html, attachments = parse_raw_email_bytes(raw_bytes)
            
            has_attach = 1 if attachments else 0
            att_names = ", ".join([a['filename'] for a in attachments])
            
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO cached_emails 
                    (account_id, folder, uid, subject, from_addr, to_addr, cc_addr, date_str, 
                     body_text, body_html, has_attachments, attachment_names, is_read, is_important, is_html)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?)
                ''', (self.acc_id, self.folder, self.uid, subject, from_, to_, cc_, date_,
                      body_text, body_html, has_attach, att_names, 1 if body_html else 0))
                conn.commit()
                
                cursor.execute("SELECT id FROM cached_emails WHERE account_id=? AND folder=? AND uid=?",
                               (self.acc_id, self.folder, self.uid))
                row = cursor.fetchone()
                email_id = row[0] if row else None
                
                if email_id:
                    cursor.execute("DELETE FROM cached_attachments WHERE email_id=?", (email_id,))
                    conn.commit()
            
            partial = False
            if attachments and email_id:
                total = len(attachments)
                for idx, att in enumerate(attachments):
                    if self._is_cancelled:
                        partial = True
                        break
                    self.progress.emit(idx + 1, total, att['filename'])
                    try:
                        with sqlite3.connect(DB_PATH, timeout=30) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO cached_attachments (email_id, filename, data) VALUES (?, ?, ?)",
                                (email_id, att['filename'], sqlite3.Binary(att['data']))
                            )
                            conn.commit()
                    except Exception as e:
                        print(f"Attachment save error: {e}")
                        partial = True
            
            self.finished.emit({'success': True, 'email_id': email_id, 'partial': partial})
        except Exception as e:
            self.error.emit(str(e))
# ==========================================
# ДИАЛОГИ
# ==========================================

class AccountDialog(QDialog):
    def __init__(self, parent=None, acc_data=None):
        super().__init__(parent)
        self.current_lang = parent.current_lang if parent else "RU"
        t = TRANSLATIONS[self.current_lang]
        self.setWindowTitle(t["dlg_edit_acc_title"] if acc_data else t["dlg_add_acc_title"])
        self.resize(450, 350)
        layout = QFormLayout(self)
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("example@yandex.ru")
        if not acc_data: self.email_input.textChanged.connect(self.auto_fill_servers)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.imap_input = QLineEdit()
        self.imap_port_input = QSpinBox()
        self.imap_port_input.setRange(1, 65535)
        self.smtp_input = QLineEdit()
        self.smtp_port_input = QSpinBox()
        self.smtp_port_input.setRange(1, 65535)
        if acc_data:
            self.email_input.setText(acc_data[1])
            self.email_input.setReadOnly(True)
            self.password_input.setText(decrypt_password(acc_data[2]))
            self.imap_input.setText(acc_data[3])
            self.imap_port_input.setValue(acc_data[4])
            self.smtp_input.setText(acc_data[5])
            self.smtp_port_input.setValue(acc_data[6])
        else:
            self.imap_port_input.setValue(993)
            self.smtp_port_input.setValue(465)
        layout.addRow(t["dlg_email"], self.email_input)
        layout.addRow(t["dlg_pass"], self.password_input)
        layout.addRow(t["dlg_imap_srv"], self.imap_input)
        layout.addRow(t["dlg_imap_port"], self.imap_port_input)
        layout.addRow(t["dlg_smtp_srv"], self.smtp_input)
        layout.addRow(t["dlg_smtp_port"], self.smtp_port_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t["dlg_save"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t["dlg_cancel"])
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def auto_fill_servers(self):
        email = self.email_input.text().strip().lower()
        if '@' not in email: return
        domain = email.split('@')[1]
        if 'yandex' in domain:
            self.imap_input.setText("imap.yandex.ru")
            self.smtp_input.setText("smtp.yandex.ru")
        elif 'gmail' in domain or 'google' in domain:
            self.imap_input.setText("imap.gmail.com")
            self.smtp_input.setText("smtp.gmail.com")
        elif 'mail.ru' in domain or 'bk.ru' in domain or 'list.ru' in domain or 'inbox.ru' in domain:
            self.imap_input.setText("imap.mail.ru")
            self.smtp_input.setText("smtp.mail.ru")


class ComposeDialog(QDialog):
    def __init__(self, parent, to_addr="", cc_addr="", subject="", body="", default_sender="", draft_id=None, is_template=False):
        super().__init__(parent)
        self.current_lang = parent.current_lang if parent else "RU"
        t = TRANSLATIONS[self.current_lang]
        self.attachments = []
        self.inline_images = {}
        self.draft_id = draft_id
        self.is_template = is_template
        
        self.setWindowTitle(t["dlg_compose_title"])
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(int(screen.width() * 0.9), 1200), min(int(screen.height() * 0.9), 900))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.from_combo = QComboBox()
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, password_enc, smtp_server, smtp_port, imap_server, imap_port FROM accounts WHERE is_active = 1 ORDER BY sort_order ASC")
            accs = cursor.fetchall()
        for acc_id, email_addr, pass_enc, smtp_srv, smtp_port, imap_srv, imap_port in accs:
            self.from_combo.addItem(email_addr, (acc_id, decrypt_password(pass_enc), smtp_srv, smtp_port, imap_srv, imap_port))
            
        if default_sender:
            idx = self.from_combo.findText(default_sender)
            if idx >= 0: self.from_combo.setCurrentIndex(idx)

        self.to_input = QLineEdit()
        self.to_input.setText(to_addr)
        self.cc_input = QLineEdit()
        self.cc_input.setText(cc_addr)
        self.subj_input = QLineEdit()
        self.subj_input.setText(subject)
        form.addRow(t["dlg_from"], self.from_combo)
        form.addRow(t["dlg_to"], self.to_input)
        form.addRow(t["dlg_cc"], self.cc_input)
        form.addRow(t["dlg_subj"], self.subj_input)
        layout.addLayout(form)
        
        sig_layout = QHBoxLayout()
        sig_layout.addWidget(QLabel(t["dlg_sig"]))
        self.sig_combo = QComboBox()
        self.load_signatures()
        self.sig_combo.currentIndexChanged.connect(self.insert_signature)
        sig_layout.addWidget(self.sig_combo)
        sig_layout.addStretch()
        layout.addLayout(sig_layout)
        
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 5, 0, 0)
        
        btn_bold = QPushButton("B")
        btn_bold.setMinimumWidth(30)
        btn_bold.setStyleSheet("font-weight: bold; font-size: 14px; color: #3c4043; border: 1px solid #dadce0; border-radius: 4px; padding: 2px 5px;")
        btn_bold.clicked.connect(lambda: self.body_input.setFontWeight(QFont.Weight.Bold if self.body_input.fontWeight() != QFont.Weight.Bold else QFont.Weight.Normal))
        
        btn_italic = QPushButton("I")
        btn_italic.setMinimumWidth(30)
        btn_italic.setStyleSheet("font-style: italic; font-size: 14px; color: #3c4043; border: 1px solid #dadce0; border-radius: 4px; padding: 2px 5px;")
        btn_italic.clicked.connect(lambda: self.body_input.setFontItalic(not self.body_input.fontItalic()))
        
        btn_underline = QPushButton("U")
        btn_underline.setMinimumWidth(30)
        btn_underline.setStyleSheet("text-decoration: underline; font-size: 14px; color: #3c4043; border: 1px solid #dadce0; border-radius: 4px; padding: 2px 5px;")
        btn_underline.clicked.connect(lambda: self.body_input.setFontUnderline(not self.body_input.fontUnderline()))
        
        btn_link = QPushButton(t["btn_insert_link"])
        btn_link.setMinimumHeight(25)
        btn_link.setStyleSheet("border: 1px solid #dadce0; border-radius: 4px; padding: 0px 10px; color: #3c4043;")
        btn_link.clicked.connect(self.insert_link)
        
        btn_make_link = QPushButton(t["btn_make_link"])
        btn_make_link.setMinimumHeight(25)
        btn_make_link.setStyleSheet("border: 1px solid #dadce0; border-radius: 4px; padding: 0px 10px; color: #3c4043;")
        btn_make_link.clicked.connect(self.make_link)
        
        btn_img = QPushButton(t["btn_insert_img"])
        btn_img.setMinimumHeight(25)
        btn_img.setStyleSheet("border: 1px solid #dadce0; border-radius: 4px; padding: 0px 10px; color: #3c4043;")
        btn_img.clicked.connect(self.insert_image)
        
        toolbar_layout.addWidget(btn_bold)
        toolbar_layout.addWidget(btn_italic)
        toolbar_layout.addWidget(btn_underline)
        toolbar_layout.addWidget(btn_link)
        toolbar_layout.addWidget(btn_make_link)
        toolbar_layout.addWidget(btn_img)
        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)
        
        self.body_input = QTextEdit()
        self.body_input.setAcceptRichText(True)
        layout.addWidget(self.body_input, 1)
        
        self.total_size_lbl = QLabel(t["file_limit_warn"])
        self.total_size_lbl.setStyleSheet("color: #5f6368; font-size: 11px;")
        layout.addWidget(self.total_size_lbl)
        
        self.files_list = QListWidget()
        self.files_list.setFixedHeight(80)
        self.files_list.itemDoubleClicked.connect(self.remove_attachment)
        layout.addWidget(self.files_list)
        
        btn_layout = QHBoxLayout()
        btn_attach = QPushButton(t["dlg_attach"])
        btn_attach.clicked.connect(self.attach_file)
        
        if self.is_template:
            btn_update_tmpl = QPushButton(t["dlg_update_template"])
            btn_update_tmpl.clicked.connect(lambda: self.save_to_db('template'))
            btn_layout.addWidget(btn_update_tmpl)
        else:
            btn_save_draft = QPushButton(t["dlg_save_draft"])
            btn_save_draft.clicked.connect(lambda: self.save_to_db('draft'))
            btn_save_tmpl = QPushButton(t["dlg_save_template"])
            btn_save_tmpl.clicked.connect(lambda: self.save_to_db('template'))
            btn_layout.addWidget(btn_save_draft)
            btn_layout.addWidget(btn_save_tmpl)

        btn_send = QPushButton(t["dlg_send"])
        btn_send.setObjectName("primaryBtn")
        btn_send.clicked.connect(self.send_email)
        
        btn_layout.addWidget(btn_attach)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_send)
        layout.addLayout(btn_layout)
        
        if self.draft_id:
            self.load_from_db()
        else:
            self.body_input.setHtml(body)
            self.insert_signature()
            cursor = self.body_input.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.body_input.setTextCursor(cursor)

    def cleanup_temp_files(self):
        """Удаляет temp-файлы вложений, созданные этим черновиком."""
        if not self.draft_id:
            return
        try:
            for fname in os.listdir(TEMP_ATT_DIR):
                if fname.startswith(f"draft_{self.draft_id}_"):
                    try:
                        os.remove(os.path.join(TEMP_ATT_DIR, fname))
                    except Exception:
                        pass
        except Exception:
            pass

    def load_from_db(self):
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT account_id, to_addr, cc_addr, subject, html_body FROM drafts_templates WHERE id=?", (self.draft_id,))
            row = cursor.fetchone()
            if row:
                acc_id, to_a, cc_a, subj, body = row
                if to_a: self.to_input.setText(to_a)
                if cc_a: self.cc_input.setText(cc_a)
                if subj: self.subj_input.setText(subj)
                if body: self.body_input.setHtml(body)
                
                if acc_id:
                    for i in range(self.from_combo.count()):
                        if self.from_combo.itemData(i)[0] == acc_id:
                            self.from_combo.setCurrentIndex(i)
                            break
                            
            cursor.execute("SELECT filename, data FROM draft_attachments WHERE draft_id=?", (self.draft_id,))
            for fn, data in cursor.fetchall():
                temp_path = os.path.join(TEMP_ATT_DIR, f"draft_{self.draft_id}_{fn}")
                with open(temp_path, 'wb') as f:
                    f.write(data)
                self.attachments.append(temp_path)
        self.update_attachment_ui()
        
        cursor = self.body_input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.body_input.setTextCursor(cursor)

    def save_to_db(self, item_type):
        to_addr = self.to_input.text().strip()
        cc_addr = self.cc_input.text().strip()
        subject = self.subj_input.text().strip()
        html_body = self.body_input.toHtml()
        
        acc_id = self.from_combo.currentData()[0] if self.from_combo.currentData() else None
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%d.%m.%Y %H:%M")
            
            if self.draft_id:
                cursor.execute("UPDATE drafts_templates SET to_addr=?, cc_addr=?, subject=?, html_body=?, created_at=? WHERE id=?", 
                               (to_addr, cc_addr, subject, html_body, now, self.draft_id))
                target_id = self.draft_id
            else:
                cursor.execute("INSERT INTO drafts_templates (type, account_id, to_addr, cc_addr, subject, html_body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (item_type, acc_id, to_addr, cc_addr, subject, html_body, now))
                target_id = cursor.lastrowid
                
            cursor.execute("DELETE FROM draft_attachments WHERE draft_id=?", (target_id,))
            
            for file_path in self.attachments:
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        data = f.read()
                    filename = os.path.basename(file_path)
                    if filename.startswith(f"draft_{target_id}_"):
                        filename = filename.replace(f"draft_{target_id}_", "")
                    cursor.execute("INSERT INTO draft_attachments (draft_id, filename, data) VALUES (?, ?, ?)", (target_id, filename, data))
                    
            conn.commit()
            
        self.draft_id = target_id
        t = TRANSLATIONS[self.current_lang]
        QMessageBox.information(self, t["success_title"], t["draft_saved"] if item_type == 'draft' else t["template_saved"])
        
        if self.parent().current_folder in ("DRAFTS", "TEMPLATES"):
            self.parent().refresh_current_folder()
            
        self.accept()

    def load_signatures(self):
        self.sig_combo.addItem(TRANSLATIONS[self.current_lang]["dlg_no_sig"], "")
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, text, is_default FROM signatures")
            self.sigs = cursor.fetchall()
        default_idx = 0
        for i, sig in enumerate(self.sigs):
            self.sig_combo.addItem(sig[1], sig[2])
            if sig[3]: default_idx = i + 1
        self.sig_combo.setCurrentIndex(default_idx)

    def insert_signature(self):
        sig_text = self.sig_combo.currentData()
        current_html = self.body_input.toHtml()
        
        # Удаляем старую подпись, если она есть
        if "-- <br" in current_html or "-- \n" in current_html:
            current_html = current_html.split("-- <br")[0]
            current_html = current_html.split("-- \n")[0]
            self.body_input.setHtml(current_html)
            
        # Если выбрана "Без подписи" - просто выходим (подпись уже удалена)
        if not sig_text: 
            return
            
        cursor = self.body_input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        
        # Добавляем две пустые строки в начале перед подписью
        html_sig = f"<br><br><div style='color: #5f6368;'>-- <br>{html.escape(sig_text).replace(chr(10), '<br>')}</div><br><br><br>"
        cursor.insertHtml(html_sig)

    def insert_link(self):
        t = TRANSLATIONS[self.current_lang]
        dialog = QDialog(self)
        dialog.setWindowTitle(t["insert_link"])
        dialog.resize(500, 150)
        layout = QFormLayout(dialog)
        
        text_input = QLineEdit()
        url_input = QLineEdit()
        url_input.setPlaceholderText("https://...")
        
        layout.addRow(t["link_text"], text_input)
        layout.addRow(t["link_url"], url_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t["dlg_ok"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t["dlg_cancel"])
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = text_input.text().strip()
            url = url_input.text().strip()
            if not text or not url: return
            if not url.startswith('http'): url = 'http://' + url
            
            cursor = self.body_input.textCursor()
            cursor.insertHtml(f'<a href="{url}">{text}</a>')

    def make_link(self):
        cursor = self.body_input.textCursor()
        if not cursor.hasSelection():
            t = TRANSLATIONS[self.current_lang]
            QMessageBox.warning(self, t["warn_title"], t["select_text_to_link"])
            return
            
        selected_text = cursor.selectedText()
        t = TRANSLATIONS[self.current_lang]
        
        dialog = QDialog(self)
        dialog.setWindowTitle(t["make_link"])
        dialog.resize(500, 100)
        layout = QFormLayout(dialog)
        
        url_input = QLineEdit()
        url_input.setPlaceholderText("https://...")
        layout.addRow(t["link_url"], url_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t["dlg_ok"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t["dlg_cancel"])
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            url = url_input.text().strip()
            if url:
                if not url.startswith('http'): url = 'http://' + url
                
                char_format = QTextCharFormat()
                char_format.setAnchor(True)
                char_format.setAnchorHref(url)
                char_format.setForeground(QColor("#1a73e8"))
                char_format.setFontUnderline(True)
                
                cursor.mergeCharFormat(char_format)

    def insert_image(self):
        t = TRANSLATIONS[self.current_lang]
        file_path, _ = QFileDialog.getOpenFileName(self, t["insert_img"], "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not file_path: return
        
        image = QImage(file_path)
        if image.isNull():
            QMessageBox.warning(self, t["err_title"], t["img_load_err"])
            return
            
        if image.width() > 800:
            image = image.scaledToWidth(800, Qt.TransformationMode.SmoothTransformation)
            
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        base64_data = bytes(ba.toBase64()).decode('utf-8')
        
        cursor = self.body_input.textCursor()
        cursor.insertHtml(f'<img src="data:image/png;base64,{base64_data}" />')

    def update_attachment_ui(self):
        self.files_list.clear()
        total_size = 0
        for file_path in self.attachments:
            if os.path.exists(file_path):
                size = os.path.getsize(file_path)
                total_size += size
                name = os.path.basename(file_path)
                if name.startswith(f"draft_{self.draft_id}_"):
                    name = name.replace(f"draft_{self.draft_id}_", "")
                item = QListWidgetItem(f"📄 {name} ({format_size(size, self.current_lang)})")
                item.setData(Qt.ItemDataRole.UserRole, file_path)
                self.files_list.addItem(item)
                
        t = TRANSLATIONS[self.current_lang]
        if total_size > 0:
            self.total_size_lbl.setText(t["total_size_label"].format(size=format_size(total_size, self.current_lang)))
        else:
            self.total_size_lbl.setText(t["file_limit_warn"])

    def attach_file(self):
        t = TRANSLATIONS[self.current_lang]
        files, _ = QFileDialog.getOpenFileNames(self, t["dlg_attach"])
        for f in files:
            if f not in self.attachments:
                self.attachments.append(f)
        self.update_attachment_ui()

    def remove_attachment(self, item):
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path in self.attachments:
            self.attachments.remove(file_path)
            self.update_attachment_ui()

    def send_email(self):
        t = TRANSLATIONS[self.current_lang]
        to_addr = self.to_input.text().strip()
        cc_addr = self.cc_input.text().strip()
        
        if not to_addr:
            QMessageBox.warning(self, t["warn_title"], t["err_no_to"])
            return
            
        subj = self.subj_input.text().strip()
        if not subj:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setWindowTitle(t["warn_title"])
            msg.setText(t["err_no_subj"])
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.button(QMessageBox.StandardButton.Yes).setText(t["yes_btn"])
            msg.button(QMessageBox.StandardButton.No).setText(t["no_btn"])
            if msg.exec() != QMessageBox.StandardButton.Yes:
                return
        
        sender_email = self.from_combo.currentText()
        sender_data = self.from_combo.currentData()
        if not sender_data: return
        
        # sender_data: (acc_id, password, smtp_server, smtp_port, imap_server, imap_port)
        acc_password = sender_data[1]
        smtp_server = sender_data[2]
        smtp_port = sender_data[3]
        imap_server = sender_data[4] if len(sender_data) > 4 else None
        imap_port = sender_data[5] if len(sender_data) > 5 else None
            
        html_body = self.body_input.toHtml()
        
        self.inline_images = {}
        img_pattern = r'<img[^>]+src="data:image/(png|jpeg|jpg|gif);base64,([^"]+)"[^>]*>'
        
        def replace_base64_with_cid(match):
            img_type = match.group(1)
            base64_data = match.group(2)
            
            cid = f"img_{len(self.inline_images) + 1}"
            
            image_data = base64.b64decode(base64_data)
            image = QImage()
            image.loadFromData(image_data)
            
            self.inline_images[cid] = (image, img_type)
            return f'<img src="cid:{cid}">'
        
        html_body = re.sub(img_pattern, replace_base64_with_cid, html_body)
        
        worker = SendEmailWorker(
            sender_email, acc_password, smtp_server, smtp_port,
            to_addr, cc_addr, subj, html_body, self.attachments, self.inline_images,
            imap_server=imap_server, imap_port=imap_port
        )
        
        def on_success(succ, append_status):
            if self.draft_id and not self.is_template:
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM drafts_templates WHERE id=?", (self.draft_id,))
                    cursor.execute("DELETE FROM draft_attachments WHERE draft_id=?", (self.draft_id,))
                    conn.commit()
                self.cleanup_temp_files()
                if self.parent().current_folder == "DRAFTS":
                    self.parent().refresh_current_folder()
            
            if append_status == "append_failed":
                QMessageBox.warning(self.parent(), t["warn_title"], t["email_sent_no_append"])
            else:
                QMessageBox.information(self.parent(), t["success_title"], t["email_sent"])
            
        self.parent().start_thread(
            worker, 
            on_success,
            lambda err: QMessageBox.critical(self.parent(), t["err_title"], f"{t['email_err']}\n{err}")
        )
        self.accept()


class SignatureDialog(QDialog):
    def __init__(self, parent=None, sig_data=None):
        super().__init__(parent)
        self.current_lang = parent.current_lang if parent else "RU"
        t = TRANSLATIONS[self.current_lang]
        self.setWindowTitle(t["dlg_sig_title"])
        self.resize(400, 300)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_input = QLineEdit()
        self.text_input = QTextEdit()
        self.default_check = QCheckBox(t["dlg_sig_default"])
        if sig_data:
            self.name_input.setText(sig_data[1])
            self.text_input.setText(sig_data[2])
            self.default_check.setChecked(bool(sig_data[3]))
        form.addRow(t["dlg_sig_name"], self.name_input)
        layout.addLayout(form)
        layout.addWidget(QLabel(t["dlg_sig_text"]))
        layout.addWidget(self.text_input)
        layout.addWidget(self.default_check)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t["dlg_save"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t["dlg_cancel"])
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LabelDialog(QDialog):
    def __init__(self, parent=None, label_data=None):
        super().__init__(parent)
        self.current_lang = parent.current_lang if parent else "RU"
        t = TRANSLATIONS[self.current_lang]
        self.current_bg_color = "#e8f0fe"
        self.setWindowTitle(t["dlg_label_title"])
        self.resize(500, 320)
        layout = QFormLayout(self)
        self.name_input = QLineEdit()
        self.emails_input = QLineEdit()
        self.subject_input = QLineEdit()
        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(30)
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_btn.clicked.connect(self.pick_color)
        if label_data:
            self.name_input.setText(label_data[1])
            self.current_bg_color = label_data[2] or "#e8f0fe"
            self.emails_input.setText(label_data[4] or "")
            self.subject_input.setText(label_data[5] or "")
        self.update_color_btn()
        layout.addRow(t["dlg_label_name"], self.name_input)
        layout.addRow(t["dlg_label_color"], self.color_btn)
        layout.addRow(t["dlg_label_emails"], self.emails_input)
        layout.addRow(t["dlg_label_subject"], self.subject_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t["dlg_save"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t["dlg_cancel"])
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.current_bg_color), self)
        if color.isValid():
            self.current_bg_color = color.name()
            self.update_color_btn()

    def update_color_btn(self):
        tc = get_contrast_color(self.current_bg_color)
        self.color_btn.setStyleSheet(f"background-color: {self.current_bg_color}; color: {tc}; border: 1px solid #dadce0; border-radius: 4px; font-weight: bold;")
        self.color_btn.setText(self.current_bg_color)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.current_lang = parent.current_lang if parent else "RU"
        t = TRANSLATIONS[self.current_lang]
        self.setWindowTitle(t["dlg_settings_title"])
        self.resize(650, 500)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        sig_widget = QWidget()
        sig_layout = QVBoxLayout(sig_widget)
        self.sig_list = QListWidget()
        self.load_signatures()
        sig_layout.addWidget(self.sig_list)
        btn_layout = QHBoxLayout()
        btn_add = QPushButton(t["dlg_add"])
        btn_add.clicked.connect(self.add_signature)
        btn_edit = QPushButton(t["dlg_edit"])
        btn_edit.clicked.connect(self.edit_signature)
        btn_del = QPushButton(t["dlg_del"])
        btn_del.clicked.connect(self.delete_signature)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_del)
        sig_layout.addLayout(btn_layout)
        tabs.addTab(sig_widget, t["dlg_tab_sigs"])
        
        acc_widget = QWidget()
        acc_layout = QVBoxLayout(acc_widget)
        self.acc_list = QListWidget()
        self.load_accounts()
        acc_layout.addWidget(self.acc_list)
        btn_acc_layout = QHBoxLayout()
        btn_add_acc = QPushButton(t["dlg_add"])
        btn_add_acc.clicked.connect(self.add_account)
        btn_edit_acc = QPushButton(t["dlg_edit"])
        btn_edit_acc.clicked.connect(self.edit_account)
        btn_del_acc = QPushButton(t["dlg_del"])
        btn_del_acc.clicked.connect(self.delete_account)
        btn_acc_layout.addWidget(btn_add_acc)
        btn_acc_layout.addWidget(btn_edit_acc)
        btn_acc_layout.addWidget(btn_del_acc)
        acc_layout.addLayout(btn_acc_layout)
        tabs.addTab(acc_widget, t["dlg_tab_accs"])
        
        lbl_widget = QWidget()
        lbl_layout = QVBoxLayout(lbl_widget)
        self.lbl_list = QListWidget()
        self.load_labels()
        lbl_layout.addWidget(self.lbl_list)
        btn_lbl_layout = QHBoxLayout()
        btn_add_lbl = QPushButton(t["dlg_add"])
        btn_add_lbl.clicked.connect(self.add_label)
        btn_edit_lbl = QPushButton(t["dlg_edit"])
        btn_edit_lbl.clicked.connect(self.edit_label)
        btn_del_lbl = QPushButton(t["dlg_del"])
        btn_del_lbl.clicked.connect(self.delete_label)
        btn_lbl_layout.addWidget(btn_add_lbl)
        btn_lbl_layout.addWidget(btn_edit_lbl)
        btn_lbl_layout.addWidget(btn_del_lbl)
        lbl_layout.addLayout(btn_lbl_layout)
        tabs.addTab(lbl_widget, t["dlg_tab_labels"])
        
        layout.addWidget(tabs)
        close_btn = QPushButton(t["close"])
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def load_signatures(self):
        self.sig_list.clear()
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, text, is_default FROM signatures")
            for row in cursor.fetchall():
                item = QListWidgetItem(row[1] + (" (Default)" if row[3] else ""))
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.sig_list.addItem(item)

    def add_signature(self):
        dialog = SignatureDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                if dialog.default_check.isChecked(): cursor.execute("UPDATE signatures SET is_default = 0")
                cursor.execute("INSERT INTO signatures (name, text, is_default) VALUES (?, ?, ?)", (dialog.name_input.text(), dialog.text_input.toPlainText(), int(dialog.default_check.isChecked())))
                conn.commit()
            self.load_signatures()

    def edit_signature(self):
        item = self.sig_list.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        dialog = SignatureDialog(self, sig_data=data)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                if dialog.default_check.isChecked(): cursor.execute("UPDATE signatures SET is_default = 0")
                cursor.execute("UPDATE signatures SET name=?, text=?, is_default=? WHERE id=?", (dialog.name_input.text(), dialog.text_input.toPlainText(), int(dialog.default_check.isChecked()), data[0]))
                conn.commit()
            self.load_signatures()

    def delete_signature(self):
        item = self.sig_list.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM signatures WHERE id=?", (data[0],))
            conn.commit()
        self.load_signatures()

    def load_accounts(self):
        self.acc_list.clear()
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, password_enc, imap_server, imap_port, smtp_server, smtp_port FROM accounts ORDER BY sort_order ASC")
            for row in cursor.fetchall():
                item = QListWidgetItem(row[1])
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.acc_list.addItem(item)

    def add_account(self):
        dialog = AccountDialog(self.parent_window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            enc_pass = encrypt_password(dialog.password_input.text().strip())
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO accounts (email, password_enc, imap_server, imap_port, smtp_server, smtp_port) VALUES (?, ?, ?, ?, ?, ?)",
                               (dialog.email_input.text().strip(), enc_pass, dialog.imap_input.text(), dialog.imap_port_input.value(), dialog.smtp_input.text(), dialog.smtp_port_input.value()))
                conn.commit()
            self.load_accounts()
            self.parent_window.load_accounts_tree()

    def edit_account(self):
        item = self.acc_list.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        dialog = AccountDialog(self.parent_window, acc_data=data)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            enc_pass = encrypt_password(dialog.password_input.text().strip())
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE accounts SET password_enc=?, imap_server=?, imap_port=?, smtp_server=?, smtp_port=? WHERE id=?", (enc_pass, dialog.imap_input.text(), dialog.imap_port_input.value(), dialog.smtp_input.text(), dialog.smtp_port_input.value(), data[0]))
                conn.commit()
            self.load_accounts()
            self.parent_window.load_accounts_tree()

    def delete_account(self):
        item = self.acc_list.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        t = TRANSLATIONS[self.current_lang]
        if show_custom_confirm(self, t["confirm_title"], t["acc_del_confirm"], self.current_lang):
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM accounts WHERE id=?", (data[0],))
                cursor.execute("DELETE FROM cached_emails WHERE account_id=?", (data[0],))
                cursor.execute("DELETE FROM cached_attachments WHERE email_id NOT IN (SELECT id FROM cached_emails)")
                conn.commit()
            self.load_accounts()
            self.parent_window.load_accounts_tree()

    def load_labels(self):
        self.lbl_list.clear()
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, bg_color, text_color, filter_emails, filter_subject FROM labels ORDER BY id")
            for row in cursor.fetchall():
                item = QListWidgetItem(row[1])
                item.setData(Qt.ItemDataRole.UserRole, row)
                item.setBackground(QColor(row[2] or "#e8f0fe"))
                item.setForeground(QColor(row[3] or "#000000"))
                self.lbl_list.addItem(item)

    def add_label(self):
        dialog = LabelDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.name_input.text().strip()
            if not name: return
            tc = get_contrast_color(dialog.current_bg_color)
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO labels (name, bg_color, text_color, filter_emails, filter_subject) VALUES (?, ?, ?, ?, ?)", (name, dialog.current_bg_color, tc, dialog.emails_input.text().strip(), dialog.subject_input.text().strip()))
                conn.commit()
            self.load_labels()
            self.parent_window.refresh_labels_ui()
            self.parent_window.refresh_current_folder()

    def edit_label(self):
        item = self.lbl_list.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        dialog = LabelDialog(self, label_data=data)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.name_input.text().strip()
            if not name: return
            tc = get_contrast_color(dialog.current_bg_color)
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE labels SET name=?, bg_color=?, text_color=?, filter_emails=?, filter_subject=? WHERE id=?", (name, dialog.current_bg_color, tc, dialog.emails_input.text().strip(), dialog.subject_input.text().strip(), data[0]))
                conn.commit()
            self.load_labels()
            self.parent_window.refresh_labels_ui()
            self.parent_window.refresh_current_folder()

    def delete_label(self):
        item = self.lbl_list.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        t = TRANSLATIONS[self.current_lang]
        if not show_custom_confirm(self, t["confirm_title"], t["label_del_confirm"], self.current_lang): return
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM labels WHERE id=?", (data[0],))
            conn.commit()
        self.load_labels()
        self.parent_window.refresh_labels_ui()
        self.parent_window.refresh_current_folder()


class ContactDialog(QDialog):
    def __init__(self, parent=None, contact_data=None, default_email=""):
        super().__init__(parent)
        self.current_lang = parent.current_lang if parent else "RU"
        t = TRANSLATIONS[self.current_lang]
        self.setWindowTitle(t["dlg_contact_title"])
        self.resize(400, 300)
        layout = QFormLayout(self)
        self.name_input = QLineEdit()
        self.email_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(80)
        if contact_data:
            self.name_input.setText(contact_data[1] or "")
            self.email_input.setText(contact_data[2] or "")
            self.phone_input.setText(contact_data[3] or "")
            self.notes_input.setText(contact_data[4] or "")
        elif default_email:
            self.email_input.setText(default_email)
        layout.addRow(t["dlg_contact_name"], self.name_input)
        layout.addRow(t["dlg_contact_email"], self.email_input)
        layout.addRow(t["dlg_contact_phone"], self.phone_input)
        layout.addRow(t["dlg_contact_notes"], self.notes_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t["dlg_save"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t["dlg_cancel"])
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
# ==========================================
# ГЛАВНОЕ ОКНО
# ==========================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_lang = "RU"
        self.setWindowTitle(TRANSLATIONS[self.current_lang]["app_title"])
        self.resize(1500, 900)
        self.setMinimumSize(1200, 700)
        if os.path.exists(ICON_PATH): self.setWindowIcon(QIcon(ICON_PATH))
        init_db()
        gc_temp_files()
        
        self.current_account_id = None
        self.current_account_email = None
        self.current_folder = None
        self.current_email_data = None
        self.current_raw_bytes = None
        self.active_threads = []
        self.is_viewing_source = False
        self.current_raw_source = ""
        self.current_body_text = ""
        self.current_body_html = ""
        self.current_body_cc = ""
        self.important_uids = set()
        self.sync_worker = None
        self.full_email_worker = None
        self.load_older_worker = None
        self.spam_list_worker = None
        self.spam_search_worker = None
        self.save_important_worker = None
        self.is_spam_mode = False
        self.qt_translator = None
        
        self.read_timer = QTimer(self)
        self.read_timer.setSingleShot(True)
        self.read_timer.timeout.connect(self.mark_current_email_as_read)
        self.pending_item_to_read = None
        self.contact_filter_text = ""
        self.all_contacts = []
        self.global_counts = {}
        self.labels_cache = []
        self.init_tray()
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        top_panel = QWidget()
        top_panel.setObjectName("topPanel")
        top_panel.setFixedHeight(60)
        top_layout = QHBoxLayout(top_panel)
        top_layout.setContentsMargins(20, 0, 20, 0)
        self.title_lbl = QLabel(TRANSLATIONS[self.current_lang]["app_title"])
        self.title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #202124;")
        top_layout.addWidget(self.title_lbl)
        top_layout.addStretch()
        self.btn_compose = QPushButton(TRANSLATIONS[self.current_lang]["compose"])
        self.btn_compose.setObjectName("primaryBtn")
        self.btn_compose.clicked.connect(lambda checked=False: self.open_compose_dialog())
        top_layout.addWidget(self.btn_compose)
        self.btn_settings = QPushButton(TRANSLATIONS[self.current_lang]["settings"])
        self.btn_settings.clicked.connect(self.open_settings)
        top_layout.addWidget(self.btn_settings)
        main_layout.addWidget(top_panel)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #dadce0;")
        main_layout.addWidget(line)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(1)
        
        # --- ЛЕВАЯ ПАНЕЛЬ ---
        left_panel = QWidget()
        left_panel.setObjectName("leftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setHandleWidth(1)
        
        folders_widget = QWidget()
        folders_layout = QVBoxLayout(folders_widget)
        folders_layout.setContentsMargins(0, 0, 0, 0)
        left_toolbar = QHBoxLayout()
        self.btn_refresh_left = QPushButton(TRANSLATIONS[self.current_lang]["refresh"])
        self.btn_refresh_left.setStyleSheet("text-align: left; font-weight: bold; padding: 5px;")
        self.btn_refresh_left.clicked.connect(self.manual_global_check)
        left_toolbar.addWidget(self.btn_refresh_left)
        left_toolbar.addStretch()
        folders_layout.addLayout(left_toolbar)
        self.tree_accounts = QTreeWidget()
        self.tree_accounts.setHeaderHidden(True)
        self.tree_accounts.setRootIsDecorated(True)
        self.tree_accounts.setIndentation(15)
        self.tree_accounts.setStyleSheet("QTreeWidget { border: none; background: transparent; font-size: 14px; } QTreeWidget::item { padding: 8px; border-radius: 4px; } QTreeWidget::item:selected { background-color: #e8f0fe; color: #1967d2; }")
        self.tree_accounts.itemClicked.connect(self.on_folder_clicked)
        self.tree_accounts.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_accounts.customContextMenuRequested.connect(self.show_account_context_menu)
        self.load_accounts_tree()
        folders_layout.addWidget(self.tree_accounts, 1)
        
        contacts_widget = QWidget()
        contacts_layout = QVBoxLayout(contacts_widget)
        contacts_layout.setContentsMargins(0, 0, 0, 0)
        contacts_header = QHBoxLayout()
        self.contacts_lbl = QLabel(TRANSLATIONS[self.current_lang]["contacts_title"])
        self.contacts_lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        contacts_header.addWidget(self.contacts_lbl)
        contacts_header.addStretch()
        self.btn_add_contact = QPushButton(TRANSLATIONS[self.current_lang]["add_contact"])
        self.btn_add_contact.setStyleSheet("QPushButton { background-color: #e8f0fe; color: #1967d2; border-radius: 4px; font-weight: bold; border: 1px solid #1967d2; padding: 2px 8px; }")
        self.btn_add_contact.clicked.connect(self.add_contact_dialog)
        contacts_header.addWidget(self.btn_add_contact)
        self.btn_import_vcf = QPushButton(TRANSLATIONS[self.current_lang]["import_vcf"])
        self.btn_import_vcf.setStyleSheet("QPushButton { border: 1px solid #dadce0; border-radius: 4px; font-size: 11px; padding: 2px 8px; }")
        self.btn_import_vcf.clicked.connect(self.import_vcf)
        contacts_header.addWidget(self.btn_import_vcf)
        self.btn_export_vcf = QPushButton(TRANSLATIONS[self.current_lang]["export_vcf"])
        self.btn_export_vcf.setStyleSheet("QPushButton { border: 1px solid #dadce0; border-radius: 4px; font-size: 11px; padding: 2px 8px; }")
        self.btn_export_vcf.clicked.connect(self.export_vcf)
        contacts_header.addWidget(self.btn_export_vcf)
        contacts_layout.addLayout(contacts_header)
        self.contact_search_input = QLineEdit()
        self.contact_search_input.setPlaceholderText(TRANSLATIONS[self.current_lang]["contact_search_ph"])
        self.contact_search_input.setStyleSheet("QLineEdit { border: 1px solid #dadce0; border-radius: 4px; padding: 4px 8px; background-color: #ffffff; font-size: 12px; margin-bottom: 5px; } QLineEdit:focus { border: 1px solid #1a73e8; }")
        self.contact_search_input.textChanged.connect(self.filter_contacts)
        contacts_layout.addWidget(self.contact_search_input)
        self.contacts_list = QListWidget()
        self.contacts_list.setStyleSheet("QListWidget { border: 1px solid #dadce0; border-radius: 4px; background: #ffffff; } QListWidget::item { padding: 0px; border-bottom: 1px solid #f1f3f4; } QListWidget::item:selected { background-color: #e8f0fe; }")
        self.contacts_list.itemDoubleClicked.connect(self.edit_contact_dialog)
        self.contacts_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.contacts_list.customContextMenuRequested.connect(self.show_contact_context_menu)
        contacts_layout.addWidget(self.contacts_list)
        left_splitter.addWidget(folders_widget)
        left_splitter.addWidget(contacts_widget)
        left_splitter.setSizes([500, 300])
        left_layout.addWidget(left_splitter)
        self.load_contacts()
        
        # --- ПАНЕЛЬ МЕТОК ---
        labels_panel = QWidget()
        labels_panel.setObjectName("labelsPanel")
        labels_panel.setStyleSheet("QWidget#labelsPanel { background-color: #f8f9fa; }")
        labels_panel.setMinimumWidth(90)
        labels_panel.setMaximumWidth(260)
        labels_panel_layout = QVBoxLayout(labels_panel)
        labels_panel_layout.setContentsMargins(8, 10, 8, 10)
        labels_panel_layout.setSpacing(0)
        labels_scroll = QScrollArea()
        labels_scroll.setWidgetResizable(True)
        labels_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        labels_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        labels_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.labels_scroll_content = QWidget()
        self.labels_scroll_content.setStyleSheet("background: transparent;")
        self.labels_buttons_layout = QVBoxLayout(self.labels_scroll_content)
        self.labels_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.labels_buttons_layout.setSpacing(6)
        self.labels_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        labels_scroll.setWidget(self.labels_scroll_content)
        labels_panel_layout.addWidget(labels_scroll)

        # --- ЦЕНТРАЛЬНАЯ ПАНЕЛЬ ---
        center_panel = QWidget()
        center_panel.setObjectName("centerPanel")
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(20, 20, 20, 20)
        search_toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(TRANSLATIONS[self.current_lang]["search_ph"])
        self.search_input.setStyleSheet("QLineEdit { border: 1px solid #dadce0; border-radius: 20px; padding: 8px 15px; background-color: #f1f3f4; } QLineEdit:focus { background-color: #ffffff; border: 1px solid #1a73e8; }")
        self.search_input.returnPressed.connect(self.execute_search)
        search_toolbar.addWidget(self.search_input, 1)
        self.btn_bulk_del = QPushButton(TRANSLATIONS[self.current_lang]["bulk_del"])
        self.btn_bulk_del.setStyleSheet("QPushButton { background-color: #fce8e6; color: #c5221f; border-radius: 4px; padding: 8px 12px; font-weight: bold; border: 1px solid #fad2cf; } QPushButton:hover { background-color: #fad2cf; }")
        self.btn_bulk_del.clicked.connect(self.bulk_delete_emails)
        search_toolbar.addWidget(self.btn_bulk_del)
        center_layout.addLayout(search_toolbar)
        self.email_list = QListWidget()
        self.email_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.email_list.setStyleSheet("QListWidget { border: 1px solid #dadce0; border-radius: 8px; background-color: #ffffff; } QListWidget::item { border-bottom: 1px solid #f1f3f4; padding: 10px; } QListWidget::item:hover { background-color: #f8f9fa; } QListWidget::item:selected { background-color: #e8f0fe; border-left: 3px solid #1a73e8; }")
        self.email_list.itemClicked.connect(self.on_email_clicked)
        self.email_list.itemDoubleClicked.connect(self.edit_draft_template)
        self.email_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.email_list.customContextMenuRequested.connect(self.show_email_context_menu)
        center_layout.addWidget(self.email_list, 1)

        self.btn_load_older = QPushButton(TRANSLATIONS[self.current_lang]["load_older"])
        self.btn_load_older.setStyleSheet("QPushButton { background-color: #f1f3f4; color: #3c4043; border-radius: 4px; padding: 8px; font-weight: bold; margin-top: 10px; } QPushButton:hover { background-color: #e8eaed; }")
        self.btn_load_older.hide()
        self.btn_load_older.clicked.connect(self.load_older_emails)
        center_layout.addWidget(self.btn_load_older)

        # --- ПРАВАЯ ПАНЕЛЬ ---
        right_panel = QWidget()
        right_panel.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 20, 20, 20)
        action_layout = QHBoxLayout()
        self.btn_reply = QPushButton(TRANSLATIONS[self.current_lang]["reply"])
        self.btn_reply.clicked.connect(self.reply_to_email)
        self.btn_forward = QPushButton(TRANSLATIONS[self.current_lang]["forward"])
        self.btn_forward.clicked.connect(self.forward_email)
        self.btn_save_imp = QPushButton(TRANSLATIONS[self.current_lang]["save_imp"])
        self.btn_save_imp.setStyleSheet("color: #fbbc04; font-weight: bold;")
        self.btn_save_imp.clicked.connect(self.save_important_email)
        self.btn_remove_imp = QPushButton(TRANSLATIONS[self.current_lang]["remove_imp"])
        self.btn_remove_imp.setStyleSheet("color: #5f6368; font-weight: bold;")
        self.btn_remove_imp.clicked.connect(self.remove_important_email)
        self.btn_remove_imp.hide()
        self.btn_browser = QPushButton(TRANSLATIONS[self.current_lang]["open_browser"])
        self.btn_browser.clicked.connect(self.open_in_browser)
        self.btn_browser.setEnabled(False)
        self.btn_source = QPushButton(TRANSLATIONS[self.current_lang]["src_view"])
        self.btn_source.clicked.connect(self.toggle_source_view)
        self.btn_source.setEnabled(False)
        action_layout.addWidget(self.btn_reply)
        action_layout.addWidget(self.btn_forward)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_save_imp)
        action_layout.addWidget(self.btn_remove_imp)
        action_layout.addWidget(self.btn_browser)
        action_layout.addWidget(self.btn_source)
        right_layout.addLayout(action_layout)
        self.email_subject = QLabel(TRANSLATIONS[self.current_lang]["select_email"])
        self.email_subject.setStyleSheet("font-size: 18px; font-weight: bold; color: #202124;")
        self.email_subject.setWordWrap(True)
        self.email_subject.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_layout.addWidget(self.email_subject)
        meta_layout = QHBoxLayout()
        self.lbl_meta = QLabel("")
        self.lbl_meta.setStyleSheet("color: #5f6368; font-size: 12px;")
        self.lbl_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        meta_layout.addWidget(self.lbl_meta)
        self.btn_copy_email = QPushButton(TRANSLATIONS[self.current_lang]["copy_email"])
        self.btn_copy_email.setStyleSheet("QPushButton { padding: 2px 8px; font-size: 11px; border: 1px solid #dadce0; border-radius: 4px; color: #1a73e8; } QPushButton:hover { background-color: #f1f3f4; }")
        self.btn_copy_email.setFixedHeight(22)
        self.btn_copy_email.hide()
        self.btn_copy_email.clicked.connect(self.copy_sender_email)
        meta_layout.addWidget(self.btn_copy_email)
        self.btn_create_contact = QPushButton(TRANSLATIONS[self.current_lang]["create_contact"])
        self.btn_create_contact.setStyleSheet("QPushButton { padding: 2px 8px; font-size: 11px; border: 1px solid #dadce0; border-radius: 4px; color: #1a73e8; } QPushButton:hover { background-color: #f1f3f4; }")
        self.btn_create_contact.setFixedHeight(22)
        self.btn_create_contact.hide()
        self.btn_create_contact.clicked.connect(self.create_contact_from_sender)
        meta_layout.addWidget(self.btn_create_contact)
        meta_layout.addStretch()
        right_layout.addLayout(meta_layout)
        self.lbl_cc = QLabel("")
        self.lbl_cc.setStyleSheet("color: #5f6368; font-size: 12px; margin-bottom: 5px;")
        self.lbl_cc.hide()
        right_layout.addWidget(self.lbl_cc)
        self.attach_list = QListWidget()
        self.attach_list.setFixedHeight(80)
        self.attach_list.setStyleSheet("QListWidget { border: 1px solid #dadce0; border-radius: 4px; background-color: #f8f9fa; } QListWidget::item { padding: 5px; }")
        self.attach_list.itemClicked.connect(self.save_attachment)
        self.attach_list.hide()
        right_layout.addWidget(self.attach_list)
        
        self.html_banner_lbl = QLabel(TRANSLATIONS[self.current_lang]["html_banner"])
        self.html_banner_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.html_banner_lbl.hide()
        right_layout.addWidget(self.html_banner_lbl)
        
        self.email_body = QTextBrowser()
        self.email_body.setOpenExternalLinks(True)
        self.email_body.setStyleSheet("QTextBrowser { border: 1px solid #dadce0; border-radius: 8px; background-color: #ffffff; padding: 15px; font-size: 14px; color: #3c4043; }")
        right_layout.addWidget(self.email_body, 1)
        
        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(labels_panel)
        self.main_splitter.addWidget(center_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setSizes([300, 140, 450, 600])
        main_layout.addWidget(self.main_splitter, 1)
        
        # --- НИЖНЯЯ ПАНЕЛЬ ---
        bottom_bar = QWidget()
        bottom_bar.setFixedHeight(30)
        bottom_bar.setStyleSheet("background-color: #ffffff; border-top: 1px solid #dadce0;")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(10, 0, 10, 0)
        bottom_layout.setSpacing(10)
        
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedSize(20, 20)
        self.btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_help.setStyleSheet("QPushButton { background-color: transparent; color: #888; border: 1px solid #ccc; border-radius: 10px; font-size: 13px; font-weight: bold; padding: 0px; } QPushButton:hover { background-color: #f1f3f4; color: #333; }")
        self.btn_help.clicked.connect(self.show_about_dialog)
        bottom_layout.addWidget(self.btn_help)
        
        self.btn_lang = QPushButton(TRANSLATIONS[self.current_lang]["lang_btn"])
        self.btn_lang.setFixedSize(30, 20)
        self.btn_lang.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lang.setStyleSheet("QPushButton { background-color: transparent; color: #888; border: 1px solid #ccc; border-radius: 4px; font-size: 11px; font-weight: bold; padding: 0px; } QPushButton:hover { background-color: #f1f3f4; color: #333; }")
        self.btn_lang.clicked.connect(self.toggle_language)
        bottom_layout.addWidget(self.btn_lang)
        
        bottom_layout.addStretch()
        
        self.sync_status_lbl = QLabel("")
        self.sync_status_lbl.setStyleSheet("color: #1a73e8; font-weight: bold; font-size: 11px;")
        self.sync_status_lbl.hide()
        bottom_layout.addWidget(self.sync_status_lbl)
        
        self.btn_cancel_sync = QPushButton(TRANSLATIONS[self.current_lang]["sync_cancel"])
        self.btn_cancel_sync.setStyleSheet("QPushButton { color: #c5221f; font-weight: bold; font-size: 11px; border: none; padding: 0px 5px; } QPushButton:hover { text-decoration: underline; }")
        self.btn_cancel_sync.clicked.connect(self.cancel_sync)
        self.btn_cancel_sync.hide()
        bottom_layout.addWidget(self.btn_cancel_sync)
        
        main_layout.addWidget(bottom_bar)
        
        self.refresh_labels_ui()
        
        self.auto_check_timer = QTimer(self)
        self.auto_check_timer.timeout.connect(self.run_background_check)
        self.auto_check_timer.start(30 * 60 * 1000)
        
        QTimer.singleShot(500, self.open_first_inbox)
        
    def init_tray(self):
        t = TRANSLATIONS[self.current_lang]
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists(ICON_PATH): self.tray_icon.setIcon(QIcon(ICON_PATH))
        else: self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray_icon.setToolTip("UlianaMAIL")
        tray_menu = QMenu()
        show_action = QAction(t["tray_show"], self)
        show_action.triggered.connect(self.show_window)
        quit_action = QAction(t["tray_quit"], self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger: self.show_window()
    def show_window(self):
        self.showMaximized()
        self.activateWindow()
    def quit_app(self): QApplication.quit()
    
    def closeEvent(self, event: QCloseEvent):
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def start_thread(self, worker, on_finish, on_error):
        self.active_threads.append(worker)
        worker.finished.connect(on_finish)
        
        def cleanup():
            if worker in self.active_threads:
                self.active_threads.remove(worker)
                
        worker.finished.connect(cleanup)
        
        if hasattr(worker, 'error'):
            worker.error.connect(on_error)
            worker.error.connect(cleanup)
            
        worker.start()

    def run_background_check(self):
        if self.isMinimized() or not self.isVisible():
            self.start_sync()

    def manual_global_check(self):
        self.start_sync()

    def start_sync(self):
        t = TRANSLATIONS[self.current_lang]
        if self.sync_worker and self.sync_worker.isRunning():
            return
            
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, password_enc, imap_server, imap_port FROM accounts WHERE is_active = 1")
            accounts = cursor.fetchall()
            
        if not accounts: return
        
        self.sync_status_lbl.setText(t["sync_starting"])
        self.sync_status_lbl.show()
        self.btn_cancel_sync.show()
        
        self.sync_worker = SyncWorker(accounts)
        self.sync_worker.progress.connect(self.on_sync_progress)
        self.sync_worker.account_status.connect(self.on_sync_status)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.error.connect(self.on_sync_error)
        
        self.btn_refresh_left.setText(t["sync_starting"])
        self.btn_refresh_left.setEnabled(False)
        self.sync_worker.start()

    def on_sync_progress(self, current, total):
        t = TRANSLATIONS[self.current_lang]
        self.sync_status_lbl.setText(t["sync_progress_fmt"].format(current=current, total=total))

    def on_sync_status(self, text):
        t = TRANSLATIONS[self.current_lang]
        self.sync_status_lbl.setText(t["sync_acc_status_fmt"].format(email=text))

    def cancel_sync(self):
        t = TRANSLATIONS[self.current_lang]
        if self.sync_worker:
            self.sync_worker.cancel()
            self.sync_worker.terminate()
        self.sync_status_lbl.hide()
        self.btn_cancel_sync.hide()
        self.btn_refresh_left.setText(t["refresh"])
        self.btn_refresh_left.setEnabled(True)
        self.tray_icon.showMessage("UlianaMAIL", t["sync_cancelled"], QSystemTrayIcon.MessageIcon.Warning, 3000)

    def on_sync_finished(self, new_notifications):
        t = TRANSLATIONS[self.current_lang]
        self.sync_status_lbl.hide()
        self.btn_cancel_sync.hide()
        self.btn_refresh_left.setText(t["refresh"])
        self.btn_refresh_left.setEnabled(True)
        self.update_tree_counts()
        if not self.is_spam_mode:
            self.refresh_current_folder()
        
        for email_addr, count in new_notifications:
            if self.current_lang == "RU":
                word = get_russian_plural(count, "письмо", "письма", "писем")
                msg_text = f"У вас {count} новых {word} в {email_addr}"
            else:
                word = "email" if count == 1 else "emails"
                msg_text = f"You have {count} new {word} in {email_addr}"
            self.tray_icon.showMessage(t["tray_msg_title"], msg_text, QSystemTrayIcon.MessageIcon.Information, 5000)
        
    def on_sync_error(self, err):
        t = TRANSLATIONS[self.current_lang]
        self.sync_status_lbl.hide()
        self.btn_cancel_sync.hide()
        self.btn_refresh_left.setText(t["refresh"])
        self.btn_refresh_left.setEnabled(True)
        self.tray_icon.showMessage("UlianaMAIL", t["sync_error_msg_fmt"].format(err=err), QSystemTrayIcon.MessageIcon.Warning, 5000)

    def load_older_emails(self):
        t = TRANSLATIONS[self.current_lang]
        if not self.current_account_id or self.current_folder not in ("INBOX", "Sent"): return
        
        creds = self.get_account_credentials()
        if not creds: return
        
        self.btn_load_older.setText(t["loading_archive"])
        self.btn_load_older.setEnabled(False)
        
        self.load_older_worker = LoadOlderWorker(self.current_account_id, self.current_account_email, creds['password'], creds['imap_server'], creds['imap_port'], self.current_folder)
        
        def on_progress(current, total):
            self.btn_load_older.setText(t["loading_archive_progress_fmt"].format(current=current, total=total))
            
        def on_done(success):
            self.btn_load_older.setText(t["load_older"])
            self.btn_load_older.setEnabled(True)
            if success:
                self.refresh_current_folder()
            else:
                self.btn_load_older.hide()
                QMessageBox.information(self, t["info_title"], t["no_more_emails"])
                
        def on_err(err):
            self.btn_load_older.setText(t["load_older"])
            self.btn_load_older.setEnabled(True)
            QMessageBox.critical(self, t["err_title"], err)
            
        self.load_older_worker.progress.connect(on_progress)
        self.load_older_worker.finished.connect(on_done)
        self.load_older_worker.error.connect(on_err)
        self.load_older_worker.start()

    def update_tree_counts(self):
        t = TRANSLATIONS[self.current_lang]
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            for i in range(self.tree_accounts.topLevelItemCount()):
                acc_item = self.tree_accounts.topLevelItem(i)
                acc_data = acc_item.data(0, Qt.ItemDataRole.UserRole)
                if acc_data and acc_data.get("type") == "account":
                    acc_id = acc_data["id"]
                    for j in range(acc_item.childCount()):
                        folder_item = acc_item.child(j)
                        f_data = folder_item.data(0, Qt.ItemDataRole.UserRole)
                        if f_data and f_data.get("type") == "folder":
                            f_code = f_data["code"]
                            if f_code == "INBOX":
                                cursor.execute("SELECT COUNT(*) FROM cached_emails WHERE account_id=? AND folder='INBOX' AND is_read=0", (acc_id,))
                                cnt = cursor.fetchone()[0]
                                base_text = t["inbox"]
                                folder_item.setText(0, f"{base_text} ({cnt})" if cnt > 0 else base_text)
                            elif f_code == "Spam":
                                folder_item.setText(0, t["spam"])

    def refresh_labels_ui(self):
        while self.labels_buttons_layout.count():
            child = self.labels_buttons_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, bg_color, text_color, filter_emails, filter_subject FROM labels ORDER BY id")
            self.labels_cache = cursor.fetchall()
        for lbl_id, name, bg, tc, f_em, f_su in self.labels_cache:
            btn = QPushButton(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"QPushButton {{ background-color: {bg or '#e8f0fe'}; color: {tc or '#000000'}; border: none; border-radius: 4px; padding: 6px 8px; text-align: center; font-size: 12px; font-weight: bold; }} QPushButton:hover {{ border: 1px solid #1a73e8; }}")
            btn.setMinimumWidth(60)
            btn.clicked.connect(lambda checked=False, lid=lbl_id: self.on_label_clicked(lid))
            self.labels_buttons_layout.addWidget(btn)
        self.labels_buttons_layout.addStretch()

    def on_label_clicked(self, label_id):
        t = TRANSLATIONS[self.current_lang]
        self.search_input.clear()
        self.email_subject.setText(t["select_email"])
        self.email_body.clear()
        self.btn_source.setEnabled(False)
        self.btn_browser.setEnabled(False)
        self.btn_copy_email.hide()
        self.btn_create_contact.hide()
        self.lbl_meta.setText("")
        self.attach_list.hide()
        self.attach_list.clear()
        self.lbl_cc.hide()
        self.html_banner_lbl.hide()
        self.current_email_data = None
        self.current_raw_bytes = None
        self.current_body_cc = ""
        self.read_timer.stop()
        self.pending_item_to_read = None
        self.current_folder = f"LABEL_{label_id}"
        self.btn_load_older.hide()
        self.is_spam_mode = False
        self.btn_save_imp.hide()
        self.btn_remove_imp.hide()
        
        label_data = next((lbl for lbl in self.labels_cache if lbl[0] == label_id), None)
        if not label_data: return
        f_emails = label_data[4]
        f_subject = label_data[5]
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email FROM accounts WHERE is_active = 1 ORDER BY sort_order ASC LIMIT 1")
            row = cursor.fetchone()
        if not row: return
        self.current_account_id, self.current_account_email = row[0], row[1]
        
        self.load_emails_from_db(folder="ALL", filter_emails=f_emails, filter_subject=f_subject)

    def create_email_item(self, em):
        item = QListWidgetItem()
        w = QWidget()
        main_layout = QVBoxLayout(w)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(2)
        
        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)
        
        star = "⭐ " if em.get('is_important') else ""
        is_unread = em.get('is_read', 0) == 0
        
        from_text = em.get('from_addr', 'Unknown')
        if em.get('is_draft'): from_text = f"<i>{TRANSLATIONS[self.current_lang]['drafts_folder']}</i>"
        if em.get('is_template'): from_text = f"<i>{TRANSLATIONS[self.current_lang]['templates_folder']}</i>"
        
        from_lbl = QLabel()
        from_lbl.setText(f"{star}<b>{from_text}</b>" if is_unread else f"{star}{from_text}")
        top_layout.addWidget(from_lbl)
        
        for lbl_data in self.labels_cache:
            lbl_id, name, bg, tc, f_em, f_su = lbl_data
            if email_matches_label(em.get('from_addr', ''), em.get('subject', ''), f_em, f_su) and not em.get('is_draft') and not em.get('is_template'):
                badge = QLabel(shorten_text(name, 15))
                badge.setStyleSheet(f"""
                    background-color: {bg or '#e8f0fe'}; 
                    color: {tc or '#000'}; 
                    border-radius: 4px; 
                    padding: 2px 6px; 
                    font-size: 10px; 
                    font-weight: bold;
                """)
                top_layout.addWidget(badge)
                
        if em.get('has_attachments'):
            clip = QLabel("📎")
            top_layout.addWidget(clip)
            
        top_layout.addStretch()
        main_layout.addWidget(top_row)
        
        subj_lbl = QLabel()
        subj_text = f"<b>{em.get('subject', 'No Subject')}</b>" if is_unread else em.get('subject', 'No Subject')
        subj_lbl.setText(subj_text)
        subj_lbl.setWordWrap(True)
        main_layout.addWidget(subj_lbl)
        
        date_lbl = QLabel(f"<small style='color:#5f6368;'>{em.get('date_str', '')}</small>")
        main_layout.addWidget(date_lbl)
        
        item.setSizeHint(QSize(0, 90))
        item.setData(Qt.ItemDataRole.UserRole, em)
        return item, w

    def load_emails_from_db(self, folder="INBOX", filter_emails="", filter_subject=""):
        t = TRANSLATIONS[self.current_lang]
        self.email_list.clear()
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM cached_emails WHERE account_id = ?"
            params = [self.current_account_id]
            
            if folder != "ALL":
                query += " AND folder = ?"
                params.append(folder)
                
            query += " ORDER BY CAST(uid AS INTEGER) DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
        if not rows:
            self.email_list.addItem(t["empty_folder"])
            return
            
        for row in rows:
            em = dict(row)
            if filter_emails or filter_subject:
                if not email_matches_label(em['from_addr'], em['subject'], filter_emails, filter_subject):
                    continue
                    
            item, w = self.create_email_item(em)
            self.email_list.addItem(item)
            self.email_list.setItemWidget(item, w)
            
        if folder in ("INBOX", "Sent"):
            self.btn_load_older.show()
        else:
            self.btn_load_older.hide()

    def load_accounts_tree(self):
        t = TRANSLATIONS[self.current_lang]
        current_item = self.tree_accounts.currentItem()
        current_data = current_item.data(0, Qt.ItemDataRole.UserRole) if current_item else None
        self.tree_accounts.clear()
        
        imp_item = QTreeWidgetItem([t["important"]])
        imp_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "special", "code": "IMPORTANT"})
        self.tree_accounts.addTopLevelItem(imp_item)
        
        unread_item = QTreeWidgetItem([t["unread"]])
        unread_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "special", "code": "UNREAD"})
        self.tree_accounts.addTopLevelItem(unread_item)
        
        att_item = QTreeWidgetItem([t["attachments_folder"]])
        att_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "special", "code": "ATTACHMENTS"})
        self.tree_accounts.addTopLevelItem(att_item)
        
        drafts_item = QTreeWidgetItem([t["drafts_folder"]])
        drafts_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "special", "code": "DRAFTS"})
        self.tree_accounts.addTopLevelItem(drafts_item)
        
        templates_item = QTreeWidgetItem([t["templates_folder"]])
        templates_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "special", "code": "TEMPLATES"})
        self.tree_accounts.addTopLevelItem(templates_item)
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email FROM accounts WHERE is_active = 1 ORDER BY sort_order ASC, id ASC")
            accounts = cursor.fetchall()
            
        for acc_id, email_addr in accounts:
            acc_item = QTreeWidgetItem()
            acc_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "account", "id": acc_id})
            self.tree_accounts.addTopLevelItem(acc_item)
            
            acc_widget = QWidget()
            acc_widget.setStyleSheet("background: transparent;")
            acc_layout = QHBoxLayout(acc_widget)
            acc_layout.setContentsMargins(5, 2, 5, 2)
            acc_layout.setSpacing(5)
            
            lbl_email = QLabel(email_addr)
            lbl_email.setStyleSheet("background: transparent; font-weight: bold;")
            acc_layout.addWidget(lbl_email)
            acc_layout.addStretch()
            
            btn_copy = QPushButton("📋")
            btn_copy.setToolTip(t["copy_email_tooltip"])
            btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_copy.setFixedSize(24, 24)
            btn_copy.setStyleSheet("QPushButton { border: none; background: transparent; font-size: 14px; padding: 0px; } QPushButton:hover { background-color: #e8eaed; border-radius: 4px; }")
            btn_copy.clicked.connect(lambda checked=False, e=email_addr: self.copy_account_email(e))
            acc_layout.addWidget(btn_copy)
            
            self.tree_accounts.setItemWidget(acc_item, 0, acc_widget)
            
            for f_name, f_code in [(t["inbox"], "INBOX"), (t["sent"], "Sent"), (t["spam"], "Spam")]:
                folder_item = QTreeWidgetItem([f_name])
                folder_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "acc_id": acc_id, "code": f_code, "email": email_addr})
                acc_item.addChild(folder_item)
            
            acc_item.setExpanded(True)

        if current_data:
            for i in range(self.tree_accounts.topLevelItemCount()):
                acc = self.tree_accounts.topLevelItem(i)
                c_data = acc.data(0, Qt.ItemDataRole.UserRole)
                if current_data.get("type") == "special" and c_data.get("code") == current_data.get("code"):
                    self.tree_accounts.setCurrentItem(acc)
                    break
                for j in range(acc.childCount()):
                    child = acc.child(j)
                    c_data = child.data(0, Qt.ItemDataRole.UserRole)
                    if current_data.get("acc_id") == c_data.get("acc_id") and current_data.get("code") == c_data.get("code"):
                        self.tree_accounts.setCurrentItem(child)
                        break
        else:
            if self.tree_accounts.topLevelItemCount() > 5:
                first_acc = self.tree_accounts.topLevelItem(5)
                self.tree_accounts.setCurrentItem(first_acc)
                
        self.update_tree_counts()

    def on_folder_clicked(self, item, column):
        t = TRANSLATIONS[self.current_lang]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data: return
        self.search_input.clear()
        self.email_subject.setText(t["select_email"])
        self.email_body.clear()
        self.btn_source.setEnabled(False)
        self.btn_browser.setEnabled(False)
        self.btn_copy_email.hide()
        self.btn_create_contact.hide()
        self.lbl_meta.setText("")
        self.attach_list.hide()
        self.attach_list.clear()
        self.current_email_data = None
        self.current_raw_bytes = None
        self.current_body_cc = ""
        self.read_timer.stop()
        self.pending_item_to_read = None
        self.lbl_cc.hide()
        self.html_banner_lbl.hide()
        self.btn_save_imp.hide()
        self.btn_remove_imp.hide()
        self.is_spam_mode = False
        
        if data.get("type") == "special":
            code = data.get("code")
            if code == "UNREAD":
                self.current_folder = "UNREAD"
                self.current_account_id = None
                self.btn_load_older.hide()
                self.show_main_buttons(True)
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM cached_emails WHERE is_read = 0 ORDER BY CAST(uid AS INTEGER) DESC")
                    rows = cursor.fetchall()
                self.email_list.clear()
                for row in rows:
                    em = dict(row)
                    item, w = self.create_email_item(em)
                    self.email_list.addItem(item)
                    self.email_list.setItemWidget(item, w)
                return
            elif code == "IMPORTANT":
                self.current_folder = "IMPORTANT"
                self.current_account_id = None
                self.btn_load_older.hide()
                self.show_main_buttons(True)
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM cached_emails WHERE is_important = 1 ORDER BY CAST(uid AS INTEGER) DESC")
                    rows = cursor.fetchall()
                self.email_list.clear()
                for row in rows:
                    em = dict(row)
                    item, w = self.create_email_item(em)
                    self.email_list.addItem(item)
                    self.email_list.setItemWidget(item, w)
                return
            elif code == "ATTACHMENTS":
                self.current_folder = "ATTACHMENTS"
                self.current_account_id = None
                self.btn_load_older.hide()
                self.show_main_buttons(True)
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM cached_emails WHERE has_attachments = 1 ORDER BY CAST(uid AS INTEGER) DESC")
                    rows = cursor.fetchall()
                self.email_list.clear()
                for row in rows:
                    em = dict(row)
                    item, w = self.create_email_item(em)
                    self.email_list.addItem(item)
                    self.email_list.setItemWidget(item, w)
                return
            elif code in ("DRAFTS", "TEMPLATES"):
                self.current_folder = code
                self.current_account_id = None
                self.btn_load_older.hide()
                self.show_main_buttons(False)
                db_type = "draft" if code == "DRAFTS" else "template"
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM drafts_templates WHERE type=? ORDER BY id DESC", (db_type,))
                    rows = cursor.fetchall()
                    
                    cursor.execute("SELECT DISTINCT draft_id FROM draft_attachments")
                    ids_with_att = {r[0] for r in cursor.fetchall()}
                    
                self.email_list.clear()
                for row in rows:
                    em = {
                        'id': row['id'], 
                        'subject': row['subject'], 
                        'from_addr': row['to_addr'] or "—", 
                        'date_str': row['created_at'],
                        'is_read': 1,
                        'is_draft': (code == "DRAFTS"),
                        'is_template': (code == "TEMPLATES"),
                        'has_attachments': 1 if row['id'] in ids_with_att else 0,
                        'is_local': True,
                        'body_text': row['html_body']
                    }
                    item, w = self.create_email_item(em)
                    self.email_list.addItem(item)
                    self.email_list.setItemWidget(item, w)
                return
                
        if data.get("type") != "folder": return
        self.current_account_id, self.current_folder, self.current_account_email = data["acc_id"], data["code"], data["email"]
        self.show_main_buttons(True)
        
        # === СПАМ: live-режим ===
        if self.current_folder == "Spam":
            self.is_spam_mode = True
            self.btn_load_older.hide()
            self.fetch_spam_list()
            return
        
        self.load_emails_from_db(self.current_folder)

    def show_main_buttons(self, visible):
        self.btn_save_imp.setVisible(visible)
        self.btn_browser.setVisible(visible)
        self.btn_source.setVisible(visible)

    def fetch_spam_list(self):
        """Загружает список последних 50 писем из спама (live, без записи в БД)."""
        t = TRANSLATIONS[self.current_lang]
        creds = self.get_account_credentials()
        if not creds: return
        
        self.email_list.clear()
        self.email_list.addItem(t["spam_loading"])
        self.sync_status_lbl.setText(t["spam_loading"])
        self.sync_status_lbl.show()
        
        self.spam_list_worker = FetchSpamListWorker(
            self.current_account_email, creds['password'],
            creds['imap_server'], creds['imap_port'],
            self.current_account_id, limit=50
        )
        
        def on_done(results):
            self.sync_status_lbl.hide()
            if not self.is_spam_mode or self.current_folder != "Spam":
                return
            self.email_list.clear()
            if not results:
                self.email_list.addItem(t["spam_empty"])
                return
            for em in results:
                item, w = self.create_email_item(em)
                self.email_list.addItem(item)
                self.email_list.setItemWidget(item, w)
                
        def on_err(err):
            self.sync_status_lbl.hide()
            self.email_list.clear()
            self.email_list.addItem(f"{t['spam_load_error']} {err}")
            
        self.spam_list_worker.finished.connect(on_done)
        self.spam_list_worker.error.connect(on_err)
        self.spam_list_worker.start()
    def edit_draft_template(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data: return
        if data.get('is_draft') or data.get('is_template'):
            is_template = data.get('is_template', False)
            dialog = ComposeDialog(self, draft_id=data['id'], is_template=is_template)
            dialog.exec()

    def execute_search(self):
        t = TRANSLATIONS[self.current_lang]
        query = self.search_input.text().strip().lower()
        if not query: 
            self.refresh_current_folder()
            return
        
        # === СПАМ: серверный поиск ===
        if self.is_spam_mode and self.current_folder == "Spam":
            creds = self.get_account_credentials()
            if not creds: return
            self.email_list.clear()
            self.email_list.addItem(t["spam_searching"])
            self.sync_status_lbl.setText(t["spam_searching"])
            self.sync_status_lbl.show()
            
            self.spam_search_worker = FetchSpamSearchWorker(
                self.current_account_email, creds['password'],
                creds['imap_server'], creds['imap_port'],
                self.current_account_id, self.search_input.text().strip()
            )
            
            def on_done(results):
                self.sync_status_lbl.hide()
                if not self.is_spam_mode or self.current_folder != "Spam": return
                self.email_list.clear()
                if not results:
                    self.email_list.addItem(t["spam_search_empty"])
                    return
                for em in results:
                    item, w = self.create_email_item(em)
                    self.email_list.addItem(item)
                    self.email_list.setItemWidget(item, w)
                    
            def on_err(err):
                self.sync_status_lbl.hide()
                self.email_list.clear()
                self.email_list.addItem(f"{t['spam_load_error']} {err}")
                
            self.spam_search_worker.finished.connect(on_done)
            self.spam_search_worker.error.connect(on_err)
            self.spam_search_worker.start()
            return
        
        # === Обычный поиск по локальной базе ===
        found_local = False
        for i in range(self.email_list.count()):
            item = self.email_list.item(i)
            if not item: continue
            d = item.data(Qt.ItemDataRole.UserRole)
            if not d: continue
            text_to_search = f"{d.get('subject', '')} {d.get('from_addr', '')} {d.get('body_text', '')} {d.get('attachment_names', '')}".lower()
            if query in text_to_search:
                item.setHidden(False)
                found_local = True
            else:
                item.setHidden(True)
                
        if not found_local:
            self.email_list.clear()
            self.email_list.addItem(t["local_search_not_found"])

    def refresh_current_folder(self):
        if not self.current_folder: return
        
        if str(self.current_folder).startswith("LABEL_"):
            label_id = int(self.current_folder.split("_")[1])
            self.on_label_clicked(label_id)
            return
        if self.current_folder == "Spam":
            self.fetch_spam_list()
            return
            
        # Поиск нужного элемента в дереве по коду для точного клика
        code_to_find = self.current_folder
        for i in range(self.tree_accounts.topLevelItemCount()):
            it = self.tree_accounts.topLevelItem(i)
            it_data = it.data(0, Qt.ItemDataRole.UserRole)
            if it_data.get("type") == "special" and it_data.get("code") == code_to_find:
                self.on_folder_clicked(it, 0)
                return
                
        # Для папок аккаунтов (INBOX, Sent)
        item = self.tree_accounts.currentItem()
        if item: self.on_folder_clicked(item, 0)

    def update_important_buttons(self):
        """Показывает нужную кнопку: В важные / Убрать из важных."""
        if not self.current_email_data:
            self.btn_save_imp.hide()
            self.btn_remove_imp.hide()
            return
        if self.current_email_data.get('is_draft') or self.current_email_data.get('is_template'):
            self.btn_save_imp.hide()
            self.btn_remove_imp.hide()
            return
        if self.current_email_data.get('is_important'):
            self.btn_save_imp.hide()
            self.btn_remove_imp.show()
        else:
            self.btn_save_imp.show()
            self.btn_remove_imp.hide()

    def on_email_clicked(self, item):
        t = TRANSLATIONS[self.current_lang]
        self.current_email_data = item.data(Qt.ItemDataRole.UserRole)
        if not self.current_email_data: return
        self.read_timer.stop()
        self.pending_item_to_read = None
        
        if self.current_email_data.get('is_draft') or self.current_email_data.get('is_template'):
            self.is_viewing_source = False
            self.btn_source.setEnabled(False)
            self.btn_browser.setEnabled(False)
            self.btn_reply.setEnabled(False)
            self.btn_forward.setEnabled(False)
            self.btn_save_imp.hide()
            self.btn_remove_imp.hide()
            self.email_subject.setText(self.current_email_data['subject'])
            self.lbl_meta.setText(t["dbl_click_to_edit"])
            self.btn_copy_email.hide()
            self.btn_create_contact.hide()
            self.lbl_cc.hide()
            self.html_banner_lbl.hide()
            
            self.email_body.setHtml(self.current_email_data.get('body_text', ''))
            
            self.attach_list.clear()
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT filename FROM draft_attachments WHERE draft_id=?", (self.current_email_data['id'],))
                atts = cursor.fetchall()
                
            if atts:
                self.attach_list.show()
                for att in atts:
                    if not att[0].startswith("cid_"):
                        it = QListWidgetItem(f"📎 {att[0]}")
                        it.setData(Qt.ItemDataRole.UserRole, None)
                        self.attach_list.addItem(it)
            else:
                self.attach_list.hide()
            return

        self.btn_reply.setEnabled(True)
        self.btn_forward.setEnabled(True)
        self.update_important_buttons()
        
        # Для спама не запускаем отметку прочтения
        if self.current_email_data.get('is_read') == 0 and not self.current_email_data.get('is_spam_live'):
            self.pending_item_to_read = item
            self.read_timer.start(3000)
            
        self.is_viewing_source = False
        self.current_raw_source = ""
        self.current_body_html = ""
        self.btn_source.setText(t["src_view"])
        self.btn_source.setEnabled(False)
        self.btn_browser.setEnabled(False)
        self.email_subject.setText(self.current_email_data['subject'])
        self.lbl_meta.setText(f"From: {self.current_email_data['from_addr']} | Date: {self.current_email_data['date_str']}")
        self.btn_copy_email.show()
        self.btn_create_contact.show()
        self.current_body_cc = self.current_email_data.get('cc_addr', '')
        self.update_cc_display(self.current_body_cc)
        
        # Для спама тело пустое — показываем заглушку и включаем кнопки загрузки
        if self.current_email_data.get('is_spam_live'):
            self.html_banner_lbl.hide()
            self.email_body.setPlainText(t["loading"])
            self.btn_source.setEnabled(True)
            self.btn_browser.setEnabled(True)
            self.attach_list.clear()
            # Автоматически подгружаем тело с сервера
            self.fetch_spam_body()
            # Показываем имена вложений, если есть
            if self.current_email_data.get('has_attachments'):
                self.attach_list.show()
                self.attach_list.addItem("📎 (вложения на сервере)")
            else:
                self.attach_list.hide()
            return
        
        if self.current_email_data.get('is_html'):
            self.html_banner_lbl.show()
        else:
            self.html_banner_lbl.hide()
            
        self.email_body.setPlainText(self.current_email_data.get('body_text', 'No text.'))
        self.btn_source.setEnabled(True)
        self.btn_browser.setEnabled(True)
        
        self.attach_list.clear()
        att_names = self.current_email_data.get('attachment_names', '')
        if att_names:
            self.attach_list.show()
            for name in att_names.split(', '):
                if name:
                    it = QListWidgetItem(f"📎 {name}")
                    it.setData(Qt.ItemDataRole.UserRole, name)
                    self.attach_list.addItem(it)
        else: 
            self.attach_list.hide()

    def fetch_spam_body(self):
        """Подгружает тело письма из спама с сервера."""
        if not self.current_email_data or not self.current_email_data.get('is_spam_live'):
            return
        
        t = TRANSLATIONS[self.current_lang]
        creds = self.get_account_credentials()
        if not creds: return
        
        self.email_body.setPlainText(t["fetch_body_title"])
        
        worker = FetchFullEmailWorker(
            self.current_account_email, creds['password'],
            creds['imap_server'], creds['imap_port'],
            self.current_email_data['folder'],
            self.current_email_data['uid']
        )
        self.full_email_worker = worker
        
        def on_done(result):
            if not self.current_email_data or self.current_email_data.get('uid') != worker.uid:
                return
            self.current_body_html = result.get('body_html', '')
            self.current_raw_source = result.get('raw_bytes', b'').decode('utf-8', errors='replace')
            self.current_email_data['body_text'] = result.get('body_text', 'No text.')
            self.current_email_data['is_html'] = 1 if result.get('body_html') else 0
            
            atts = result.get('attachments', [])
            if atts:
                self.current_email_data['has_attachments'] = 1
                self.current_email_data['attachment_names'] = ", ".join([a['filename'] for a in atts])
            
            if self.current_email_data.get('is_html'):
                self.html_banner_lbl.show()
            else:
                self.html_banner_lbl.hide()
                
            self.email_body.setPlainText(self.current_email_data.get('body_text', 'No text.'))
            self.btn_source.setEnabled(True)
            self.btn_browser.setEnabled(True)
            
            self.attach_list.clear()
            if atts:
                self.attach_list.show()
                for att in atts:
                    it = QListWidgetItem(f"📎 {att['filename']}")
                    it.setData(Qt.ItemDataRole.UserRole, att['filename'])
                    self.attach_list.addItem(it)
            else:
                self.attach_list.hide()
                
        def on_err(err):
            self.email_body.setPlainText(t["fetch_body_err_fmt"].format(err=err))
            self.btn_source.setEnabled(False)
            self.btn_browser.setEnabled(False)
            
        self.start_thread(worker, on_done, on_err)

    def download_and_run_action(self, action_type, extra_data=None):
        t = TRANSLATIONS[self.current_lang]
        if not self.current_email_data: return
        
        acc_id = self.current_email_data.get('account_id')
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email, password_enc, imap_server, imap_port FROM accounts WHERE id=?", (acc_id,))
            row = cursor.fetchone()
            
        if not row: return
        acc_email, p_enc, imap_srv, imap_port = row
        password = decrypt_password(p_enc)
        
        dialog = QDialog(self)
        dialog.setWindowTitle("UlianaMAIL")
        dialog.setFixedSize(300, 80)
        layout = QVBoxLayout(dialog)
        
        if action_type == 'html': txt = t["fetching_html"]
        elif action_type == 'attachment': txt = t["fetching_att"]
        else: txt = t["loading"]
        
        lbl = QLabel(txt)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        
        worker = FetchFullEmailWorker(acc_email, password, imap_srv, imap_port, self.current_email_data['folder'], self.current_email_data['uid'])
        self.full_email_worker = worker
        
        def on_finish(result):
            dialog.accept()
            if action_type in ('html', 'source'):
                self.current_body_html = result.get('body_html', '')
                self.current_raw_source = result.get('raw_bytes', b'').decode('utf-8', errors='replace')
                
                if action_type == 'html':
                    if self.current_body_html:
                        self.open_in_browser()
                    else:
                        QMessageBox.warning(self, t["warn_title"], t["no_html_version"])
                elif action_type == 'source':
                    self.is_viewing_source = True
                    self.btn_source.setText(t["src_back"])
                    self.btn_browser.hide()
                    self.email_body.setPlainText(self.current_raw_source)
            elif action_type == 'attachment':
                for att in result.get('attachments', []):
                    if att['filename'] == extra_data:
                        save_path, _ = QFileDialog.getSaveFileName(self, t["save_att"], att['filename'])
                        if save_path:
                            with open(save_path, 'wb') as f: f.write(att['data'])
                            QMessageBox.information(self, t["dlg_ok"], f"{t['saved_ok']}\n{save_path}")
                        break
                        
        def on_err(err):
            dialog.reject()
            QMessageBox.critical(self, t["err_title"], t["load_data_err_fmt"].format(err=err))
            
        dialog.rejected.connect(worker.cancel)
        worker.finished.connect(on_finish)
        worker.error.connect(on_err)
        worker.start()
        dialog.exec()

    def open_in_browser(self):
        t = TRANSLATIONS[self.current_lang]
        if not self.current_body_html:
            self.download_and_run_action('html')
            return
        
        html_content = self.current_body_html
        unique_name = f"mail_{uuid.uuid4().hex}.html"
        file_path = os.path.join(TEMP_ATT_DIR, unique_name)
        try:
            with open(file_path, 'w', encoding='utf-8') as f: 
                f.write(html_content)
            webbrowser.open(f"file://{file_path}")
        except Exception as e:
            QMessageBox.critical(self, t["err_title"], t["browser_open_err_fmt"].format(err=str(e)))

    def save_attachment(self, item):
        att_name = item.data(Qt.ItemDataRole.UserRole)
        if not att_name or att_name == "📎 (вложения на сервере)": return
        t = TRANSLATIONS[self.current_lang]
        
        # Черновики/шаблоны
        if self.current_email_data.get('is_draft') or self.current_email_data.get('is_template'):
            draft_id = self.current_email_data['id']
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data FROM draft_attachments WHERE draft_id=? AND filename=?", (draft_id, att_name))
                row = cursor.fetchone()
                
            if row:
                save_path, _ = QFileDialog.getSaveFileName(self, t["save_att"], att_name)
                if save_path:
                    with open(save_path, 'wb') as f: f.write(row[0])
                    QMessageBox.information(self, t["dlg_ok"], f"{t['saved_ok']}\n{save_path}")
            return
        
        # Письма из кэша с сохранёнными вложениями (Важные из спама)
        email_id = self.current_email_data.get('id')
        if email_id:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data FROM cached_attachments WHERE email_id=? AND filename=?", (email_id, att_name))
                row = cursor.fetchone()
            if row:
                save_path, _ = QFileDialog.getSaveFileName(self, t["save_att"], att_name)
                if save_path:
                    with open(save_path, 'wb') as f: f.write(row[0])
                    QMessageBox.information(self, t["dlg_ok"], f"{t['saved_ok']}\n{save_path}")
                return
        
        # Иначе — с сервера
        self.download_and_run_action('attachment', att_name)

    def toggle_source_view(self):
        t = TRANSLATIONS[self.current_lang]
        if not self.current_raw_source:
            self.download_and_run_action('source')
            return
        self.is_viewing_source = not self.is_viewing_source
        if self.is_viewing_source:
            self.email_body.setPlainText(self.current_raw_source)
            self.btn_source.setText(t["src_back"])
            self.btn_browser.hide()
        else:
            self.btn_source.setText(t["src_view"])
            self.btn_browser.show()
            body = self.current_email_data.get('body_text', '') if self.current_email_data else ''
            self.email_body.setPlainText(body or 'No text.')

    def copy_sender_email(self):
        t = TRANSLATIONS[self.current_lang]
        if not self.current_email_data: return
        raw_from = self.current_email_data.get('from_addr', '')
        clean_email = email.utils.parseaddr(raw_from)[1] or raw_from
        QApplication.clipboard().setText(clean_email)
        self.btn_copy_email.setText(t["copied_toast"])
        QTimer.singleShot(2000, lambda: self.btn_copy_email.setText(t["copy_email"]))

    def create_contact_from_sender(self):
        if not self.current_email_data: return
        raw_from = self.current_email_data.get('from_addr', '')
        clean_email = email.utils.parseaddr(raw_from)[1]
        dialog = ContactDialog(self, default_email=clean_email)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.name_input.text().strip()
            if not name: return
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO contacts (name, email, phone, notes) VALUES (?, ?, ?, ?)", (name, dialog.email_input.text().strip(), dialog.phone_input.text().strip(), dialog.notes_input.toPlainText().strip()))
                conn.commit()
            self.load_contacts()

    def mark_current_email_as_read(self):
        if not self.pending_item_to_read: return
        item = self.pending_item_to_read
        data = item.data(Qt.ItemDataRole.UserRole)
        if self.email_list.row(item) != -1 and data and data.get('is_read') == 0:
            data['is_read'] = 1
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.update_email_item_visuals(item)
            
            # Мгновенное обновление БД и счетчика
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE cached_emails SET is_read=1 WHERE account_id=? AND folder=? AND uid=?", 
                               (data.get('account_id'), data.get('folder'), data.get('uid')))
                conn.commit()
                
            if self.current_folder == "INBOX":
                key = (self.current_account_id, "INBOX")
                if key in self.global_counts and self.global_counts[key] > 0:
                    self.global_counts[key] -= 1
            
            # Обновляем счетчик в дереве
            self.update_tree_counts()

            creds = self.get_account_credentials()
            if creds:
                worker = MarkAsReadWorker(self.current_account_id, self.current_account_email, creds['password'], creds['imap_server'], creds['imap_port'], data['folder'], data['uid'], True)
                self.start_thread(worker, lambda: None, lambda err: None)
        self.pending_item_to_read = None

    def show_email_context_menu(self, pos):
        item = self.email_list.itemAt(pos)
        if not item: return
        selected_items = self.email_list.selectedItems() or [item]
        has_read, has_unread = False, False
        for it in selected_items:
            d = it.data(Qt.ItemDataRole.UserRole)
            if d and not d.get('is_draft') and not d.get('is_template') and not d.get('is_spam_live'):
                if d.get('is_read') == 0: has_unread = True
                else: has_read = True
        menu = QMenu()
        t = TRANSLATIONS[self.current_lang]
        action_mark_read, action_mark_unread = None, None
        if has_unread: action_mark_read = menu.addAction(t["mark_read_selected"])
        if has_read: action_mark_unread = menu.addAction(t["mark_unread_selected"])
        if not has_unread and not has_read: return
        action = menu.exec(self.email_list.mapToGlobal(pos))
        if action == action_mark_read: self.bulk_mark(selected_items, True)
        elif action == action_mark_unread: self.bulk_mark(selected_items, False)

    def bulk_mark(self, selected_items, is_read):
        for item in selected_items:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and not data.get('is_draft') and not data.get('is_template') and not data.get('is_spam_live'):
                data['is_read'] = 1 if is_read else 0
                item.setData(Qt.ItemDataRole.UserRole, data)
                self.update_email_item_visuals(item)
                
                acc_id = data.get('account_id')
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT email, password_enc, imap_server, imap_port FROM accounts WHERE id=?", (acc_id,))
                    row = cursor.fetchone()
                if row:
                    worker = MarkAsReadWorker(acc_id, row[0], decrypt_password(row[1]), row[2], row[3], data['folder'], data['uid'], is_read)
                    self.start_thread(worker, lambda: None, lambda err: None)
        self.update_tree_counts()

    def update_email_item_visuals(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data: return
        new_item, new_w = self.create_email_item(data)
        self.email_list.setItemWidget(item, new_w)
        item.setSizeHint(QSize(0, 90))

    def save_important_email(self):
        t = TRANSLATIONS[self.current_lang]
        if not self.current_email_data or self.current_email_data.get('is_draft') or self.current_email_data.get('is_template'): return
        
        # === СПАМ: полное скачивание и сохранение ===
        if self.current_email_data.get('is_spam_live'):
            creds = self.get_account_credentials()
            if not creds: return
            
            progress_dlg = QDialog(self)
            progress_dlg.setWindowTitle("UlianaMAIL")
            progress_dlg.setFixedSize(400, 100)
            pl = QVBoxLayout(progress_dlg)
            pl.addWidget(QLabel(t["saving_to_important"]))
            prg_lbl = QLabel("")
            pl.addWidget(prg_lbl)
            
            worker = SaveToImportantWorker(
                self.current_account_email, creds['password'],
                creds['imap_server'], creds['imap_port'],
                self.current_account_id,
                self.current_email_data['folder'],
                self.current_email_data['uid']
            )
            self.save_important_worker = worker
            
            def on_progress(cur, tot, fname):
                prg_lbl.setText(t["saving_attachment_fmt"].format(current=cur, total=tot, filename=fname))
                
            def on_done(result):
                progress_dlg.accept()
                if result.get('success'):
                    self.current_email_data['is_important'] = 1
                    self.current_email_data['id'] = result.get('email_id')
                    self.update_important_buttons()
                    msg = t["imp_saved"]
                    if result.get('partial'):
                        msg += "\n(не все вложения удалось скачать)"
                    QMessageBox.information(self, t["success_title"], msg)
                    
            def on_err(err):
                progress_dlg.reject()
                QMessageBox.critical(self, t["err_title"], t["save_to_imp_err_fmt"].format(err=err))
                
            worker.progress.connect(on_progress)
            worker.finished.connect(on_done)
            worker.error.connect(on_err)
            worker.start()
            progress_dlg.exec()
            return
        
        # === Обычное сохранение (INBOX/Sent) ===
        acc_id = self.current_email_data.get('account_id')
        uid = self.current_email_data.get('uid')
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE cached_emails SET is_important=1 WHERE account_id=? AND uid=?", (acc_id, uid))
            conn.commit()
        self.current_email_data['is_important'] = 1
        for i in range(self.email_list.count()):
            it = self.email_list.item(i)
            d = it.data(Qt.ItemDataRole.UserRole)
            if d and d.get('uid') == uid and d.get('folder') == self.current_email_data.get('folder'): 
                self.update_email_item_visuals(it)
                break
        self.update_important_buttons()
        QMessageBox.information(self, t["success_title"], t["imp_saved"])

    def remove_important_email(self):
        t = TRANSLATIONS[self.current_lang]
        if not self.current_email_data or not self.current_email_data.get('is_important'): return
        
        # Для спама (сохранённого ранее) — удаляем запись полностью
        if self.current_email_data.get('is_spam_live') or self.current_email_data.get('folder') == "Spam":
            email_id = self.current_email_data.get('id')
            if email_id:
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM cached_attachments WHERE email_id=?", (email_id,))
                    cursor.execute("DELETE FROM cached_emails WHERE id=?", (email_id,))
                    conn.commit()
            self.current_email_data['is_important'] = 0
            self.current_email_data['id'] = None
            self.update_important_buttons()
            QMessageBox.information(self, t["success_title"], t["removed_imp"])
            return
        
        # Для INBOX/Sent — снимаем флаг
        acc_id = self.current_email_data.get('account_id')
        uid = self.current_email_data.get('uid')
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE cached_emails SET is_important=0 WHERE account_id=? AND uid=?", (acc_id, uid))
            conn.commit()
        self.current_email_data['is_important'] = 0
        for i in range(self.email_list.count()):
            it = self.email_list.item(i)
            d = it.data(Qt.ItemDataRole.UserRole)
            if d and d.get('uid') == uid and d.get('folder') == self.current_email_data.get('folder'):
                self.update_email_item_visuals(it)
                break
        self.update_important_buttons()
        QMessageBox.information(self, t["success_title"], t["removed_imp"])

    def bulk_delete_emails(self):
        selected_items = self.email_list.selectedItems()
        if not selected_items: return
        t = TRANSLATIONS[self.current_lang]
        if not show_custom_confirm(self, t["confirm_title"], t["del_confirm"], self.current_lang): return
        
        local_draft_ids = []
        server_uids = []
        local_email_ids = []
        
        for item in selected_items:
            data = item.data(Qt.ItemDataRole.UserRole)
            if not data: continue
            if data.get('is_draft') or data.get('is_template'):
                local_draft_ids.append(data['id'])
            elif data.get('is_spam_live'):
                server_uids.append(data)
            else:
                local_email_ids.append(data.get('id'))
                if self.current_folder not in ("IMPORTANT", "ATTACHMENTS", "UNREAD") and not str(self.current_folder).startswith("LABEL_"):
                    server_uids.append(data)
                
        # 1. Удаление черновиков/шаблонов
        if local_draft_ids:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                for did in local_draft_ids:
                    cursor.execute("DELETE FROM drafts_templates WHERE id=?", (did,))
                    cursor.execute("DELETE FROM draft_attachments WHERE draft_id=?", (did,))
                conn.commit()
            # Чистим temp-файлы
            try:
                for fname in os.listdir(TEMP_ATT_DIR):
                    for did in local_draft_ids:
                        if fname.startswith(f"draft_{did}_"):
                            try: os.remove(os.path.join(TEMP_ATT_DIR, fname))
                            except Exception: pass
            except Exception: pass
        
        # 2. Удаление с сервера
        if server_uids:
            by_acc_folder = {}
            for data in server_uids:
                acc_id = data.get('account_id')
                folder = data.get('folder')
                key = (acc_id, folder)
                if key not in by_acc_folder:
                    with sqlite3.connect(DB_PATH, timeout=30) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT email, password_enc, imap_server, imap_port FROM accounts WHERE id=?", (acc_id,))
                        acc_row = cursor.fetchone()
                    if acc_row: 
                        by_acc_folder[key] = {'creds': acc_row, 'uids': []}
                if key in by_acc_folder:
                    by_acc_folder[key]['uids'].append(data['uid'])
                    
            for (acc_id, folder), acc_info in by_acc_folder.items():
                acc_email, p_enc, imap_srv, imap_port = acc_info['creds']
                worker = DeleteEmailsWorker(acc_email, decrypt_password(p_enc), imap_srv, imap_port, folder, acc_info['uids'])
                self.start_thread(worker, lambda succ: None, lambda err: None)
        
        # 3. Удаление из локальной БД (+ каскад attachments)
        if local_email_ids:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                for eid in local_email_ids:
                    if eid:
                        cursor.execute("DELETE FROM cached_attachments WHERE email_id=?", (eid,))
                        cursor.execute("DELETE FROM cached_emails WHERE id=?", (eid,))
                conn.commit()
        
        # 4. Убираем из UI
        for item in selected_items:
            row = self.email_list.row(item)
            if row != -1:
                self.email_list.takeItem(row)
            
        self.email_body.clear()
        self.email_subject.setText(t["select_email"])
        self.lbl_meta.setText("")
        self.btn_copy_email.hide()
        self.btn_create_contact.hide()
        self.attach_list.hide()
        self.btn_browser.setEnabled(False)
        self.btn_source.setEnabled(False)
        self.lbl_cc.hide()
        self.html_banner_lbl.hide()
        self.btn_save_imp.hide()
        self.btn_remove_imp.hide()
        self.current_email_data = None
        self.update_tree_counts()

    def show_about_dialog(self):
        t = TRANSLATIONS[self.current_lang]
        dialog = QDialog(self)
        dialog.setWindowTitle(t["about_title"])
        dialog.resize(600, 550)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        text_lbl = QLabel(t["about_content"])
        text_lbl.setWordWrap(True)
        text_lbl.setTextFormat(Qt.TextFormat.RichText)
        text_lbl.setOpenExternalLinks(True)
        text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        content_layout.addWidget(text_lbl)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        btn_close = QPushButton(t["close"])
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def toggle_language(self):
        self.current_lang = "EN" if self.current_lang == "RU" else "RU"
        app = QApplication.instance()
        if self.qt_translator is not None:
            app.removeTranslator(self.qt_translator)
            if self.current_lang == "RU":
                app.installTranslator(self.qt_translator)
        self.retranslate_ui()

    def retranslate_ui(self):
        t = TRANSLATIONS[self.current_lang]
        self.setWindowTitle(t["app_title"])
        self.title_lbl.setText(t["app_title"])
        self.btn_compose.setText(t["compose"])
        self.btn_settings.setText(t["settings"])
        self.btn_refresh_left.setText(t["refresh"])
        self.search_input.setPlaceholderText(t["search_ph"])
        self.contact_search_input.setPlaceholderText(t["contact_search_ph"])
        self.btn_bulk_del.setText(t["bulk_del"])
        self.btn_reply.setText(t["reply"])
        self.btn_forward.setText(t["forward"])
        self.btn_save_imp.setText(t["save_imp"])
        self.btn_remove_imp.setText(t["remove_imp"])
        self.btn_browser.setText(t["open_browser"])
        self.btn_copy_email.setText(t["copy_email"])
        self.btn_create_contact.setText(t["create_contact"])
        self.contacts_lbl.setText(t["contacts_title"])
        self.btn_add_contact.setText(t["add_contact"])
        self.btn_import_vcf.setText(t["import_vcf"])
        self.btn_export_vcf.setText(t["export_vcf"])
        self.btn_load_older.setText(t["load_older"])
        self.btn_cancel_sync.setText(t["sync_cancel"])
        self.btn_lang.setText(t["lang_btn"])
        self.html_banner_lbl.setText(t["html_banner"])
        if self.is_viewing_source: self.btn_source.setText(t["src_back"])
        else: self.btn_source.setText(t["src_view"])
        if not self.current_email_data: self.email_subject.setText(t["select_email"])
        elif self.current_body_cc: self.update_cc_display(self.current_body_cc)
        
        # Трей-меню
        tray_menu = QMenu()
        show_action = QAction(t["tray_show"], self)
        show_action.triggered.connect(self.show_window)
        quit_action = QAction(t["tray_quit"], self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        
        self.load_accounts_tree()
        self.load_contacts()
        self.update_tree_counts()
        self.refresh_labels_ui()
        if self.current_folder: self.refresh_current_folder()

    def open_first_inbox(self):
        for i in range(self.tree_accounts.topLevelItemCount()):
            acc = self.tree_accounts.topLevelItem(i)
            if acc.childCount() > 0:
                first_folder = acc.child(0)
                self.tree_accounts.setCurrentItem(first_folder)
                self.on_folder_clicked(first_folder, 0)
                break

    def show_account_context_menu(self, pos):
        item = self.tree_accounts.itemAt(pos)
        if not item: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data.get("type") == "account":
            menu = QMenu()
            action_up = menu.addAction("⬆️ Up"); action_down = menu.addAction("⬇️ Down")
            action = menu.exec(self.tree_accounts.mapToGlobal(pos))
            if action == action_up: self.move_account(data["id"], -1)
            elif action == action_down: self.move_account(data["id"], 1)

    def move_account(self, acc_id, direction):
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sort_order FROM accounts WHERE id=?", (acc_id,))
            current_order = cursor.fetchone()[0]
            if direction == -1: cursor.execute("SELECT id, sort_order FROM accounts WHERE sort_order < ? ORDER BY sort_order DESC LIMIT 1", (current_order,))
            else: cursor.execute("SELECT id, sort_order FROM accounts WHERE sort_order > ? ORDER BY sort_order ASC LIMIT 1", (current_order,))
            target = cursor.fetchone()
            if target:
                target_id, target_order = target
                cursor.execute("UPDATE accounts SET sort_order=? WHERE id=?", (target_order, acc_id))
                cursor.execute("UPDATE accounts SET sort_order=? WHERE id=?", (current_order, target_id))
                conn.commit()
        self.load_accounts_tree()

    def get_account_credentials(self):
        if not self.current_account_id: return None
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password_enc, imap_server, imap_port, smtp_server, smtp_port FROM accounts WHERE id = ?", (self.current_account_id,))
            row = cursor.fetchone()
        if row: 
            return {'password': decrypt_password(row[0]), 'imap_server': row[1], 'imap_port': row[2], 'smtp_server': row[3], 'smtp_port': row[4]}
        return None

    def copy_account_email(self, email_addr):
        QApplication.clipboard().setText(email_addr)
        t = TRANSLATIONS[self.current_lang]
        self.tray_icon.showMessage("UlianaMAIL", t["copied_toast"], QSystemTrayIcon.MessageIcon.Information, 2000)

    def open_compose_dialog(self, to_addr=""):
        dialog = ComposeDialog(self, to_addr=to_addr)
        dialog.exec()

    def reply_to_email(self):
        if not self.current_email_data or self.current_email_data.get('is_draft') or self.current_email_data.get('is_template'): return
        em = self.current_email_data
        acc_id = em.get('account_id')
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM accounts WHERE id=?", (acc_id,))
            row = cursor.fetchone()
        default_sender = row[0] if row else ""
        
        to_email = email.utils.parseaddr(em['from_addr'])[1]
        body_text = em.get('body_text', '') or ''
        quoted_body = f"<br><br><div style='color: #5f6368;'>--- Original Message ---<br>From: {em['from_addr']}<br>Date: {em['date_str']}</div><blockquote style='margin: 0; padding-left: 10px; border-left: 2px solid #dadce0; color: #5f6368;'>{html.escape(body_text).replace(chr(10), '<br>')}</blockquote>"
        dialog = ComposeDialog(self, to_addr=to_email, subject=f"Re: {em['subject']}", body=quoted_body, default_sender=default_sender)
        dialog.exec()

    def forward_email(self):
        if not self.current_email_data or self.current_email_data.get('is_draft') or self.current_email_data.get('is_template'): return
        em = self.current_email_data
        acc_id = em.get('account_id')
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM accounts WHERE id=?", (acc_id,))
            row = cursor.fetchone()
        default_sender = row[0] if row else ""
        
        body_text = em.get('body_text', '') or ''
        quoted_body = f"<br><br><div style='color: #5f6368;'>--- Forwarded Message ---<br>From: {em['from_addr']}<br>Date: {em['date_str']}<br>Subject: {em['subject']}</div><blockquote style='margin: 0; padding-left: 10px; border-left: 2px solid #dadce0; color: #5f6368;'>{html.escape(body_text).replace(chr(10), '<br>')}</blockquote>"
        dialog = ComposeDialog(self, subject=f"Fwd: {em['subject']}", body=quoted_body, default_sender=default_sender)
        dialog.exec()

    def update_cc_display(self, cc_string):
        if not cc_string: self.lbl_cc.hide(); return
        cc_addresses = email.utils.getaddresses([cc_string])
        my_email = self.current_account_email.lower() if self.current_account_email else ""
        display_list = [addr for name, addr in cc_addresses if addr and addr.lower() != my_email]
        if display_list:
            t = TRANSLATIONS[self.current_lang]
            self.lbl_cc.setText(f"<b>{t['cc_display']}</b> {', '.join(display_list)}")
            self.lbl_cc.show()
        else: self.lbl_cc.hide()

    def load_contacts(self):
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, email, phone, notes FROM contacts ORDER BY name ASC")
            self.all_contacts = cursor.fetchall()
        self.refresh_contacts_ui()
        
    def filter_contacts(self, text):
        self.contact_filter_text = text.strip().lower()
        self.refresh_contacts_ui()
        
    def refresh_contacts_ui(self):
        self.contacts_list.clear()
        query = self.contact_filter_text
        filtered = [c for c in self.all_contacts if not query or query in (c[1] or "").lower() or query in (c[2] or "").lower() or query in (c[3] or "").lower() or query in (c[4] or "").lower()]
        if not filtered:
            item = QListWidgetItem(TRANSLATIONS[self.current_lang]["no_contacts"])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(Qt.gray)
            self.contacts_list.addItem(item)
            return
        for c in filtered:
            contact_id, name, email_addr, phone, notes = c
            item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, contact_id)
            widget = QWidget(); layout = QVBoxLayout(widget); layout.setContentsMargins(8, 6, 8, 6); layout.setSpacing(2)
            name_text = f"👤 {name}"; name_text += f" ({email_addr})" if email_addr else ""
            lbl_name = QLabel(name_text); lbl_name.setStyleSheet("font-weight: bold; color: #202124;"); layout.addWidget(lbl_name)
            if notes:
                display_notes = notes.replace('\n', ' '); display_notes = display_notes[:42] + "..." if len(display_notes) > 45 else display_notes
                lbl_notes = QLabel(display_notes); lbl_notes.setStyleSheet("color: #5f6368; font-size: 11px;"); layout.addWidget(lbl_notes)
            item.setSizeHint(widget.sizeHint()); self.contacts_list.addItem(item); self.contacts_list.setItemWidget(item, widget)
            
    def add_contact_dialog(self):
        dialog = ContactDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.name_input.text().strip()
            if not name: return
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO contacts (name, email, phone, notes) VALUES (?, ?, ?, ?)", (name, dialog.email_input.text().strip(), dialog.phone_input.text().strip(), dialog.notes_input.toPlainText().strip()))
                conn.commit()
            self.load_contacts()
            
    def edit_contact_dialog(self, item):
        contact_id = item.data(Qt.ItemDataRole.UserRole)
        if not contact_id: return
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, email, phone, notes FROM contacts WHERE id=?", (contact_id,))
            data = cursor.fetchone()
        if data:
            dialog = ContactDialog(self, contact_data=data)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                name = dialog.name_input.text().strip()
                if not name: return
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE contacts SET name=?, email=?, phone=?, notes=? WHERE id=?", (name, dialog.email_input.text().strip(), dialog.phone_input.text().strip(), dialog.notes_input.toPlainText().strip(), contact_id))
                    conn.commit()
                self.load_contacts()
                
    def show_contact_context_menu(self, pos):
        item = self.contacts_list.itemAt(pos)
        if not item: return
        contact_id = item.data(Qt.ItemDataRole.UserRole)
        if not contact_id: return
        menu = QMenu(); t = TRANSLATIONS[self.current_lang]
        action_compose = menu.addAction(t["compose"])
        action_edit = menu.addAction(t["dlg_edit"])
        menu.addSeparator()
        action_del = menu.addAction(t["dlg_del"])
        
        action = menu.exec(self.contacts_list.mapToGlobal(pos))
        
        if action == action_compose:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT email FROM contacts WHERE id=?", (contact_id,))
                row = cursor.fetchone()
            email_addr = row[0] if row else ""
            if not email_addr: QMessageBox.warning(self, t["err_title"], t["no_email_err"]); return
            self.open_compose_dialog(to_addr=email_addr)
        elif action == action_edit:
            self.edit_contact_dialog(item)
        elif action == action_del:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
                conn.commit()
            self.load_contacts()

    def import_vcf(self):
        t = TRANSLATIONS[self.current_lang]
        file_path, _ = QFileDialog.getOpenFileName(self, t["import_vcf"], "", "vCard Files (*.vcf)")
        if not file_path: return
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            cards = re.findall(r'BEGIN:VCARD.*?END:VCARD', content, re.DOTALL)
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                count = 0
                for card in cards:
                    name, email_addr, phone, notes = "", "", "", ""
                    for line in card.splitlines():
                        if line.startswith('FN:'): name = line[3:].strip()
                        elif line.startswith('EMAIL'): email_addr = line.split(':', 1)[-1].strip()
                        elif line.startswith('TEL'): phone = line.split(':', 1)[-1].strip()
                        elif line.startswith('NOTE'): notes = line[5:].strip()
                    if name:
                        cursor.execute("INSERT INTO contacts (name, email, phone, notes) VALUES (?, ?, ?, ?)", (name, email_addr, phone, notes))
                        count += 1
                conn.commit()
            self.load_contacts()
            QMessageBox.information(self, t["success_title"], t["import_success_fmt"].format(count=count))
        except Exception as e: 
            QMessageBox.critical(self, t["err_title"], t["import_err_fmt"].format(err=str(e)))

    def export_vcf(self):
        t = TRANSLATIONS[self.current_lang]
        file_path, _ = QFileDialog.getSaveFileName(self, t["export_vcf"], "contacts.vcf", "vCard Files (*.vcf)")
        if not file_path: return
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name, email, phone, notes FROM contacts")
                contacts = cursor.fetchall()
            with open(file_path, 'w', encoding='utf-8') as f:
                for c in contacts:
                    f.write("BEGIN:VCARD\nVERSION:3.0\n")
                    f.write(f"FN:{c[0]}\n")
                    if c[1]: f.write(f"EMAIL:{c[1]}\n")
                    if c[2]: f.write(f"TEL:{c[2]}\n")
                    if c[3]: f.write(f"NOTE:{c[3]}\n")
                    f.write("END:VCARD\n")
            QMessageBox.information(self, t["success_title"], t["export_success_fmt"].format(count=len(contacts)))
        except Exception as e: 
            QMessageBox.critical(self, t["err_title"], t["export_err_fmt"].format(err=str(e)))

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("UlianaMAIL")
    app.setStyle("Fusion")
    
    translator = QTranslator()
    if translator.load("qtbase_ru", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        
    if os.path.exists(ICON_PATH): app.setWindowIcon(QIcon(ICON_PATH))
    app.setStyleSheet("""
        QWidget { font-family: 'Segoe UI', 'Roboto', sans-serif; font-size: 13px; color: #3c4043; }
        #leftPanel { background-color: #f8f9fa; border: none; }
        #centerPanel, #rightPanel { background-color: #ffffff; }
        #topPanel { background-color: #ffffff; }
        QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 18px; padding: 8px 16px; font-weight: 500; color: #3c4043; }
        QPushButton:hover { background-color: #f1f3f4; }
        #primaryBtn { background-color: #1a73e8; color: #ffffff; border-radius: 4px; padding: 8px 24px; font-weight: bold; }
        #primaryBtn:hover { background-color: #1557b0; }
        QLineEdit, QTextEdit, QSpinBox, QTextBrowser { border: 1px solid #dadce0; border-radius: 4px; padding: 8px; background-color: #ffffff; }
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QTextBrowser:focus { border: 1px solid #1a73e8; }
    """)
    
    socket = QLocalSocket()
    socket.connectToServer("UlianaMAIL_Server_Unique")
    if socket.waitForConnected(500):
        socket.write(b"show")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        sys.exit(0)
    else:
        server = QLocalServer()
        QLocalServer.removeServer("UlianaMAIL_Server_Unique")
        server.listen("UlianaMAIL_Server_Unique")
        
        window = MainWindow()
        window.qt_translator = translator
        window.showMaximized()
        
        def new_connection():
            client = server.nextPendingConnection()
            if client.waitForReadyRead(1000):
                client.readAll()
            window.showMaximized()
            window.activateWindow()
            
        server.newConnection.connect(new_connection)
        sys.exit(app.exec())
