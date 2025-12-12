"""
ローカルMySQL → Supabase PostgreSQL データ移行スクリプト
"""
import pymysql
import psycopg2
import json
from datetime import datetime

# ============================================
# 設定
# ============================================

# ローカルMySQL設定
MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',  # XAMPPのデフォルトは空
    'database': 'study_chatbot_db',
    'charset': 'utf8mb4'
}

# Supabase PostgreSQL設定
POSTGRES_URL = "postgresql://postgres.otoflircaaqnngeizqxr:A673H7z5y@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres"

# ============================================
# 移行関数
# ============================================

def connect_mysql():
    """MySQL接続"""
    print("🔌 MySQL接続中...")
    return pymysql.connect(**MYSQL_CONFIG)

def connect_postgres():
    """PostgreSQL接続"""
    print("🔌 PostgreSQL接続中...")
    return psycopg2.connect(POSTGRES_URL)

def migrate_pdf_metadata():
    """pdf_metadataテーブルを移行"""
    print("\n📦 pdf_metadata テーブル移行開始")
    
    mysql_conn = connect_mysql()
    postgres_conn = connect_postgres()
    
    try:
        # MySQLからデータ取得
        mysql_cursor = mysql_conn.cursor(pymysql.cursors.DictCursor)
        mysql_cursor.execute("SELECT * FROM pdf_metadata")
        rows = mysql_cursor.fetchall()
        
        print(f"  📊 {len(rows)}件のデータを取得")
        
        if len(rows) == 0:
            print("  ⚠️ データがありません")
            return
        
        # PostgreSQLに挿入
        postgres_cursor = postgres_conn.cursor()
        
        # 既存データを削除
        postgres_cursor.execute("DELETE FROM pdf_metadata")
        postgres_conn.commit()
        print("  🗑️ 既存データを削除")
        
        # データ挿入
        for row in rows:
            postgres_cursor.execute("""
                INSERT INTO pdf_metadata 
                (filename, page_count, total_chars, total_chunks, added_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                row['filename'],
                row['page_count'],
                row['total_chars'],
                row['total_chunks'],
                row['added_date']
            ))
        
        postgres_conn.commit()
        print(f"  ✅ {len(rows)}件を移行完了")
        
    finally:
        mysql_cursor.close()
        postgres_cursor.close()
        mysql_conn.close()
        postgres_conn.close()

def migrate_pdf_contents():
    """pdf_contentsテーブルを移行（大量データ対応）"""
    print("\n📦 pdf_contents テーブル移行開始")
    
    mysql_conn = connect_mysql()
    postgres_conn = connect_postgres()
    
    try:
        # MySQLからデータ数を確認
        mysql_cursor = mysql_conn.cursor()
        mysql_cursor.execute("SELECT COUNT(*) FROM pdf_contents")
        total_count = mysql_cursor.fetchone()[0]
        
        print(f"  📊 {total_count}件のデータを移行します")
        
        if total_count == 0:
            print("  ⚠️ データがありません")
            return
        
        # PostgreSQLに挿入
        postgres_cursor = postgres_conn.cursor()
        
        # 既存データを削除
        postgres_cursor.execute("DELETE FROM pdf_contents")
        postgres_conn.commit()
        print("  🗑️ 既存データを削除")
        
        # バッチ処理（100件ずつ）
        batch_size = 100
        offset = 0
        inserted = 0
        
        while offset < total_count:
            # MySQLからバッチ取得
            mysql_cursor = mysql_conn.cursor(pymysql.cursors.DictCursor)
            mysql_cursor.execute(f"""
                SELECT * FROM pdf_contents 
                LIMIT {batch_size} OFFSET {offset}
            """)
            rows = mysql_cursor.fetchall()
            
            if not rows:
                break
            
            # PostgreSQLに挿入
            for row in rows:
                postgres_cursor.execute("""
                    INSERT INTO pdf_contents 
                    (filename, page_number, chunk_text, embedding, added_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    row['filename'],
                    row['page_number'],
                    row['chunk_text'],
                    row['embedding'],
                    row['added_date']
                ))
                inserted += 1
            
            postgres_conn.commit()
            
            # 進捗表示
            progress = (offset + len(rows)) / total_count * 100
            print(f"  ⏳ 進捗: {inserted}/{total_count} ({progress:.1f}%)")
            
            offset += batch_size
        
        print(f"  ✅ {inserted}件を移行完了")
        
    finally:
        mysql_cursor.close()
        postgres_cursor.close()
        mysql_conn.close()
        postgres_conn.close()

def migrate_pdf_images():
    """pdf_imagesテーブルを移行"""
    print("\n📦 pdf_images テーブル移行開始")
    
    mysql_conn = connect_mysql()
    postgres_conn = connect_postgres()
    
    try:
        # MySQLからデータ取得
        mysql_cursor = mysql_conn.cursor(pymysql.cursors.DictCursor)
        mysql_cursor.execute("SELECT * FROM pdf_images")
        rows = mysql_cursor.fetchall()
        
        print(f"  📊 {len(rows)}件のデータを取得")
        
        if len(rows) == 0:
            print("  ⚠️ データがありません")
            return
        
        # PostgreSQLに挿入
        postgres_cursor = postgres_conn.cursor()
        
        # 既存データを削除
        postgres_cursor.execute("DELETE FROM pdf_images")
        postgres_conn.commit()
        print("  🗑️ 既存データを削除")
        
        # データ挿入
        for row in rows:
            postgres_cursor.execute("""
                INSERT INTO pdf_images 
                (filename, page_number, image_path, image_index, width, height, added_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                row['filename'],
                row['page_number'],
                row['image_path'],
                row['image_index'],
                row['width'],
                row['height'],
                row['added_date']
            ))
        
        postgres_conn.commit()
        print(f"  ✅ {len(rows)}件を移行完了")
        
    finally:
        mysql_cursor.close()
        postgres_cursor.close()
        mysql_conn.close()
        postgres_conn.close()

def verify_migration():
    """移行結果を確認"""
    print("\n🔍 移行結果の確認")
    
    mysql_conn = connect_mysql()
    postgres_conn = connect_postgres()
    
    try:
        mysql_cursor = mysql_conn.cursor()
        postgres_cursor = postgres_conn.cursor()
        
        tables = ['pdf_metadata', 'pdf_contents', 'pdf_images']
        
        for table in tables:
            # MySQL
            mysql_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            mysql_count = mysql_cursor.fetchone()[0]
            
            # PostgreSQL
            postgres_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            postgres_count = postgres_cursor.fetchone()[0]
            
            status = "✅" if mysql_count == postgres_count else "❌"
            print(f"  {status} {table}: MySQL={mysql_count}, PostgreSQL={postgres_count}")
        
    finally:
        mysql_cursor.close()
        postgres_cursor.close()
        mysql_conn.close()
        postgres_conn.close()

# ============================================
# メイン処理
# ============================================

def main():
    """メイン処理"""
    print("=" * 60)
    print("🚀 データベース移行開始")
    print("  MySQL → Supabase PostgreSQL")
    print("=" * 60)
    
    try:
        # 接続テスト
        print("\n🔌 接続テスト中...")
        mysql_conn = connect_mysql()
        mysql_conn.close()
        print("  ✅ MySQL接続成功")
        
        postgres_conn = connect_postgres()
        postgres_conn.close()
        print("  ✅ PostgreSQL接続成功")
        
        # 確認
        print("\n⚠️ 警告: Supabaseの既存データは削除されます")
        response = input("続行しますか？ (yes/no): ")
        
        if response.lower() != 'yes':
            print("❌ 中止しました")
            return
        
        # 移行実行
        migrate_pdf_metadata()
        migrate_pdf_contents()
        migrate_pdf_images()
        
        # 確認
        verify_migration()
        
        print("\n" + "=" * 60)
        print("🎉 移行完了！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()