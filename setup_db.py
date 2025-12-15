# setup_mysql.py
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

print("🔧 MySQLテーブルを作成中...")

# pdf_metadataテーブル
cursor.execute("""
    CREATE TABLE IF NOT EXISTS pdf_metadata (
        id INT AUTO_INCREMENT PRIMARY KEY,
        filename VARCHAR(255) NOT NULL UNIQUE,
        page_count INT NOT NULL,
        total_chars INT NOT NULL,
        total_chunks INT NOT NULL,
        added_date DATETIME NOT NULL,
        INDEX idx_filename (filename)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""")
print("✅ pdf_metadata テーブル作成")

# pdf_contentsテーブル
cursor.execute("""
    CREATE TABLE IF NOT EXISTS pdf_contents (
        id INT AUTO_INCREMENT PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        page_number INT NOT NULL,
        chunk_text TEXT NOT NULL,
        embedding LONGTEXT NOT NULL,
        added_date DATETIME NOT NULL,
        INDEX idx_filename (filename),
        INDEX idx_page (page_number),
        FOREIGN KEY (filename) REFERENCES pdf_metadata(filename) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""")
print("✅ pdf_contents テーブル作成")

# pdf_imagesテーブル
cursor.execute("""
    CREATE TABLE IF NOT EXISTS pdf_images (
        id INT AUTO_INCREMENT PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        page_number INT NOT NULL,
        image_path VARCHAR(500) NOT NULL,
        image_index INT NOT NULL,
        width INT,
        height INT,
        added_date DATETIME NOT NULL,
        FOREIGN KEY (filename) REFERENCES pdf_metadata(filename) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""")
print("✅ pdf_images テーブル作成")

conn.commit()
cursor.close()
conn.close()

print("✅ MySQLデータベースセットアップ完了!")