import telebot
from telebot import types
import psutil
import os
import subprocess
from datetime import datetime

TOKEN = '85FH04oU'
bot = telebot.TeleBot(TOKEN)

def main_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('📊 Статус MARVEL')
    btn2 = types.KeyboardButton('🌐 Сеть')
    btn3 = types.KeyboardButton('📂 Топ процессов')
    btn4 = types.KeyboardButton('🖥 Управление')
    markup.add(btn1, btn2, btn3, btn4)
    return markup

@bot.message_handler(func=lambda m: m.text == '📊 Статус MARVEL')
def send_status(message):
    cpu_usage = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    
    status_text = (
        f"🖥 **СЕРВЕР MARVEL**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🚀 **ЦП:** {cpu_usage}%\n"
        f"🧠 **ОЗУ:** {ram.percent}% ({ram.used // (1024**2)}MB / {ram.total // (1024**2)}MB)\n"
        f"💾 **Диск:** {disk.free // (1024**3)} GB свободно\n"
        f"⏱ **Запущен:** {boot_time}"
    )
    bot.send_message(message.chat.id, status_text, parse_mode='Markdown', reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text == '🌐 Сеть')
def network_status(message):
    net = psutil.net_io_counters()
    # ИСПРАВЛЕНО: используем bytes_sent и bytes_recv
    net_text = (
        f"🌐 **ТРАФИК СЕРВЕРА**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📤 Отправлено: {net.bytes_sent // (1024**2)} MB\n"
        f"📥 Получено: {net.bytes_recv // (1024**2)} MB"
    )
    bot.send_message(message.chat.id, net_text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '📂 Топ процессов')
def top_procs(message):
    procs = sorted(psutil.process_iter(['pid', 'name', 'cpu_percent']), key=lambda x: x.info['cpu_percent'], reverse=True)[:5]
    text = "🔝 **ТОП-5 ПРОЦЕССОВ:**\n\n"
    for p in procs:
        text += f"🔹 {p.info['name']} (PID: {p.info['pid']}) — {p.info['cpu_percent']}%\n"
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['cmd'])
def execute_command(message):
    command = message.text.replace('/cmd ', '')
    try:
        output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=5)
        bot.send_message(message.chat.id, f"✅ **Результат:**\n`{output.decode('utf-8')[:4000]}`", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **Ошибка:**\n`{str(e)}`", parse_mode='Markdown')

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Мега-Помощник активен! Мониторю сервер MARVEL.", reply_markup=main_markup())

if __name__ == '__main__':
    print("Исправленный помощник запущен!")
    bot.infinity_polling()
