import pymysql
from dotenv import load_dotenv
import os

load_dotenv()

# MySQL接続
conn = pymysql.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    user=os.getenv('DB_USER', 'root'),
    password=os.getenv('DB_PASSWORD', ''),
    database=os.getenv('DB_NAME'),
    charset='utf8mb4'
)

cursor = conn.cursor()

print("🔍 データベースの文字セット設定を確認中...\n")

# データベースの文字セット
cursor.execute("SHOW VARIABLES LIKE 'character_set%'")
results = cursor.fetchall()
print("【文字セット設定】")
for row in results:
    print(f"  {row[0]}: {row[1]}")

print("\n【照合順序設定】")
cursor.execute("SHOW VARIABLES LIKE 'collation%'")
results = cursor.fetchall()
for row in results:
    print(f"  {row[0]}: {row[1]}")

# テーブルの文字セット
db_name = os.getenv('DB_NAME')
print(f"\n【{db_name} テーブルの文字セット】")
cursor.execute(f"""
    SELECT 
        TABLE_NAME,
        TABLE_COLLATION
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = '{db_name}'
""")
results = cursor.fetchall()
for row in results:
    print(f"  {row[0]}: {row[1]}")

cursor.close()
conn.close()

print("\n✅ 確認完了")