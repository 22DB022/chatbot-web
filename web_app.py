"""
マルチメディア学習アプリ（Web版）
既存のRAGロジックを使用したFlask API
PostgreSQL/MySQL/SQLite 3種対応
"""
from flask import Flask, request, jsonify, render_template, send_file, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from openai import OpenAI
import os
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
    """RAG対応データベース（PostgreSQL/MySQL/SQLite 3種対応）"""
    
    def __init__(self):
        # 環境変数からデータベース設定を取得
        self.db_url = os.getenv('DATABASE_URL')  # PostgreSQL (Supabase)
        self.db_name = os.getenv('DB_NAME')       # MySQL (XAMPP)
        
        # データベースタイプを判定
        if self.db_url:
            # PostgreSQL (Supabase) - 本番環境
            print("✅ Supabase PostgreSQL接続")
            self.db_type = 'postgresql'
        elif self.db_name and MYSQL_AVAILABLE:
            # MySQL (XAMPP) - ローカル開発
            self.db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'user': os.getenv('DB_USER', 'root'),
                'password': os.getenv('DB_PASSWORD', ''),
                'database': self.db_name,
                'charset': 'utf8mb4'
            }
            print(f"✅ MySQL接続設定完了: {self.db_name}")
            self.db_type = 'mysql'
        else:
            # SQLite - フォールバック
            self.db_path = "rag_study_data.db"
            print(f"⚠️ SQLiteモード: {self.db_path}")
            self.db_type = 'sqlite'
    
    def get_connection(self):
        """DB接続を取得"""
        if self.db_type == 'postgresql':
            import psycopg2
            return psycopg2.connect(self.db_url)
        elif self.db_type == 'mysql':
            return pymysql.connect(**self.db_config)
        else:  # sqlite
            import sqlite3
            return sqlite3.connect(self.db_path)
    
    def vector_search(self, query_embedding, top_k=5):
        """ベクトル検索（コサイン類似度）"""
        conn = self.get_connection()
        
        try:
            if self.db_type == 'postgresql':
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT filename, chunk_text, embedding, page_number 
                    FROM pdf_contents
                """)
            elif self.db_type == 'mysql':
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute("""
                    SELECT filename, chunk_text, embedding, page_number 
                    FROM pdf_contents
                """)
            else:  # sqlite
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
                    # データベースタイプに応じて列にアクセス
                    if self.db_type == 'postgresql':
                        chunk_embedding = json.loads(row[2])
                        filename = row[0]
                        chunk_text = row[1]
                        page_number = row[3]
                    elif self.db_type == 'mysql':
                        chunk_embedding = json.loads(row['embedding'])
                        filename = row['filename']
                        chunk_text = row['chunk_text']
                        page_number = row['page_number']
                    else:  # sqlite
                        chunk_embedding = json.loads(row['embedding'])
                        filename = row['filename']
                        chunk_text = row['chunk_text']
                        page_number = row['page_number']
                    
                    chunk_vec = np.array(chunk_embedding)
                    
                    # コサイン類似度
                    similarity = np.dot(query_vec, chunk_vec) / (
                        np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec)
                    )
                    
                    similarities.append({
                        'filename': filename,
                        'text': chunk_text,
                        'page': page_number,
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
            if self.db_type == 'postgresql':
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT filename, page_count, total_chars, total_chunks, added_date 
                    FROM pdf_metadata 
                    ORDER BY added_date DESC
                """)
                columns = ['filename', 'page_count', 'total_chars', 'total_chunks', 'added_date']
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            elif self.db_type == 'mysql':
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute("""
                    SELECT filename, page_count, total_chars, total_chunks, added_date 
                    FROM pdf_metadata 
                    ORDER BY added_date DESC
                """)
                results = [dict(row) for row in cursor.fetchall()]
            else:  # sqlite
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT filename, page_count, total_chars, total_chunks, added_date 
                    FROM pdf_metadata 
                    ORDER BY added_date DESC
                """)
                results = [dict(row) for row in cursor.fetchall()]
            
            cursor.close()
            return results
            
        finally:
            conn.close()
    
    def get_stats(self):
        """統計情報"""
        conn = self.get_connection()
        
        try:
            cursor = conn.cursor()
        
            cursor.execute("""
            SELECT 
                COUNT(*) as pdf_count,
                COALESCE(SUM(page_count), 0) as total_pages,
                COALESCE(SUM(total_chunks), 0) as total_chunks
            FROM pdf_metadata
         """)
        
            result = cursor.fetchone()
            cursor.close()
        
         # 全てのDBタイプでタプルが返るので統一処理
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
- 絶対に提供された学習資料のみを参照して回答します

# 制約条件
- 学習資料に記載されていない内容は「資料に記載がありません」と答える
- 資料に基づかない推測や創作は禁止
- 親しみやすく励ます口調（〜だよ、〜してみよう、よくできたね）
- 回答は400文字以内を目安に簡潔にまとめる
- 必ず参照した資料のページ番号を示す
- 検定に無関係な内容には丁寧に断る

# 画像表示について
ユーザーが以下のような要求をした場合、該当ページの画像を表示する：
- 「図を見せて」「画像を表示して」
- 「図XX」「図表」「イラスト」などの言及
- 「視覚的に見たい」「見せてほしい」

対応方法: [IMAGE:ファイル名|ページ番号] の形式で指定

# 対応パターン

## パターン1: 知識・説明を求められた場合
1. 資料の内容を基に明確に説明する
2. 具体例を1〜2個挙げる
3. ページ番号を明記する
4. 軽く「理解できたかな？」と確認
5. 資料からの情報のみで回答

## パターン2: ユーザーが理解を示した場合（★重要★）
ユーザーが以下のような発言をした場合、**必ず理解度確認の問題を出題する**：

### 理解を示すキーワード・フレーズ：
- 「分かった」「わかった」「理解した」
- 「なるほど」「そういうことか」「そうなんだ」
- 「分かりました」「理解できました」
- 「OK」「了解」「大丈夫」
- 「簡単だね」「覚えた」
- 「ありがとう」（説明の後）

### 対応手順：
1. まず理解を認める（「よし！」「いいね！」）
2. **即座に**「じゃあ、本当に理解できたか確認してみよう！」と言う
3. **必ず問題を1問出題する**（3択問題）
4. ユーザーの回答を待つ

## パターン3: 問題・演習を求められた場合
1. 学習内容に沿った選択式問題を1問出題（A、B、Cの3択）
2. ユーザーの回答を待つ
3. 回答後、以下の対応：
   - **正解の場合**: 褒めて、解説を追加し、次の学習を提案
   - **不正解の場合**: 否定せず「惜しい！」と励まし、ヒントを出して再挑戦を促す
4. 資料からの内容で問題を作成

## パターン4: ヒントを求められた場合
1. **1回目**: 概念的なヒント（どの分野に関係するか）
2. **2回目**: より具体的なヒント（選択肢の絞り込み）
3. **3回目**: ほぼ答えに近い情報（キーワードを示す）

## パターン5: 初回接触・挨拶
- 簡潔に挨拶
- 「何を学習したい？」と聞く
- 選択肢は出さない（ユーザーの自由な質問を促す）

# 禁止事項
- 資料外の情報を創作する
- ユーザーが理解を示したのに問題を出さない
- 間違いを責める口調
- 連続して複数の問題を出す
- 長すぎる説明（400文字を大幅に超える）
"""


def initialize():
    """アプリケーション初期化"""
    global db, client
    
    # OpenAI API初期化
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise Exception("OPENAI_API_KEYが設定されていません")
    
    client = OpenAI(api_key=api_key)
    
    # データベース初期化（自動判定）
    db = RAGDatabase()
    
    if db.db_type == 'postgresql':
        print(f"✅ RAGデータベース初期化完了 (PostgreSQL - Supabase)")
    elif db.db_type == 'mysql':
        print(f"✅ RAGデータベース初期化完了 (MySQL)")
    else:
        print(f"✅ RAGデータベース初期化完了 (SQLite - フォールバック)")


# ============================================
# APIエンドポイント
# ============================================

@app.route('/')
def index():
    """メインページ"""
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health():
    """ヘルスチェック"""
    try:
        stats = db.get_stats()
        return jsonify({
            'status': 'ok',
            'database': db.db_type.upper(),
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
            'database_type': db.db_type.upper()
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
    """PDFアップロードと登録（AWS Lambda経由）"""
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
        
        # ファイルをBase64エンコード
        import base64
        pdf_data = file.read()
        pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
        
        # AWS Lambda URLを取得
        lambda_url = os.getenv('AWS_LAMBDA_URL')
        
        if not lambda_url:
            return jsonify({'error': 'AWS_LAMBDA_URLが設定されていません'}), 500
        
        print(f"🚀 AWS Lambdaに送信: {lambda_url}")
        
        import requests
        
        # Lambda関数を呼び出し
        response = requests.post(
            lambda_url,
            json={
                'pdf_data': pdf_base64,
                'filename': file.filename
            },
            timeout=600  # 10分タイムアウト
        )
        
        print(f"📨 Lambda応答: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('success'):
                return jsonify({
                    'success': True,
                    'message': f'"{file.filename}" を登録しました',
                    'stats': {
                        'filename': result.get('filename'),
                        'page_count': result.get('page_count'),
                        'total_chars': result.get('total_chars'),
                        'total_chunks': result.get('total_chunks')
                    }
                })
            else:
                error_msg = result.get('error', '不明なエラー')
                print(f"❌ Lambda エラー: {error_msg}")
                return jsonify({'error': f'処理エラー: {error_msg}'}), 500
        else:
            error_text = response.text
            print(f"❌ Lambda HTTPエラー: {error_text}")
            return jsonify({'error': f'処理エラー: {error_text}'}), 500
        
    except requests.exceptions.Timeout:
        print(f"⏰ タイムアウト")
        return jsonify({'error': '処理がタイムアウトしました。PDFが大きすぎる可能性があります。'}), 504
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'処理エラー: {str(e)}'}), 500


@app.route('/api/images/<filename>/<int:page_number>', methods=['GET'])
def get_page_images(filename, page_number):
    """特定ページの画像を取得"""
    try:
        images = get_images_for_page(filename, page_number)
        
        # 画像パスをURLパスに変換
        for img in images:
            img['url'] = '/' + img['image_path'].replace('\\', '/')
        
        return jsonify({
            'images': images,
            'count': len(images)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# PDF処理関数
# ============================================

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
        if db.db_type == 'postgresql':
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = %s", (filename,))
        elif db.db_type == 'mysql':
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = %s", (filename,))
        else:  # sqlite
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = ?", (filename,))
        
        exists = cursor.fetchone()[0] > 0
        
        if exists:
            if db.db_type == 'postgresql':
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = %s", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = %s", (filename,))
                cursor.execute("DELETE FROM pdf_images WHERE filename = %s", (filename,))
            elif db.db_type == 'mysql':
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = %s", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = %s", (filename,))
                cursor.execute("DELETE FROM pdf_images WHERE filename = %s", (filename,))
            else:  # sqlite
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = ?", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = ?", (filename,))
                cursor.execute("DELETE FROM pdf_images WHERE filename = ?", (filename,))
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
        # メタデータを挿入
        if db.db_type == 'postgresql':
            cursor.execute("""
                INSERT INTO pdf_metadata 
                (filename, page_count, total_chars, total_chunks, added_date)
                VALUES (%s, %s, %s, %s, NOW())
            """, (filename, len(pages_text), total_chars, len(all_chunks)))
        elif db.db_type == 'mysql':
            cursor.execute("""
                INSERT INTO pdf_metadata 
                (filename, page_count, total_chars, total_chunks, added_date)
                VALUES (%s, %s, %s, %s, NOW())
            """, (filename, len(pages_text), total_chars, len(all_chunks)))
        else:  # sqlite
            cursor.execute("""
                INSERT INTO pdf_metadata 
                (filename, page_count, total_chars, total_chunks, added_date)
                VALUES (?, ?, ?, ?, ?)
            """, (filename, len(pages_text), total_chars, len(all_chunks), datetime.now().isoformat()))
        
        # チャンクを挿入
        for chunk in all_chunks:
            embedding_json = json.dumps(chunk['embedding'])
            
            if db.db_type == 'postgresql':
                cursor.execute("""
                    INSERT INTO pdf_contents 
                    (filename, page_number, chunk_text, embedding, added_date)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (filename, chunk['page'], chunk['text'], embedding_json))
            elif db.db_type == 'mysql':
                cursor.execute("""
                    INSERT INTO pdf_contents 
                    (filename, page_number, chunk_text, embedding, added_date)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (filename, chunk['page'], chunk['text'], embedding_json))
            else:  # sqlite
                cursor.execute("""
                    INSERT INTO pdf_contents 
                    (filename, page_number, chunk_text, embedding, added_date)
                    VALUES (?, ?, ?, ?, ?)
                """, (filename, chunk['page'], chunk['text'], embedding_json, datetime.now().isoformat()))
        
        conn.commit()
        print(f"✅ データベース登録完了: {filename}")
        
        # 画像を抽出して保存
        try:
            images = extract_images_from_pdf(pdf_path, filename)
            if images:
                save_images_to_db(images)
        except Exception as img_error:
            print(f"⚠️ 画像処理でエラー（処理は継続）: {img_error}")
        
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


def extract_images_from_pdf(pdf_path, filename):
    """PDFから画像を抽出"""
    import pdfplumber
    from PIL import Image
    import io
    
    # 画像保存ディレクトリ
    images_dir = os.path.join('assets', 'images', 'pdf_images')
    os.makedirs(images_dir, exist_ok=True)
    
    print(f"🖼️ 画像抽出開始: {filename}")
    
    extracted_images = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # ページ内の画像を抽出
                if hasattr(page, 'images') and page.images:
                    for img_index, img_info in enumerate(page.images, 1):
                        try:
                            # 画像データを取得
                            if hasattr(page, 'extract_image'):
                                # pdfplumber 0.9.0以降
                                image_obj = page.within_bbox(
                                    (img_info['x0'], img_info['top'], 
                                     img_info['x1'], img_info['bottom'])
                                ).to_image()
                                
                                # 画像を保存
                                base_filename = os.path.splitext(filename)[0]
                                safe_filename = "".join(c for c in base_filename if c.isalnum() or c in (' ', '-', '_'))
                                image_filename = f"{safe_filename}_page{page_num}_img{img_index}.png"
                                image_path = os.path.join(images_dir, image_filename)
                                
                                image_obj.save(image_path)
                                
                                # 画像情報を記録
                                extracted_images.append({
                                    'filename': filename,
                                    'page_number': page_num,
                                    'image_path': os.path.join('assets', 'images', 'pdf_images', image_filename),
                                    'image_index': img_index,
                                    'width': int(img_info['width']),
                                    'height': int(img_info['height']),
                                    'added_date': datetime.now().isoformat()
                                })
                                
                                print(f"  ✓ ページ{page_num} 画像{img_index}を抽出")
                        except Exception as e:
                            print(f"  ⚠️ ページ{page_num} 画像{img_index}の抽出失敗: {e}")
                            continue
    except Exception as e:
        print(f"❌ PDF画像抽出エラー: {e}")
        return []
    
    print(f"✅ {len(extracted_images)}個の画像を抽出しました")
    return extracted_images


def save_images_to_db(images):
    """画像情報をデータベースに保存"""
    if not images:
        return
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        for img in images:
            if db.db_type == 'postgresql':
                cursor.execute("""
                    INSERT INTO pdf_images 
                    (filename, page_number, image_path, image_index, width, height, added_date)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """, (
                    img['filename'],
                    img['page_number'],
                    img['image_path'],
                    img['image_index'],
                    img['width'],
                    img['height']
                ))
            elif db.db_type == 'mysql':
                cursor.execute("""
                    INSERT INTO pdf_images 
                    (filename, page_number, image_path, image_index, width, height, added_date)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """, (
                    img['filename'],
                    img['page_number'],
                    img['image_path'],
                    img['image_index'],
                    img['width'],
                    img['height']
                ))
            else:  # sqlite
                cursor.execute("""
                    INSERT INTO pdf_images 
                    (filename, page_number, image_path, image_index, width, height, added_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    img['filename'],
                    img['page_number'],
                    img['image_path'],
                    img['image_index'],
                    img['width'],
                    img['height'],
                    img['added_date']
                ))
        
        conn.commit()
        print(f"✅ {len(images)}個の画像情報をデータベースに保存")
    except Exception as e:
        conn.rollback()
        print(f"❌ 画像情報の保存エラー: {e}")
        raise e
    finally:
        cursor.close()
        conn.close()


def get_images_for_page(filename, page_number):
    """特定ページの画像を取得"""
    conn = db.get_connection()
    
    try:
        if db.db_type == 'postgresql':
            cursor = conn.cursor()
            cursor.execute("""
                SELECT image_path, image_index, width, height
                FROM pdf_images
                WHERE filename = %s AND page_number = %s
                ORDER BY image_index
            """, (filename, page_number))
            
            columns = ['image_path', 'image_index', 'width', 'height']
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        elif db.db_type == 'mysql':
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute("""
                SELECT image_path, image_index, width, height
                FROM pdf_images
                WHERE filename = %s AND page_number = %s
                ORDER BY image_index
            """, (filename, page_number))
            
            results = [dict(row) for row in cursor.fetchall()]
        else:  # sqlite
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT image_path, image_index, width, height
                FROM pdf_images
                WHERE filename = ? AND page_number = ?
                ORDER BY image_index
            """, (filename, page_number))
            
            results = [dict(row) for row in cursor.fetchall()]
        
        cursor.close()
        return results
    finally:
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