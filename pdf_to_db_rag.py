"""
PDFをRAGデータベースに登録するスクリプト
"""

import os
import json
import sqlite3
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
import pdfplumber

# PyMySQL（MySQL使う場合）
try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

load_dotenv()


class PDFToRAG:
    """PDFをRAGデータベースに登録"""
    
    def __init__(self, use_mysql=False):
        # OpenAI API初期化
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise Exception("OPENAI_API_KEYが設定されていません")
        
        self.client = OpenAI(api_key=api_key)
        self.use_mysql = use_mysql
        
        # データベース設定
        if use_mysql:
            if not MYSQL_AVAILABLE:
                raise Exception("pymysqlをインストールしてください: pip install pymysql")
            self.db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'user': os.getenv('DB_USER', 'root'),
                'password': os.getenv('DB_PASSWORD', ''),
                'database': os.getenv('DB_NAME', 'study_chatbot_db'),
                'charset': 'utf8mb4'
            }
            print("✅ MySQL使用")
        else:
            self.db_path = "rag_study_data.db"
            print(f"✅ SQLite使用: {self.db_path}")
        
        self.init_database()
    
    def get_connection(self):
        """DB接続"""
        if self.use_mysql:
            return pymysql.connect(**self.db_config)
        else:
            return sqlite3.connect(self.db_path)
    
    def init_database(self):
        """データベースとテーブルを初期化"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            if self.use_mysql:
                # MySQL用テーブル作成
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pdf_metadata (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        filename VARCHAR(500) NOT NULL,
                        page_count INT,
                        total_chars INT,
                        total_chunks INT,
                        added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_filename (filename)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pdf_contents (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        filename VARCHAR(500) NOT NULL,
                        page_number INT,
                        chunk_text TEXT NOT NULL,
                        embedding JSON NOT NULL,
                        added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_filename (filename),
                        INDEX idx_page (page_number)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
            else:
                # SQLite用テーブル作成
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pdf_metadata (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT NOT NULL UNIQUE,
                        page_count INTEGER,
                        total_chars INTEGER,
                        total_chunks INTEGER,
                        added_date TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pdf_contents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT NOT NULL,
                        page_number INTEGER,
                        chunk_text TEXT NOT NULL,
                        embedding TEXT NOT NULL,
                        added_date TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # SQLiteのインデックス
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_filename 
                    ON pdf_contents(filename)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_page 
                    ON pdf_contents(page_number)
                """)
            
            conn.commit()
            print("✅ データベーステーブル初期化完了")
            
        finally:
            cursor.close()
            conn.close()
    
    def extract_text_from_pdf(self, pdf_path):
        """PDFからテキスト抽出（ページごと）"""
        print(f"📄 PDFを読み込み中: {pdf_path}")
        
        pages_text = []
        total_chars = 0
        
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    text = text.strip()
                    pages_text.append({
                        'page': i,
                        'text': text
                    })
                    total_chars += len(text)
                    print(f"  ページ {i}/{len(pdf.pages)} 抽出完了 ({len(text)}文字)")
        
        print(f"✅ 全{len(pages_text)}ページ、合計{total_chars}文字を抽出")
        return pages_text, total_chars
    
    def chunk_text(self, text, max_chunk_size=1000, overlap=200):
        """テキストをチャンクに分割（オーバーラップあり）"""
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + max_chunk_size
            chunk = text[start:end]
            
            # 文の途中で切れないように調整
            if end < len(text):
                last_period = chunk.rfind('。')
                last_newline = chunk.rfind('\n')
                last_space = chunk.rfind(' ')
                
                split_point = max(last_period, last_newline, last_space)
                if split_point > max_chunk_size * 0.5:  # 半分以上進んでいれば区切る
                    chunk = chunk[:split_point + 1]
                    end = start + split_point + 1
            
            if chunk.strip():
                chunks.append(chunk.strip())
            
            start = end - overlap  # オーバーラップ
        
        return chunks
    
    def create_embedding(self, text):
        """テキストをベクトル化"""
        response = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    
    def add_pdf_to_database(self, pdf_path):
        """PDFをデータベースに追加"""
        filename = os.path.basename(pdf_path)
        
        # 1. PDFからテキスト抽出
        pages_text, total_chars = self.extract_text_from_pdf(pdf_path)
        
        if not pages_text:
            print("❌ テキストが抽出できませんでした")
            return
        
        # 2. 既存データをチェック
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            if self.use_mysql:
                cursor.execute(
                    "SELECT COUNT(*) FROM pdf_metadata WHERE filename = %s",
                    (filename,)
                )
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM pdf_metadata WHERE filename = ?",
                    (filename,)
                )
            
            if cursor.fetchone()[0] > 0:
                print(f"⚠️  {filename} は既に登録されています")
                
                response = input("上書きしますか？ (y/n): ")
                if response.lower() != 'y':
                    print("キャンセルしました")
                    return
                
                # 既存データを削除
                if self.use_mysql:
                    cursor.execute("DELETE FROM pdf_metadata WHERE filename = %s", (filename,))
                    cursor.execute("DELETE FROM pdf_contents WHERE filename = %s", (filename,))
                else:
                    cursor.execute("DELETE FROM pdf_metadata WHERE filename = ?", (filename,))
                    cursor.execute("DELETE FROM pdf_contents WHERE filename = ?", (filename,))
                
                conn.commit()
                print("✅ 既存データを削除しました")
        
        finally:
            cursor.close()
            conn.close()
        
        # 3. ページごとにチャンク化してベクトル化
        all_chunks = []
        
        for page_data in pages_text:
            page_num = page_data['page']
            page_text = page_data['text']
            
            chunks = self.chunk_text(page_text)
            
            print(f"📝 ページ {page_num}: {len(chunks)}チャンクを処理中...")
            
            for chunk in chunks:
                # ベクトル化
                embedding = self.create_embedding(chunk)
                
                all_chunks.append({
                    'page': page_num,
                    'text': chunk,
                    'embedding': embedding
                })
        
        print(f"✅ 全{len(all_chunks)}チャンクのベクトル化完了")
        
        # 4. データベースに保存
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # メタデータ登録
            if self.use_mysql:
                cursor.execute("""
                    INSERT INTO pdf_metadata 
                    (filename, page_count, total_chars, total_chunks, added_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    filename,
                    len(pages_text),
                    total_chars,
                    len(all_chunks),
                    datetime.now()
                ))
            else:
                cursor.execute("""
                    INSERT INTO pdf_metadata 
                    (filename, page_count, total_chars, total_chunks, added_date)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    filename,
                    len(pages_text),
                    total_chars,
                    len(all_chunks),
                    datetime.now().isoformat()
                ))
            
            # チャンクデータ登録
            for chunk in all_chunks:
                embedding_json = json.dumps(chunk['embedding'])
                
                if self.use_mysql:
                    cursor.execute("""
                        INSERT INTO pdf_contents 
                        (filename, page_number, chunk_text, embedding, added_date)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        filename,
                        chunk['page'],
                        chunk['text'],
                        embedding_json,
                        datetime.now()
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO pdf_contents 
                        (filename, page_number, chunk_text, embedding, added_date)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        filename,
                        chunk['page'],
                        chunk['text'],
                        embedding_json,
                        datetime.now().isoformat()
                    ))
            
            conn.commit()
            print(f"✅ データベース登録完了: {filename}")
            print(f"   - ページ数: {len(pages_text)}")
            print(f"   - 総文字数: {total_chars}")
            print(f"   - チャンク数: {len(all_chunks)}")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ データベース登録エラー: {e}")
            raise
        
        finally:
            cursor.close()
            conn.close()
    
    def list_registered_pdfs(self):
        """登録済みPDF一覧"""
        conn = self.get_connection()
        
        try:
            if self.use_mysql:
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute("""
                    SELECT filename, page_count, total_chars, total_chunks, added_date
                    FROM pdf_metadata
                    ORDER BY added_date DESC
                """)
            else:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT filename, page_count, total_chars, total_chunks, added_date
                    FROM pdf_metadata
                    ORDER BY added_date DESC
                """)
            
            results = cursor.fetchall()
            cursor.close()
            
            if not results:
                print("\n📚 登録済みPDFはありません")
                return
            
            print(f"\n📚 登録済みPDF ({len(results)}件):")
            print("-" * 80)
            
            for i, row in enumerate(results, 1):
                print(f"{i}. {row['filename']}")
                print(f"   ページ数: {row['page_count']} | "
                      f"総文字数: {row['total_chars']} | "
                      f"チャンク数: {row['total_chunks']}")
                print(f"   登録日時: {row['added_date']}")
                print()
            
        finally:
            conn.close()


def main():
    """メイン処理"""
    print("=" * 80)
    print("📚 PDF → RAGデータベース登録ツール")
    print("=" * 80)
    print()
    
    # MySQL使うか確認
    use_mysql = False
    if MYSQL_AVAILABLE and os.getenv('DB_NAME'):
        use_mysql_input = input("MySQLを使用しますか？ (y/n, デフォルト: n): ").strip().lower()
        use_mysql = use_mysql_input == 'y'
    
    try:
        rag = PDFToRAG(use_mysql=use_mysql)
        
        while True:
            print("\n" + "=" * 80)
            print("メニュー:")
            print("  1. PDFを追加")
            print("  2. 登録済みPDF一覧")
            print("  3. 終了")
            print("=" * 80)
            
            choice = input("選択してください (1-3): ").strip()
            
            if choice == '1':
                pdf_path = input("\nPDFファイルのパスを入力してください: ").strip()
                
                # パスのクォーテーションを削除
                pdf_path = pdf_path.strip('"').strip("'")
                
                if not os.path.exists(pdf_path):
                    print(f"❌ ファイルが見つかりません: {pdf_path}")
                    continue
                
                if not pdf_path.lower().endswith('.pdf'):
                    print("❌ PDFファイルを指定してください")
                    continue
                
                print()
                rag.add_pdf_to_database(pdf_path)
                
            elif choice == '2':
                rag.list_registered_pdfs()
                
            elif choice == '3':
                print("\n👋 終了します")
                break
            
            else:
                print("❌ 無効な選択です")
    
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()