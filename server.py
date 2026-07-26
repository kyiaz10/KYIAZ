#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orbit Task Manager - Backend Server
Flask API + SQLite Database + Telegram Bot
Многопользовательская система с поддержкой Telegram Mini App
"""

import sqlite3
import threading
import logging
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация Telegram бота
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Замените на ваш токен от @BotFather

# База данных SQLite
DB_PATH = "orbit.db"

def get_db():
    """Получить подключение к базе данных"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Инициализация базы данных"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица категорий
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
    """)
    
    # Таблица задач
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            text TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            priority TEXT DEFAULT 'medium',
            category_id INTEGER,
            deadline TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def create_default_categories(telegram_id):
    """Создать категории по умолчанию для нового пользователя"""
    conn = get_db()
    cursor = conn.cursor()
    
    default_cats = ["Личное", "Работа"]
    for cat_name in default_cats:
        cursor.execute("""
            INSERT OR IGNORE INTO categories (user_id, name)
            SELECT ?, ? WHERE NOT EXISTS (
                SELECT 1 FROM categories WHERE user_id = ? AND name = ?
            )
        """, (telegram_id, cat_name, telegram_id, cat_name))
    
    conn.commit()
    conn.close()

@app.route('/api/register', methods=['POST'])
def register_user():
    """Регистрация/авторизация пользователя"""
    data = request.json
    telegram_id = data.get('telegram_id')
    username = data.get('username')
    
    if not telegram_id:
        return jsonify({'success': False, 'error': 'Telegram ID обязателен'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username))
            conn.commit()
            create_default_categories(telegram_id)
            logger.info(f"Новый пользователь зарегистрирован: {telegram_id}")
        else:
            if username and username != user['username']:
                cursor.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
                conn.commit()
        
        return jsonify({'success': True, 'telegram_id': telegram_id})
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Получить все задачи пользователя"""
    telegram_id = request.args.get('telegram_id')
    
    if not telegram_id:
        return jsonify({'tasks': []}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT t.*, c.name as category_name
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.user_id = ?
            ORDER BY t.is_favorite DESC, 
                     CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END,
                     t.created_at DESC
        """, (telegram_id,))
        
        tasks = []
        for row in cursor.fetchall():
            tasks.append({
                'id': row['id'],
                'text': row['text'],
                'completed': bool(row['completed']),
                'is_favorite': bool(row['is_favorite']),
                'priority': row['priority'],
                'category_id': row['category_id'],
                'category_name': row['category_name'],
                'deadline': row['deadline'],
                'created_at': row['created_at']
            })
        
        return jsonify({'tasks': tasks})
    except Exception as e:
        logger.error(f"Ошибка получения задач: {e}")
        return jsonify({'tasks': [], 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Создать новую задачу"""
    data = request.json
    telegram_id = data.get('telegram_id')
    text = data.get('text')
    priority = data.get('priority', 'medium')
    category_id = data.get('category_id')
    deadline = data.get('deadline')
    is_favorite = data.get('is_favorite', False)
    
    if not telegram_id or not text:
        return jsonify({'success': False, 'error': 'telegram_id и text обязательны'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO tasks (user_id, text, priority, category_id, deadline, is_favorite)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (telegram_id, text, priority, category_id, deadline, 1 if is_favorite else 0))
        
        conn.commit()
        task_id = cursor.lastrowid
        
        return jsonify({'success': True, 'task_id': task_id})
    except Exception as e:
        logger.error(f"Ошибка создания задачи: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    """Обновить задачу"""
    data = request.json
    telegram_id = data.get('telegram_id')
    
    if not telegram_id:
        return jsonify({'success': False, 'error': 'telegram_id обязателен'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        updates = []
        values = []
        
        if 'completed' in data:
            updates.append('completed = ?')
            values.append(1 if data['completed'] else 0)
        
        if 'is_favorite' in data:
            updates.append('is_favorite = ?')
            values.append(1 if data['is_favorite'] else 0)
        
        if not updates:
            return jsonify({'success': False, 'error': 'Нет данных для обновления'}), 400
        
        values.append(task_id)
        values.append(telegram_id)
        
        query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
        cursor.execute(query, values)
        
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'error': 'Задача не найдена'}), 404
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Ошибка обновления задачи: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Удалить задачу"""
    telegram_id = request.args.get('telegram_id')
    
    if not telegram_id:
        return jsonify({'success': False, 'error': 'telegram_id обязателен'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, telegram_id))
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'error': 'Задача не найдена'}), 404
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Ошибка удаления задачи: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/categories', methods=['GET'])
def get_categories():
    """Получить все категории пользователя"""
    telegram_id = request.args.get('telegram_id')
    
    if not telegram_id:
        return jsonify({'categories': []}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, name, created_at
            FROM categories
            WHERE user_id = ?
            ORDER BY created_at ASC
        """, (telegram_id,))
        
        categories = []
        for row in cursor.fetchall():
            categories.append({
                'id': row['id'],
                'name': row['name'],
                'created_at': row['created_at']
            })
        
        return jsonify({'categories': categories})
    except Exception as e:
        logger.error(f"Ошибка получения категорий: {e}")
        return jsonify({'categories': [], 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/categories', methods=['POST'])
def create_category():
    """Создать новую категорию"""
    data = request.json
    telegram_id = data.get('telegram_id')
    name = data.get('name')
    
    if not telegram_id or not name:
        return jsonify({'success': False, 'error': 'telegram_id и name обязательны'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO categories (user_id, name)
            VALUES (?, ?)
        """, (telegram_id, name))
        
        conn.commit()
        category_id = cursor.lastrowid
        
        return jsonify({'success': True, 'category_id': category_id})
    except Exception as e:
        logger.error(f"Ошибка создания категории: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Получить статистику пользователя"""
    telegram_id = request.args.get('telegram_id')
    
    if not telegram_id:
        return jsonify({'stats': {}}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN completed = 0 AND priority = 'high' THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN completed = 0 AND priority = 'medium' THEN 1 ELSE 0 END) as medium,
                SUM(CASE WHEN completed = 0 AND priority = 'low' THEN 1 ELSE 0 END) as low,
                SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as completed
            FROM tasks
            WHERE user_id = ?
        """, (telegram_id,))
        
        row = cursor.fetchone()
        
        stats = {
            'total': row['total'] or 0,
            'high': row['high'] or 0,
            'medium': row['medium'] or 0,
            'low': row['low'] or 0,
            'completed': row['completed'] or 0
        }
        
        return jsonify({'stats': stats})
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return jsonify({'stats': {}, 'error': str(e)}), 500
    finally:
        conn.close()

# ========== TELEGRAM BOT ==========

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "Добро пожаловать в Orbit!\n\n"
        "Я ваш космический помощник для управления задачами.\n\n"
        "Просто отправьте мне текст задачи, и я сохраню её в вашем списке.\n"
        "Например: Помыть машину или Купить молоко"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений - создание задач"""
    text = update.message.text.strip()
    telegram_id = str(update.message.from_user.id)
    username = update.message.from_user.username
    
    if not text:
        return
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username))
            conn.commit()
            create_default_categories(telegram_id)
        
        cursor.execute("""
            INSERT INTO tasks (user_id, text, priority)
            VALUES (?, ?, 'medium')
        """, (telegram_id, text))
        
        conn.commit()
        task_id = cursor.lastrowid
        
        await update.message.reply_text(
            f"Задача сохранена!\n\n"
            f"{text}\n\n"
            f"Откройте приложение Orbit чтобы увидеть все ваши задачи."
        )
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения от {telegram_id}: {e}")
        await update.message.reply_text("Произошла ошибка при сохранении задачи. Попробуйте позже.")
    finally:
        conn.close()

def run_telegram_bot():
    """Запуск Telegram бота в отдельном потоке"""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.warning("Telegram bot token не настроен. Бот не будет запущен.")
        return
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    init_database()
    
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    logger.info("Запуск сервера на порту 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
