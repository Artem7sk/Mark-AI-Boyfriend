import sqlite3

db_name = "mark_empire_final.db"

def fix():
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        # Список колонок, которых может не хватать
        columns_to_add = [
            ("u_age", "INTEGER DEFAULT 0"),
            ("prompt_style", "TEXT DEFAULT 'Романтик'"),
            ("bot_hobby", "TEXT DEFAULT 'Забота о тебе'")
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                print(f"✅ Колонка {col_name} добавлена.")
            except sqlite3.OperationalError:
                print(f"⚠️ Колонка {col_name} уже существует, пропускаю.")
        
        conn.commit()
        conn.close()
        print("\n🚀 База данных полностью готова к работе!")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    fix()