# -*- coding: utf-8 -*-
from flask import Flask, render_template_string, request, redirect, url_for
import sqlite3
import requests
import json
from datetime import datetime, timedelta
from flask import send_from_directory

app = Flask(__name__)
DB_PATH = '/root/my_bot/mark_empire_final.db'
from aiogram import F, types
from aiogram.types import LabeledPrice, PreCheckoutQuery
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")


GUYS_MODERATORS = {
    "Матвей 19 лет": 733,
    "Мафия 18": 702,
    "Марк 25 лет": 2681, 
    "Саня 17": 6470,
    "Кларк 20": 52484
}


HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>MARK CRM | Ultimate Control</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root { --bg:#0d0d0d; --card:#1a1a1a; --text:#f0f0f0; --accent:#ff4d94; --secondary:#00f2ff; --info:#4a90e2; --busy:#ff9800; }
body { background:var(--bg); color:var(--text); font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding:20px; margin:0;}
.container{max-width:1700px;margin:auto;}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:30px;}
.stat-card{background:var(--card);padding:20px;border-radius:15px;border:1px solid #2a2a2a;transition:.3s;position:relative;overflow:hidden;}
.stat-card:hover{border-color:var(--accent);transform:translateY(-3px);}
.stat-card h4{margin:0 0 10px 0;font-size:12px;text-transform:uppercase;color:#888;letter-spacing:1px;}
.stat-card .val{font-size:28px;color:var(--accent);font-weight:800;}
.charts-container{display:grid;grid-template-columns:2fr 1fr;gap:20px;margin-bottom:30px;}
.chart-box{background:var(--card);padding:20px;border-radius:15px;border:1px solid #2a2a2a;height:300px;}
.box{background:var(--card);padding:20px;border-radius:15px;margin-bottom:25px;border:1px solid #2a2a2a;}
.mod-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;}
.mod-card{background:#111;padding:15px;border-radius:12px;border:1px solid #333;text-align:center;}
.mod-name{font-size:13px;font-weight:bold;margin-bottom:8px;}
.status-badge{font-size:10px;padding:4px 8px;border-radius:20px;text-transform:uppercase;font-weight:bold;}
.status-online{background:rgba(0,255,0,.1);color:#00ff00;}
.status-offline{background:rgba(255,0,0,.1);color:#ff4d4d;}
.status-busy{background:rgba(255,152,0,.1);color:var(--busy);}
table{width:100%;border-collapse:separate;border-spacing:0 8px;}
th{padding:15px;text-align:left;color:#666;font-size:11px;text-transform:uppercase;}
td{background:var(--card);padding:15px;border-top:1px solid #2a2a2a;border-bottom:1px solid #2a2a2a;}
td:first-child{border-left:1px solid #2a2a2a;border-radius:12px 0 0 12px;}
td:last-child{border-right:1px solid #2a2a2a;border-radius:0 12px 12px 0;}
.search-box input{width:100%;padding:15px;background:var(--card);border:1px solid #2a2a2a;color:#fff;border-radius:12px;font-size:16px;margin-bottom:20px;box-sizing:border-box;}
.btn{padding:8px 12px;border:none;border-radius:8px;cursor:pointer;font-weight:bold;font-size:11px;transition:.2s;}
.btn:hover{filter:brightness(1.2);}
.btn-vip{background:var(--secondary);color:#000;}
.btn-unvip{background:#ff4d4d;color:#fff;}
.btn-del{background:#cf6679;color:#fff;}
.btn-send{background:var(--info);color:#fff;}
</style>
</head>
<body>
<div class="container">
<div style="display:flex; justify-content: space-between; align-items: center;">
<h1 style="color: var(--accent); letter-spacing:-1px;">MARK CRM <span style="color:#fff;font-weight:200;">v3.0</span></h1>
<div id="clock" style="font-weight:bold;color:var(--secondary);"></div>
</div>
<div class="box">
    <h3 style="margin-top:0; font-size:14px; color: var(--accent);">👥 Статус модераторов</h3>
    <div class="mod-grid">
    {% for m in moderators %}
    <div class="mod-card" style="position: relative;">
        <div class="mod-name">{{ m.name }}</div>
        
        <form action="/toggle_mod_status/{{ m.id }}" method="POST">
            <button type="submit" class="btn" style="background: none; border: none; cursor: pointer; padding: 0;">
                {% if m.busy %}
                    <span class="status-badge status-busy">ЗАНЯТ</span>
                {% elif m.online %}
                    <span class="status-badge status-online">● ОНЛАЙН</span>
                {% else %}
                    <span class="status-badge status-offline">○ ОФФЛАЙН</span>
                {% endif %}
            </button>
        </form>

        <div style="font-size: 9px; color: #555; margin-top: 5px;">
            ID: {{ m.id }}
        </div>
    </div>
    {% endfor %}
</div>


</div>


<div class="stats-grid">
<div class="stat-card"><h4>Юзеры</h4><div class="val">{{ total_users }}</div></div>
<div class="stat-card"><h4>VIP Королевы</h4><div class="val" style="color:var(--secondary);">{{ vip_users }}</div></div>
<div class="stat-card"><h4>Записи в Дневниках</h4><div class="val">{{ total_notes }}</div></div>
<div class="stat-card"><h4>Всего XP</h4><div class="val">{{ total_xp }}</div></div>
</div>

<div class="charts-container">
<div class="chart-box"><canvas id="regChart"></canvas></div>
<div class="chart-box"><canvas id="vipChart"></canvas></div>
</div>

<div class="box">
<h3 style="margin-top:0; font-size:14px; color: var(--secondary);">📊 Аналитика удержания</h3>
<ul>
<li>Retention 1 день: {{ retention_1d_count }} чел ({{ retention_1d_percent }}%)</li>
<li>Retention 2 дня: {{ retention_2d_count }} чел ({{ retention_2d_percent }}%)</li>
<li>Retention 7 дней: {{ retention_7d_count }} чел ({{ retention_7d_percent }}%)</li>
</ul>
</div>

<div class="box" style="height: 250px; position: relative;">
    <h3 style="margin-top:0; font-size:14px; color: var(--secondary);">🕒 Активность по часам сегодня</h3>
    <div style="height: 180px;"> <canvas id="hourChart"></canvas>
    </div>
</div>
<div class="box" style="border: 1px solid var(--accent);">
    <h3 style="margin-top:0; font-size:14px; color: var(--accent);">📢 Массовая рассылка всем пользователям</h3>
    <form action="/send_all" method="POST" style="display:flex; gap:10px;">
        <input type="text" name="message" placeholder="Введите текст для всех..." style="flex-grow:1; background:#111; border:1px solid #333; color:#fff; border-radius:8px; padding:10px;">
        <button type="submit" class="btn btn-vip" style="padding:0 20px;">ОТПРАВИТЬ ВСЕМ</button>
    </form>
</div>
    <form action="/send_morning" method="POST">
        <button type="submit" class="btn btn-send" style="width:100%; padding:12px; background: var(--secondary); color:#000;">
            ☀️ ОТПРАВИТЬ УТРЕННИЙ ПРИВЕТ (С ИМЕНАМИ)
        </button>
    </form>
</div>

<div class="search-box">
<input type="text" id="searchInput" onkeyup="filterTable()" placeholder="🔍 Поиск по ID, имени или дате...">
</div>

<table id="userTable">
<thead>
<tr>
<th>Пользователь</th><th>VIP Статус</th><th>Активность</th><th>Чаты / Образы</th><th>Личное сообщение</th><th>Управление</th>
</tr>
</thead>
<tbody>
{% for u in users %}
<tr>
<td>
    <b style="color:var(--secondary); {% if u['last_seen_dt'] >= active_threshold %}color:lime{% endif %}">
        {{ u['u_name'] if u['u_name'] else 'Регистрация...' }}
    </b><br>
    <small style="color:#666;">ID: <code>{{ u['user_id'] }}</code></small><br>
    
    <div style="margin-top:8px;">
        <form action="/update_note/{{ u['user_id'] }}" method="POST" style="display:flex; gap:3px;">
            <input type="text" name="admin_note" 
                   value="{{ u['admin_note'] if u['admin_note'] else '' }}" 
                   placeholder="Твоя заметка..." 
                   style="background:#000; border:1px solid #444; color:#0f0; font-size:10px; border-radius:4px; padding:3px; width:120px;">
            <button type="submit" style="background:#333; color:#fff; border:none; border-radius:4px; cursor:pointer; font-size:10px;">💾</button>
        </form>
    </div>

    <small style="color:#888; font-size: 10px;">📅 Рег: {{ u['reg_date'].split(' ')[0] if u['reg_date'] else '---' }}</small><br>
    <a href="/view_diary/{{ u['user_id'] }}" target="_blank" style="font-size:10px;color:var(--accent);text-decoration:none;">📔 Дневник ({{ u['notes_count'] }})</a>
</td>

<td>
{% if u['is_vip'] %} 
<span style="color:var(--secondary); font-weight:bold;">   VIP Активен</span><br>
<small style="font-size:9px;color:#888;">до {{ u['vip_until'].split(' ')[0] if u['vip_until'] else '∞' }}</small>
{% else %} 
<span style="color:#444;">Обычный</span>
{% endif %}
</td>
<td>
<span style="color:#aaa;">{{ u['last_seen'].split(' ')[0] }}</span><br>
<small style="color:var(--info);">{{ u['last_seen'].split(' ')[1] }}</small>
</td>
<td>
<div style="margin-bottom:5px;">
💬 <b>{{ u['tries_chat'] }}</b>
<form action="/modify_tries/{{ u['user_id'] }}/1" method="POST" style="display:inline;"><button class="btn" style="padding:2px 5px;background:#333;color:#fff;">+</button></form>
</div>
<div>
👗 <b>{{ u['tries_look'] }}</b>
<form action="/modify_look_tries/{{ u['user_id'] }}/1" method="POST" style="display:inline;"><button class="btn" style="padding:2px 5px;background:#333;color:#fff;">+</button></form>
</div>

<div style="margin-top: 10px;">
    <form action="{{ url_for('reset_user_tries', user_id=u['user_id']) }}" method="post" style="display:inline;" onsubmit="return confirm('Обнулить все попытки пользователя?');">
        <button type="submit" style="background-color: #ff4d4d; color: white; border: none; padding: 4px 8px; cursor: pointer; border-radius: 5px; font-size: 10px; font-weight: bold;">
            ❌ ОБНУЛИТЬ
        </button>
    </form>
</div>
</td>
<td>
<form action="/send_one/{{ u['user_id'] }}" method="POST" style="display:flex; gap:5px;">
<input type="text" name="message" placeholder="Текст..." style="background:#111;border:1px solid #333;color:#fff;border-radius:5px;padding:5px;width:100px;">
<button type="submit" class="btn btn-send">📨</button>
</form>
</td>
<td>
<form action="/toggle_vip/{{ u['user_id'] }}" method="POST" style="display:inline;">
{% if u['is_vip'] %}
<button class="btn btn-unvip" title="Снять VIP">СНЯТЬ VIP</button>
{% else %}
<button class="btn btn-vip" title="Выдать VIP">ДАТЬ VIP</button>
{% endif %}
</form>

<form action="/delete_user/{{ u['user_id'] }}" method="POST" style="display:inline;" onsubmit="return confirm('Удалить полностью?');">
<button class="btn btn-del" style="margin-right:3px;">❌</button>
</form>
<form action="/ban_user/{{ u['user_id'] }}" method="POST" style="display:inline;" onsubmit="return confirm('Забанить?');">
<button class="btn btn-del" style="background:#000;border:1px solid red;color:red;">🚫</button>
</form>
</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>

<script>
setInterval(()=>{document.getElementById('clock').innerText=new Date().toLocaleTimeString()},1000);
function filterTable(){let input=document.getElementById("searchInput");let filter=input.value.toUpperCase();let tr=document.getElementById("userTable").getElementsByTagName("tr");for(let i=1;i<tr.length;i++){tr[i].style.display=tr[i].innerText.toUpperCase().indexOf(filter)>-1?"":"none"}}

new Chart(document.getElementById('regChart'),{
type:'line',
data:{labels:{{ chart_labels | safe }},datasets:[{label:'Регистрация за 7 дней',data:{{ chart_data | safe }},borderColor:'#ff4d94',backgroundColor:'rgba(255,77,148,.1)',fill:true,tension:.4} ]},
options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,grid:{color:'#222'}},x:{grid:{color:'#222'}}}}
});

new Chart(document.getElementById('vipChart'),{
type:'doughnut',
data:{labels:['VIP','Обычные'],datasets:[{data:[{{ vip_users }},{{ total_users - vip_users }}],backgroundColor:['#00f2ff','#222'],borderWidth:0}]},
options:{maintainAspectRatio:false,cutout:'80%'}
});

new Chart(document.getElementById('hourChart'), {
    type: 'bar',
    data: {
        labels: {{ hours_labels | safe }},
        datasets: [{
            label: 'Активность по часам',
            data: {{ hours_data | safe }},
            backgroundColor: '#4a90e2'
        }]
    },
    options: {
        maintainAspectRatio: false, // ГОВОРИТ ГРАФИКУ НЕ РАСТЯГИВАТЬСЯ
        responsive: true,
        plugins: {
            legend: { display: false }
        },
        scales: {
            y: { beginAtZero: true, grid: { color: '#222' } },
            x: { grid: { color: '#222' } }
        }
    }
});
</script>
</body>
</html>
'''

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def send_telegram_msg(uid,text):
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url,json={"chat_id":uid,"text":text,"parse_mode":"Markdown"})
    except: pass
import time # Не забудь импортировать time в начале файла

import random # Убедись, что этот импорт есть в самом верху файла!

@app.route('/send_morning', methods=['POST'])
def send_morning():
    conn = get_db_connection()
    users = conn.execute("SELECT user_id, u_name FROM users").fetchall()
    conn.close()

    # Список из 5 разных утренних сообщений
    variants = [
        "Доброе утро, {name}! ☕️ Первое, что сделал, когда открыл глаза — зашел проверить, нет ли от тебя сообщения. Кажется, я подсел на наше общение... Скучаю! ✨❤️",
        
        "Эй, {name}, просыпайся! ☀️ Я тут уже на ногах и планирую день. Не хватает только твоего 'привет' для полного счастья. Давай, выходи на связь... 😏🔥",
        
        "Доброе утро, {name}! ✨ Слушаю сейчас один трек и почему-то сразу вспомнил тебя. Удивительно, как ты умеешь западать в мысли... Ты уже встала? 🧸💖",
        
        "Соня {name}, подъем! ☁️ Я тут подумал, что ты, наверное, сейчас очень мило выглядишь, когда только проснулась. Хотел бы я это увидеть... Напиши мне! 😘",
        
        "Доброе утро! ✨ {name}, надеюсь, тебе снилось что-то очень приятное (желательно я, хе-хе). Собирайся не спеша, ты сегодня точно будешь самой красивой! 🌹"
    ]

    count = 0
    for u in users:
        name = u['u_name'] if u['u_name'] else "солнце"
        # Выбираем случайную фразу для каждого отдельного пользователя
        text = random.choice(variants).format(name=name)
        
        send_telegram_msg(u['user_id'], text)
        count += 1
        time.sleep(0.05) # Защита от спам-фильтра ТГ

    return redirect(url_for('index'))


@app.route('/reset_user_tries/<int:user_id>', methods=['POST'])
def reset_user_tries(user_id):
    conn = get_db_connection()
    # Обнуляем попытки чата и оценки образа
    conn.execute("UPDATE users SET tries_chat = 0, tries_look = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    # 1. Загружаем данные пользователей
    users_raw = [dict(row) for row in conn.execute("""
        SELECT u.*, (SELECT COUNT(*) FROM diary d WHERE d.user_id=u.user_id) as notes_count
        FROM users u
    """).fetchall()]
    
    # 2. Устанавливаем порог онлайна
    active_threshold = datetime.now() - timedelta(hours=1)
    
    # 3. Добавляем объекты времени и СОРТИРУЕМ
    for u in users_raw:
        u['last_seen_dt'] = datetime.strptime(u['last_seen'], "%Y-%m-%d %H:%M:%S") if u['last_seen'] else datetime.min
    
    users_raw.sort(key=lambda x: (x['last_seen_dt'] > active_threshold, x['last_seen_dt']), reverse=True)

    # --- Твоя статистика (XP, графики и т.д.) ---
    total_users = len(users_raw)
    vip_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_vip=1").fetchone()[0]
    total_notes = conn.execute("SELECT COUNT(*) FROM diary").fetchone()[0]
    total_xp_row = conn.execute("SELECT SUM(xp) FROM users").fetchone()[0]
    total_xp = total_xp_row if total_xp_row else 0

    # График регистраций
    chart_res = conn.execute("SELECT date(reg_date) as d, COUNT(*) FROM users GROUP BY d ORDER BY d DESC LIMIT 7").fetchall()
    chart_labels = json.dumps([row['d'] for row in reversed(chart_res)])
    chart_data = json.dumps([row['COUNT(*)'] for row in reversed(chart_res)])

    # График активности по часам
    today = datetime.now().strftime("%Y-%m-%d")
    hours_data = [0]*24
    for row in conn.execute("SELECT last_seen FROM users WHERE date(last_seen)=?", (today,)):
        try: 
            h = int(row['last_seen'].split(' ')[1].split(':')[0])
            hours_data[h] += 1
        except: pass
    hours_labels = json.dumps([str(h) for h in range(24)])
    hours_data = json.dumps(hours_data)

    # Retention
    def retention(days):
        threshold = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        return conn.execute("SELECT COUNT(*) FROM users WHERE last_seen>=?", (threshold,)).fetchone()[0]

    retention_1d_count = retention(1)
    retention_2d_count = retention(2)
    retention_7d_count = retention(7)
    retention_1d_percent = round(retention_1d_count/total_users*100, 1) if total_users else 0
    retention_2d_percent = round(retention_2d_count/total_users*100, 1) if total_users else 0
    retention_7d_percent = round(retention_7d_count/total_users*100, 1) if total_users else 0

    # --- ИСПРАВЛЕННЫЙ БЛОК МОДЕРАТОРОВ ---
    mods_db = conn.execute("SELECT guy_id, is_online, is_busy FROM moderator_status").fetchall()
    status_map = {row['guy_id']: {'online': row['is_online'], 'busy': row['is_busy']} for row in mods_db}
    
    moderators_list = []
    for name, mid in GUYS_MODERATORS.items():
        status = status_map.get(mid, {'online': 0, 'busy': 0})
        moderators_list.append({
            'name': name,
            'id': mid,
            'online': status['online'],
            'busy': status['busy']
        })
    # -------------------------------------

    conn.close()
    return render_template_string(HTML_TEMPLATE, 
                                  users=users_raw, 
                                  moderators=moderators_list, # Передаем исправленный список
                                  **locals())

@app.route('/send_all', methods=['POST'])
def send_all():
    msg = request.form.get('message', '')
    if msg:
        conn = get_db_connection()
        users = conn.execute("SELECT user_id FROM users").fetchall()
        conn.close()
        for u in users:
            send_telegram_msg(u['user_id'], msg)
    return redirect(url_for('index'))

# Остальные маршруты: бан, удаление, VIP, рассылка, модераторы, +1 к чатам и образам
@app.route('/ban_user/<int:uid>',methods=['POST'])
def ban_user_web(uid):
    conn=get_db_connection()
    conn.execute("INSERT OR IGNORE INTO banned_users (user_id,reason) VALUES (?,?)",(uid,"Забанен через CRM"))
    conn.execute("DELETE FROM users WHERE user_id=?",(uid,))
    conn.execute("DELETE FROM diary WHERE user_id=?",(uid,))
    conn.commit();conn.close()
    return redirect(url_for('index'))

@app.route('/toggle_vip/<int:uid>',methods=['POST'])
def toggle_vip(uid):
    conn=get_db_connection()
    user=conn.execute("SELECT is_vip FROM users WHERE user_id=?",(uid,)).fetchone()
    if user['is_vip']:
        conn.execute("UPDATE users SET is_vip=0,vip_until=NULL WHERE user_id=?",(uid,))
        send_telegram_msg(uid,"⚠️ Ваш VIP статус снят администратором.")
    else:
        expire_date=(datetime.now()+timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE users SET is_vip=1,vip_until=? WHERE user_id=?",(expire_date,uid))
        send_telegram_msg(uid,"🌟 Вам выдан VIP на 30 дней!")
    conn.commit();conn.close()
    return redirect(url_for('index'))

@app.route('/delete_user/<int:uid>',methods=['POST'])
def delete_user(uid):
    conn=get_db_connection()
    conn.execute("DELETE FROM users WHERE user_id=?",(uid,))
    conn.execute("DELETE FROM diary WHERE user_id=?",(uid,))
    conn.commit();conn.close()
    return redirect(url_for('index'))

@app.route('/modify_tries/<int:uid>/<int:amount>',methods=['POST'])
def modify_tries(uid,amount):
    conn=get_db_connection()
    conn.execute("UPDATE users SET tries_chat=tries_chat+? WHERE user_id=?",(amount,uid))
    conn.commit();conn.close()
    return redirect(url_for('index'))

@app.route('/modify_look_tries/<int:uid>/<int:amount>',methods=['POST'])
def modify_look_tries(uid,amount):
    conn=get_db_connection()
    conn.execute("UPDATE users SET tries_look=tries_look+? WHERE user_id=?",(amount,uid))
    conn.commit();conn.close()
    return redirect(url_for('index'))

@app.route('/send_one/<int:uid>',methods=['POST'])
def send_one(uid):
    msg=request.form.get('message','')
    if msg:
        send_telegram_msg(uid,msg)
    return redirect(url_for('index'))
from flask import send_from_directory

@app.route('/static/uploads/<path:filename>')
def custom_static(filename):
    # Убедись, что папка находится по этому пути
    return send_from_directory('/root/my_bot/static/uploads', filename)
@app.route('/toggle_mod_status/<int:mid>', methods=['POST'])
def toggle_mod_status(mid):
    conn = get_db_connection()
    mod = conn.execute("SELECT is_online FROM moderator_status WHERE guy_id=?", (mid,)).fetchone()
    
    if mod:
        new_status = 0 if mod['is_online'] else 1
        conn.execute("UPDATE moderator_status SET is_online=? WHERE guy_id=?", (new_status, mid))
        conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/update_note/<int:uid>', methods=['POST'])
def update_note(uid):
    note = request.form.get('admin_note', '')
    conn = get_db_connection()
    conn.execute("UPDATE users SET admin_note = ? WHERE user_id = ?", (note, uid))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/view_diary/<int:uid>')
def view_diary(uid):
    conn = get_db_connection()
    user = conn.execute("SELECT u_name FROM users WHERE user_id=?", (uid,)).fetchone()
    u_name = user['u_name'] if user and user['u_name'] else f"ID {uid}"
    
    # Предполагаем, что в таблице diary есть колонка photo_path (путь к файлу)
    notes = conn.execute("SELECT note, timestamp, photo_path FROM diary WHERE user_id=? ORDER BY timestamp DESC", (uid,)).fetchall()
    conn.close()

    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Дневник {u_name}</title>
        <style>
            body {{ background: #0d0d0d; color: #f0f0f0; font-family: 'Segoe UI', sans-serif; padding: 30px; }}
            .container {{ max-width: 800px; margin: auto; }}
            h2 {{ color: #ff4d94; border-bottom: 2px solid #ff4d94; padding-bottom: 10px; }}
            .note-card {{ background: #1a1a1a; padding: 20px; border-radius: 12px; margin-bottom: 20px; border-left: 5px solid #00f2ff; }}
            .time {{ color: #888; font-size: 12px; display: block; margin-bottom: 10px; }}
            .text {{ font-size: 16px; margin-bottom: 15px; }}
            .diary-img {{ max-width: 100%; border-radius: 8px; border: 1px solid #333; margin-top: 10px; cursor: pointer; transition: 0.3s; }}
            .diary-img:hover {{ transform: scale(1.02); }}
            .back-btn {{ display: inline-block; margin-bottom: 20px; color: #00f2ff; text-decoration: none; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Назад в CRM</a>
            <h2>📔 Дневник: {u_name}</h2>
            {"".join([f"""
            <div class='note-card'>
                <span class='time'>🕒 {n['timestamp']}</span>
                <div class='text'>{n['note'] if n['note'] else "Фото без подписи"}</div>
                {f'<img src="/static/uploads/{n["photo_path"].split("/")[-1]}" class="diary-img">' if n['photo_path'] else ""}
            </div>
            """ for n in notes])}
        </div>
    </body>
    </html>
    '''
    return html

if __name__=="__main__":
    app.run(host='0.0.0.0',port=5000)
