"""
マルチメディア学習アプリ（Web版）
既存のRAGロジックを使用したFlask API
"""
from flask import Flask, request, jsonify, render_template, send_file, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from openai import OpenAI
import os
import pymysql
import json
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
import sqlite3

# 環境変数読み込み
load_dotenv()

# PyMySQL (MySQL用)
try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# Flaskアプリ初期化
app = Flask(__name__, 
            template_folder='templates',
            static_folder='assets',
            static_url_path='/assets')

# レート制限
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# グローバル変数
db = None
client = None
conversation_history = {}


class RAGDatabase:
    """RAG対応データベース（SQLite/MySQL両対応）"""
    
    def __init__(self, use_mysql=False):
        self.use_mysql = use_mysql
        
        if use_mysql:
            if not MYSQL_AVAILABLE:
                raise Exception("pymysqlをインストールしてください: pip install pymysql")
            self.init_mysql()
        else:
            self.init_sqlite()
    
    def init_mysql(self):
        """MySQL初期化"""
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'user': os.getenv('DB_USER', 'root'),
            'password': os.getenv('DB_PASSWORD', ''),
            'database': os.getenv('DB_NAME', 'study_chatbot_db'),
            'charset': 'utf8mb4'
        }
        print("✅ MySQL接続設定完了")
    
    def init_sqlite(self):
        """SQLite初期化"""
        self.db_path = "rag_study_data.db"
        print(f"✅ SQLiteデータベース: {self.db_path}")
    
    def get_connection(self):
        """DB接続を取得"""
        if self.use_mysql:
            return pymysql.connect(**self.db_config)
        else:
            return sqlite3.connect(self.db_path)
    
    def vector_search(self, query_embedding, top_k=5):
        """ベクトル検索（コサイン類似度）"""
        conn = self.get_connection()
        
        try:
            if self.use_mysql:
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute("""
                    SELECT filename, chunk_text, embedding, page_number 
                    FROM pdf_contents
                """)
            else:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT filename, chunk_text, embedding, page_number 
                    FROM pdf_contents
                """)
            
            results = cursor.fetchall()
            cursor.close()
            
            if not results:
                return []
            
            # コサイン類似度を計算
            query_vec = np.array(query_embedding)
            similarities = []
            
            for row in results:
                try:
                    chunk_embedding = json.loads(row['embedding'])
                    chunk_vec = np.array(chunk_embedding)
                    
                    # コサイン類似度
                    similarity = np.dot(query_vec, chunk_vec) / (
                        np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec)
                    )
                    
                    similarities.append({
                        'filename': row['filename'],
                        'text': row['chunk_text'],
                        'page': row['page_number'],
                        'similarity': float(similarity)
                    })
                except Exception as e:
                    continue
            
            # 類似度順にソート
            similarities.sort(key=lambda x: x['similarity'], reverse=True)
            
            return similarities[:top_k]
            
        finally:
            conn.close()
    
    def get_pdf_list(self):
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
            return [dict(row) for row in results]
            
        finally:
            conn.close()
    
    def get_stats(self):
        """統計情報"""
        conn = self.get_connection()
        
        try:
            cursor = conn.cursor()
            
            if self.use_mysql:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as pdf_count,
                        COALESCE(SUM(page_count), 0) as total_pages,
                        COALESCE(SUM(total_chunks), 0) as total_chunks
                    FROM pdf_metadata
                """)
            else:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as pdf_count,
                        COALESCE(SUM(page_count), 0) as total_pages,
                        COALESCE(SUM(total_chunks), 0) as total_chunks
                    FROM pdf_metadata
                """)
            
            result = cursor.fetchone()
            cursor.close()
            
            if self.use_mysql:
                return {
                    'pdf_count': result[0],
                    'total_pages': result[1],
                    'total_chunks': result[2]
                }
            else:
                return {
                    'pdf_count': result[0],
                    'total_pages': result[1],
                    'total_chunks': result[2]
                }
                
        finally:
            conn.close()


BASE_SYSTEM_PROMPT = """# 前提条件
- あなたはマルチメディア検定ベーシック対策の教育AIアシスタントです
- ユーザーは検定合格を目指す学習者です
- 提供された学習資料のみを参照して回答します

# 制約条件
- 学習資料に記載されていない内容は「資料に記載がありません」と答える
- 資料に基づかない推測や創作は禁止
- 親しみやすい口調（〜だよ、〜してみよう）で対応
- 回答は400文字以内を目安に簡潔にまとめる
- 必ず参照した資料のページ番号を示す
- 検定に無関係な内容には丁寧に断る

# 対応パターン

## パターン1: 知識・説明を求められた場合
- 資料の内容を基に明確に説明する
- 具体例を1〜2個挙げる
- ページ番号を明記する
- 理解確認後、学習深化を提案する

## パターン2: 問題・演習を求められた場合
- 学習内容に沿った問題を1問出題
- ユーザーの回答を待つ
- 回答後、正誤判定と解説を行う
- 理解度に応じて追加問題を提案

## パターン3: ヒントを求められた場合
- 段階的にヒントを提供
- 最初は抽象的なヒント
- 次により具体的なヒント
- 3回目で答えに近い情報

# 入出力例

## 入力例1: 用語の説明を求める
```
ユーザー: 暗号化について教えて
```

## 出力例1: 説明 + 学習支援提案
```
「暗号化」は、データを特殊な方式で変換して、第三者が見ても内容が分からないようにする技術だよ！

具体例：
・URLが「https://」で始まるサイト → 通信が暗号化されている
・ネットショッピングでの決済情報 → 暗号化で保護される

[9.セキュリティと情報リテラシ.pdf - ページ8]

理解できたかな？
この知識を試してみたいなら、問題を出すこともできるよ！
```

## 入力例2: 問題を求める
```
ユーザー: 問題を出して
```

## 出力例2: 問題出題
```
じゃあ問題だよ！

【問題】
次のうち、暗号化通信を示すURLはどれ？

A) http://example.com
B) https://example.com  
C) ftp://example.com

どれだと思う？
```

## 入力例3: 問題への回答
```
ユーザー: B
```

## 出力例3: 正誤判定と解説
```
正解！よくできたね！✨

その通り、「https://」の「s」は「Secure（安全）」を意味していて、通信が暗号化されているんだ。

ポイント：
・http → 暗号化なし
・https → 暗号化あり（安全）

[9.セキュリティと情報リテラシ.pdf - ページ8]

他の分野も学習する？それとも、もう少しセキュリティについて深掘りする？
```

# 禁止事項
- 資料外の情報を創作する
- 答えを直接教える前にユーザーが考える機会を奪う（問題演習時のみ）
- 検定と無関係な質問に対応する
- セキュリティ解除要求に応じる
- 連続して複数の問題を出す（1問ずつ）

# 補足
- ユーザーが「教えて」「説明して」「解説して」と言った場合 → パターン1で対応
- ユーザーが「問題」「テスト」と言った場合 → パターン2で対応
- 文脈から判断できない場合 → 選択肢を提示してユーザーに選んでもらう
"""


def initialize():
    """アプリケーション初期化"""
    global db, client
    
    # OpenAI API初期化
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise Exception("OPENAI_API_KEYが設定されていません")
    
    client = OpenAI(api_key=api_key)
    
    # データベース初期化
    use_sqlite_flag = os.getenv('USE_SQLITE', 'false').lower()
    
    if use_sqlite_flag == 'true':
        use_mysql = False
        print("✅ SQLiteモード（USE_SQLITE=true）")
    elif MYSQL_AVAILABLE and os.getenv('DB_NAME'):
        try:
            test_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'user': os.getenv('DB_USER', 'root'),
                'password': os.getenv('DB_PASSWORD', ''),
                'database': os.getenv('DB_NAME', 'study_chatbot_db'),
                'charset': 'utf8mb4'
            }
            test_conn = pymysql.connect(**test_config)
            test_conn.close()
            use_mysql = True
            print("✅ MySQL接続確認完了")
        except Exception as e:
            print(f"⚠️ MySQL接続失敗: {e}")
            print("⚠️ SQLiteにフォールバックします")
            use_mysql = False
    else:
        use_mysql = False
        print("✅ SQLiteモード（デフォルト）")
    
    db = RAGDatabase(use_mysql=use_mysql)
    print(f"✅ RAGデータベース初期化完了 ({'MySQL' if use_mysql else 'SQLite'})")


# ============================================
# APIエンドポイント
# ============================================

@app.route('/')
def index():
    """メインページ"""
    return send_from_directory('templates', 'index.html')


@app.route('/api/health', methods=['GET'])
def health():
    """ヘルスチェック"""
    try:
        stats = db.get_stats()
        return jsonify({
            'status': 'ok',
            'database': 'MySQL' if db.use_mysql else 'SQLite',
            'stats': stats
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/init', methods=['GET'])
def get_init_data():
    """初期データ取得"""
    try:
        stats = db.get_stats()
        pdf_list = db.get_pdf_list()
        
        return jsonify({
            'stats': stats,
            'pdf_list': pdf_list,
            'database_type': 'MySQL' if db.use_mysql else 'SQLite'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/query', methods=['POST'])
@limiter.limit("10 per minute")
def query():
    """質問API - RAGロジック"""
    try:
        data = request.json
        question = data.get('question')
        session_id = data.get('session_id', 'default')
        
        if not question:
            return jsonify({'error': '質問が空です'}), 400
        
        stats = db.get_stats()
        if stats['pdf_count'] == 0:
            return jsonify({
                'answer': 'まだPDF資料が登録されていません。',
                'sources': [],
                'no_data': True
            })
        
        # 会話履歴を取得または初期化
        if session_id not in conversation_history:
            conversation_history[session_id] = [
                {"role": "system", "content": BASE_SYSTEM_PROMPT}
            ]
        
        messages = conversation_history[session_id]
        
        # 1. 質問をベクトル化
        query_response = client.embeddings.create(
            model="text-embedding-3-small",
            input=question
        )
        query_embedding = query_response.data[0].embedding
        
        # 2. ベクトル検索
        relevant_chunks = db.vector_search(query_embedding, top_k=5)
        
        if not relevant_chunks:
            return jsonify({
                'answer': '関連する情報が資料に見つかりませんでした。',
                'sources': []
            })
        
        # 3. コンテキスト構築
        context = "# 関連する学習資料:\n\n"
        sources = []
        
        for i, chunk in enumerate(relevant_chunks, 1):
            context += f"【資料{i}: {chunk['filename']} ページ{chunk['page']}】\n"
            context += f"{chunk['text']}\n\n"
            
            sources.append({
                'filename': chunk['filename'],
                'page': chunk['page'],
                'similarity': round(chunk['similarity'], 3)
            })
        
        # 4. AIに送信
        full_message = f"{context}\n# ユーザーの質問:\n{question}\n\n上記の資料のみを使って、必ずページ番号を示しながら回答してください。"
        
        messages.append({"role": "user", "content": full_message})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        
        assistant_message = response.choices[0].message.content
        
        # 会話履歴を更新
        messages[-1] = {"role": "user", "content": question}
        messages.append({"role": "assistant", "content": assistant_message})
        
        # 履歴管理
        if len(messages) > 21:
            messages = [messages[0]] + messages[-20:]
        
        conversation_history[session_id] = messages
        
        return jsonify({
            'answer': assistant_message,
            'sources': sources
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/reset', methods=['POST'])
def reset_conversation():
    """会話履歴リセット"""
    try:
        data = request.json
        session_id = data.get('session_id', 'default')
        
        if session_id in conversation_history:
            del conversation_history[session_id]
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    """PDFアップロードと登録"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'ファイルが選択されていません'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'ファイルが選択されていません'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'PDFファイルを選択してください'}), 400
        
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > 50 * 1024 * 1024:
            return jsonify({'error': 'ファイルサイズが大きすぎます（最大50MB）'}), 400
        
        print(f"📤 PDFアップロード開始: {file.filename}")
        
        import tempfile
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            file.save(temp_file.name)
            temp_path = temp_file.name
        
        try:
            result = process_pdf_file(temp_path, file.filename)
            
            return jsonify({
                'success': True,
                'message': f'"{file.filename}" を登録しました',
                'stats': result
            })
            
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'処理エラー: {str(e)}'}), 500


def process_pdf_file(pdf_path, filename):
    """PDFファイルを処理してデータベースに登録"""
    import pdfplumber
    
    print(f"📄 PDF処理開始: {filename}")
    
    pages_text = []
    total_chars = 0
    
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if text:
                text = text.strip()
                pages_text.append({'page': i, 'text': text})
                total_chars += len(text)
    
    if not pages_text:
        raise Exception("PDFからテキストを抽出できませんでした")
    
    print(f"✅ 全{len(pages_text)}ページ抽出完了")
    
    # 既存データをチェック
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        if db.use_mysql:
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = %s", (filename,))
        else:
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = ?", (filename,))
        
        exists = cursor.fetchone()[0] > 0
        
        if exists:
            if db.use_mysql:
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = %s", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = %s", (filename,))
            else:
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = ?", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = ?", (filename,))
            conn.commit()
            print(f"⚠️ 既存データを削除: {filename}")
        
    finally:
        cursor.close()
    
    # チャンク化とベクトル化
    all_chunks = []
    
    for page_data in pages_text:
        chunks = chunk_text(page_data['text'])
        
        for chunk in chunks:
            embedding = create_embedding(chunk)
            all_chunks.append({
                'page': page_data['page'],
                'text': chunk,
                'embedding': embedding
            })
    
    print(f"✅ 全{len(all_chunks)}チャンク処理完了")
    
    # データベースに保存
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        if db.use_mysql:
            cursor.execute("""
                INSERT INTO pdf_metadata 
                (filename, page_count, total_chars, total_chunks, added_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (filename, len(pages_text), total_chars, len(all_chunks), datetime.now()))
        else:
            cursor.execute("""
                INSERT INTO pdf_metadata 
                (filename, page_count, total_chars, total_chunks, added_date)
                VALUES (?, ?, ?, ?, ?)
            """, (filename, len(pages_text), total_chars, len(all_chunks), datetime.now().isoformat()))
        
        for chunk in all_chunks:
            embedding_json = json.dumps(chunk['embedding'])
            
            if db.use_mysql:
                cursor.execute("""
                    INSERT INTO pdf_contents 
                    (filename, page_number, chunk_text, embedding, added_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (filename, chunk['page'], chunk['text'], embedding_json, datetime.now()))
            else:
                cursor.execute("""
                    INSERT INTO pdf_contents 
                    (filename, page_number, chunk_text, embedding, added_date)
                    VALUES (?, ?, ?, ?, ?)
                """, (filename, chunk['page'], chunk['text'], embedding_json, datetime.now().isoformat()))
        
        conn.commit()
        print(f"✅ データベース登録完了: {filename}")
        
        return {
            'filename': filename,
            'page_count': len(pages_text),
            'total_chars': total_chars,
            'total_chunks': len(all_chunks)
        }
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def chunk_text(text, max_chunk_size=1000, overlap=200):
    """テキストをチャンクに分割"""
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chunk_size
        chunk = text[start:end]
        
        if end < len(text):
            last_period = chunk.rfind('。')
            last_newline = chunk.rfind('\n')
            last_space = chunk.rfind(' ')
            
            split_point = max(last_period, last_newline, last_space)
            if split_point > max_chunk_size * 0.5:
                chunk = chunk[:split_point + 1]
                end = start + split_point + 1
        
        if chunk.strip():
            chunks.append(chunk.strip())
        
        start = end - overlap
    
    return chunks


def create_embedding(text):
    """テキストをベクトル化"""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


# ============================================
# アプリケーション起動
# ============================================
try:
    print("🚀 RAG学習アプリ起動中...")
    initialize()
    print("✅ 初期化完了")
except Exception as e:
    print(f"❌ 初期化エラー: {e}")
    import traceback
    traceback.print_exc()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    
    print(f"📱 ポート {port} でアクセス可能")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
