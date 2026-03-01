import sqlite3

def check_my_database():
    try:
        conn = sqlite3.connect('mark_empire_final.db')
        cursor = conn.cursor()
        
        # Получаем структуру таблицы users
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        
        print("📊 ТЕКУЩАЯ СТРУКТУРА ТАБЛИЦЫ USERS:")
        print("-" * 50)
        print(f"{'Index':<7} | {'Column Name':<20} | {'Type'}")
        print("-" * 50)
        
        for col in columns:
            # col[0] - индекс, col[1] - имя, col[2] - тип
            print(f"{col[0]:<7} | {col[1]:<20} | {col[2]}")
            
        print("-" * 50)
        
        # Проверка на наличие данных
        cursor.execute("SELECT * FROM users LIMIT 1")
        row = cursor.fetchone()
        if row:
            print(f"✅ В базе есть пользователи. Всего колонок: {len(row)}")
        else:
            print("⚠️ База пуста, но структура создана.")
            
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка при проверке базы: {e}")

if __name__ == "__main__":
    check_my_database()