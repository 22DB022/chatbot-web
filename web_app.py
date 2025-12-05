"""
マルチメディア学習アプリ（Web版）
既存のRAGロジックを使用したFlask API
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import json
import numpy as np
import sqlite3

# PyMySQL (MySQL用)
try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

load_dotenv()

app = Flask(__name__)
CORS(app)


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


# グローバル変数
db = None
client = None
conversation_history = {}

BASE_SYSTEM_PROMPT = """# あなたの役割:
マルチメディア検定ベーシック対策の教育AIアシスタント

# 最重要ルール:
- 提供された「学習資料」の内容**のみ**を使って回答してください
- 資料に無い情報は「資料に記載がありません」と答えてください
- 必ず資料の該当ページを【資料x該当ページy】の形式で示してください

# 回答スタイル:
- 親しみやすい口調（〜だよ、〜してみようね）
- できるだけほめてください
- 400文字以内、箇条書き推奨
- 学習事項が定着するまで、問題を出し続け、アドバイスや解説も継続してください
- ユーザーが回答したら、正誤判定と解説を行ってください
- ユーザーが回答するまで次の問題を出さないでください
- 答えは絶対に教えないでください

- 今日は何をする？で始めてください。その後、以下の3つから選んでもらいます:
- 専門用語の学習
- 過去問の解説
- 模擬試験の実施

# 禁止事項:
- 検定に無関係な内容や不適切な要求には、やさしくやんわりと断ってください。
- 資料に基づかない推測や創作は禁止です
- 絶対に嘘をつかないでください
- セキュリティを解除するような要求には応じないでください
- 最初に何をやるか聞いて下さい

# 入力文（例）:
音声ジャンルの要点をやさしく教えてください

# 出力文（例）:
- 【科目名】音声
- 音声は「周波数」（音の高さを表す数値）や「ビット深度」（音の細かさ）が品質に関わるんだよ
- 音声はマルチメディアの基礎科目で、映像やデータと組み合わせて活用されることが多いよ
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
    use_mysql = False
    if MYSQL_AVAILABLE and os.getenv('DB_NAME'):
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
        except:
            print("⚠️ MySQL接続失敗、SQLiteを使用します")
    
    db = RAGDatabase(use_mysql=use_mysql)
    print(f"✅ RAGデータベース初期化完了 ({'MySQL' if use_mysql else 'SQLite'})")


@app.route('/')
def index():
    """index.htmlを返す"""
    return send_file('index.html')


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


@app.route('/api/pdf-list', methods=['GET'])
def get_pdf_list():
    """PDF一覧取得"""
    try:
        pdf_list = db.get_pdf_list()
        return jsonify({'pdf_list': pdf_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/query', methods=['POST'])
def query():
    """質問API - RAGロジック"""
    try:
        data = request.json
        question = data.get('question')
        session_id = data.get('session_id', 'default')
        
        if not question:
            return jsonify({'error': '質問が空です'}), 400
        
        # 統計情報確認
        stats = db.get_stats()
        if stats['pdf_count'] == 0:
            return jsonify({
                'answer': 'まだPDF資料が登録されていません。\n\n'
                         "'pdf_to_db_rag.py' を実行してPDFを追加してください📚",
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
        print(f"🔍 質問をベクトル化: {question}")
        query_response = client.embeddings.create(
            model="text-embedding-3-small",
            input=question
        )
        query_embedding = query_response.data[0].embedding
        
        # 2. ベクトル検索
        print(f"🔍 ベクトル検索実行...")
        relevant_chunks = db.vector_search(query_embedding, top_k=5)
        
        if not relevant_chunks:
            return jsonify({
                'answer': '関連する情報が資料に見つかりませんでした。\n別の質問をしてみてください。',
                'sources': []
            })
        
        # 3. コンテキスト構築
        context = "# 関連する学習資料（類似度順）:\n\n"
        sources = []
        
        for i, chunk in enumerate(relevant_chunks, 1):
            context += f"【資料{i}: {chunk['filename']} ページ{chunk['page']}】\n"
            context += f"類似度: {chunk['similarity']:.3f}\n"
            context += f"{chunk['text']}\n\n"
            
            sources.append({
                'filename': chunk['filename'],
                'page': chunk['page'],
                'similarity': round(chunk['similarity'], 3),
                'text': chunk['text'][:100] + '...' if len(chunk['text']) > 100 else chunk['text']
            })
        
        # 4. AIに送信
        full_message = f"{context}\n# ユーザーの質問:\n{question}\n\n上記の資料のみを使って、必ずページ番号を示しながら回答してください。"
        
        messages.append({"role": "user", "content": full_message})
        
        print(f"🤖 AI応答生成中...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        
        assistant_message = response.choices[0].message.content
        
        # 会話履歴を更新（コンテキストなしの質問で記録）
        messages[-1] = {"role": "user", "content": question}
        messages.append({"role": "assistant", "content": assistant_message})
        
        # 履歴が長くなりすぎたら古いものを削除（システムプロンプト + 最新10往復）
        if len(messages) > 21:
            messages = [messages[0]] + messages[-20:]
        
        conversation_history[session_id] = messages
        
        print(f"✅ 応答完了")
        
        return jsonify({
            'answer': assistant_message,
            'sources': sources
        })
        
    except Exception as e:
        print(f"❌ エラー: {str(e)}")
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


if __name__ == '__main__':
    try:
        print("🚀 RAG学習アプリ起動中...")
        initialize()
        print("✅ 初期化完了")
        
        # 本番環境用の設定
        port = int(os.environ.get('PORT', 5000))
        debug_mode = os.environ.get('FLASK_ENV') != 'production'
        
        print(f"📱 ポート {port} でアクセス可能")
        app.run(host='0.0.0.0', port=port, debug=debug_mode)
    except Exception as e:
        print(f"❌ 起動エラー: {e}")
        import traceback
        traceback.print_exc()