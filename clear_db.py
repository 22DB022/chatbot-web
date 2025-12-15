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

print("🗑️ MySQLデータベースをクリア中...")

# 外部キー制約を一時的に無効化
cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

# 全てのデータを削除
cursor.execute("DELETE FROM pdf_contents")
print("✅ pdf_contents テーブルをクリア")

cursor.execute("DELETE FROM pdf_metadata")
print("✅ pdf_metadata テーブルをクリア")

try:
    cursor.execute("DELETE FROM pdf_images")
    print("✅ pdf_images テーブルをクリア")
except:
    pass

# 外部キー制約を再度有効化
cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

conn.commit()
cursor.close()
conn.close()

print("✅ MySQLデータベースをクリアしました")