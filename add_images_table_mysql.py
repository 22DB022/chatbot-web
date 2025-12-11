"""
MySQLに画像テーブルを追加するスクリプト
"""
import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

def add_images_table_mysql():
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'user': os.getenv('DB_USER', 'root'),
        'password': os.getenv('DB_PASSWORD', ''),
        'database': os.getenv('DB_NAME', 'study_chatbot_db'),
        'charset': 'utf8mb4'
    }
    
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
        
        # テーブルが既に存在するかチェック
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = %s AND table_name = 'pdf_images'
        """, (db_config['database'],))
        
        exists = cursor.fetchone()[0] > 0
        
        if exists:
            print("ℹ️ pdf_images テーブルは既に存在します")
        else:
            # テーブル作成
            cursor.execute("""
                CREATE TABLE pdf_images (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    page_number INT NOT NULL,
                    image_path VARCHAR(512) NOT NULL,
                    image_index INT NOT NULL,
                    width INT,
                    height INT,
                    added_date DATETIME NOT NULL,
                    INDEX idx_filename_page (filename, page_number)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            conn.commit()
            print("✅ pdf_images テーブルを作成しました")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ エラー: {e}")

if __name__ == '__main__':
    add_images_table_mysql()