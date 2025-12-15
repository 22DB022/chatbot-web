"""
マルチメディア学習アプリ(Web版)
高度版ハイブリッド検索 (SudachiPy + TF-IDF)
"""
from flask import Flask, request, jsonify, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from openai import OpenAI
import os
import json
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
import sqlite3
import uuid
import re
from collections import Counter
from typing import List, Dict
import math

# 環境変数読み込み
load_dotenv()

# PyMySQL
try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# SudachiPy
try:
    from sudachipy import tokenizer
    from sudachipy import dictionary
    SUDACHI_AVAILABLE = True
except ImportError:
    SUDACHI_AVAILABLE = False
    print("⚠️ SudachiPyが未インストール。簡易版キーワード抽出を使用します。")

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
keyword_extractor = None


# ============================================
# 高度版キーワード抽出
# ============================================

class AdvancedKeywordExtractor:
    """SudachiPyによる高度なキーワード抽出"""
    
    def __init__(self):
        if SUDACHI_AVAILABLE:
            try:
                self.tokenizer_obj = dictionary.Dictionary().create()
                self.mode = tokenizer.Tokenizer.SplitMode.C
                print("✅ SudachiPy初期化完了")
                self.enabled = True
            except Exception as e:
                print(f"⚠️ SudachiPy初期化失敗: {e}")
                self.enabled = False
        else:
            self.tokenizer_obj = None
            self.enabled = False
    
    def extract_keywords(self, text: str, min_length: int = 2) -> List[str]:
        """キーワード抽出"""
        if not self.enabled or not self.tokenizer_obj:
            return self._fallback_extract(text, min_length)
        
        keywords = []
        
        try:
            tokens = self.tokenizer_obj.tokenize(text, self.mode)
            
            for token in tokens:
                pos = token.part_of_speech()[0]
                pos_detail = token.part_of_speech()[1]
                surface = token.surface()
                
                # 名詞系のみ抽出
                if pos == '名詞' and pos_detail in ['普通名詞', 'サ変可能', '固有名詞']:
                    if len(surface) >= min_length:
                        # 専門用語を優先
                        if self._is_technical_term(surface) or len(surface) >= 3:
                            keywords.append(surface)
            
            # 重複除去
            seen = set()
            unique = []
            for kw in keywords:
                if kw not in seen:
                    seen.add(kw)
                    unique.append(kw)
            
            return unique
        
        except Exception as e:
            print(f"⚠️ 形態素解析エラー: {e}")
            return self._fallback_extract(text, min_length)
    
    def _is_technical_term(self, word: str) -> bool:
        """専門用語判定"""
        # カタカナ語
        if re.match(r'^[ァ-ヶー]+$', word):
            return True
        # 英語
        if re.match(r'^[A-Za-z]+$', word):
            return True
        # 専門用語パターン
        if re.search(r'(方式|プロトコル|システム|技術|暗号)$', word):
            return True
        return False
    
    def _fallback_extract(self, text: str, min_length: int) -> List[str]:
        """フォールバック抽出"""
        keywords = []
        keywords.extend(re.findall(r'[ァ-ヶー]{3,}', text))
        keywords.extend(re.findall(r'[A-Za-z]{2,}', text))
        keywords.extend(re.findall(r'[一-龠]{2,}[ぁ-ん]*', text))
        return list(set([kw for kw in keywords if len(kw) >= min_length]))


def calculate_tfidf_scores(query_keywords: List[str], 
                          all_chunks: List[Dict],
                          chunk_idx: int) -> Dict[str, float]:
    """TF-IDFスコア計算"""
    if chunk_idx >= len(all_chunks):
        return {}
    
    current_chunk = all_chunks[chunk_idx]
    chunk_keywords = current_chunk.get('keywords', [])
    
    # TF計算
    keyword_counts = Counter(chunk_keywords)
    total_keywords = len(chunk_keywords)
    
    # IDF計算
    num_chunks = len(all_chunks)
    idf_scores = {}
    
    for keyword in query_keywords:
        doc_freq = sum(1 for chunk in all_chunks if keyword in chunk.get('keywords', []))
        if doc_freq > 0:
            idf_scores[keyword] = math.log(num_chunks / doc_freq)
        else:
            idf_scores[keyword] = 0.0
    
    # TF-IDF
    tfidf_scores = {}
    for keyword in query_keywords:
        if keyword in chunk_keywords:
            tf = keyword_counts[keyword] / total_keywords if total_keywords > 0 else 0
            idf = idf_scores.get(keyword, 0)
            tfidf_scores[keyword] = tf * idf
        else:
            tfidf_scores[keyword] = 0.0
    
    return tfidf_scores


def advanced_keyword_match_score(query_keywords: List[str],
                                 chunk_keywords: List[str],
                                 tfidf_scores: Dict[str, float]) -> float:
    """高度なキーワードマッチング"""
    if not query_keywords:
        return 0.0
    
    query_set = set(query_keywords)
    chunk_set = set(chunk_keywords)
    exact_matches = query_set & chunk_set
    
    if not exact_matches:
        return 0.0
    
    # マッチ率
    match_rate = len(exact_matches) / len(query_set)
    
    # TF-IDF重み付け
    tfidf_weight = sum(tfidf_scores.get(kw, 0) for kw in exact_matches)
    max_possible_tfidf = sum(tfidf_scores.get(kw, 0) for kw in query_set)
    
    if max_possible_tfidf > 0:
        tfidf_ratio = tfidf_weight / max_possible_tfidf
    else:
        tfidf_ratio = 0
    
    # 統合: 60% マッチ率 + 40% TF-IDF
    final_score = (0.6 * match_rate) + (0.4 * tfidf_ratio)
    return min(final_score, 1.0)


def extract_context_from_history(messages: List[Dict], max_turns: int = 2) -> str:
    """会話履歴から文脈を抽出"""
    context_parts = []
    
    # 最後のN個のユーザーメッセージを取得
    user_messages = [m for m in messages if m['role'] == 'user']
    recent_messages = user_messages[-max_turns:] if len(user_messages) > 0 else []
    
    for msg in recent_messages:
        content = msg['content']
        # システムプロンプトの注釈を除去
        if "(注意:" in content:
            content = content.split("(注意:")[0]
        if "以下は学習資料からの抜粋です" in content:
            content = content.split("以下は学習資料からの抜粋です")[0]
        if "質問:" in content:
            content = content.split("質問:")[-1]
        
        context_parts.append(content.strip())
    
    return " ".join(context_parts)


def expand_query_with_context(query: str, context: str, extractor) -> List[str]:
    """文脈を考慮してクエリを拡張"""
    # 現在のクエリからキーワード抽出
    query_keywords = extractor.extract_keywords(query)
    
    # 文脈からもキーワード抽出
    context_keywords = extractor.extract_keywords(context)
    
    # 統合（重複除去、順序保持）
    all_keywords = []
    seen = set()
    
    # クエリのキーワードを優先
    for kw in query_keywords:
        if kw not in seen:
            all_keywords.append(kw)
            seen.add(kw)
    
    # 文脈のキーワードを追加（最大3個まで）
    for kw in context_keywords[:3]:
        if kw not in seen:
            all_keywords.append(kw)
            seen.add(kw)
    
    return all_keywords


def advanced_hybrid_search(query: str,
                          vector_results: List[Dict],
                          alpha: float = 0.7,
                          context: str = "") -> List[Dict]:
    """高度版ハイブリッド検索（文脈考慮版）"""
    global keyword_extractor
    
    # 文脈を考慮したキーワード抽出
    if context:
        query_keywords = expand_query_with_context(query, context, keyword_extractor)
        print(f"   📌 抽出キーワード: {query_keywords}")
        if len(context) > 50:
            print(f"   📝 文脈考慮: {context[:50]}...")
        else:
            print(f"   📝 文脈考慮: {context}")
    else:
        query_keywords = keyword_extractor.extract_keywords(query)
        print(f"   📌 抽出キーワード: {query_keywords}")
    
    if not query_keywords:
        print("   ⚠️ キーワード抽出失敗、ベクトル検索のみ")
        # キーワードスコアをデフォルト値で設定
        for result in vector_results:
            result['keyword_score'] = 0.0
            result['hybrid_score'] = result['similarity']  # ベクトルスコアのみ
            result['tfidf'] = 0.0
        return vector_results
    
    # 各チャンクからキーワード抽出
    all_chunks_with_keywords = []
    for result in vector_results:
        chunk_keywords = keyword_extractor.extract_keywords(result['text'])
        all_chunks_with_keywords.append({
            'keywords': chunk_keywords,
            'text': result['text']
        })
    
    # スコア計算
    for idx, result in enumerate(vector_results):
        tfidf_scores = calculate_tfidf_scores(
            query_keywords,
            all_chunks_with_keywords,
            idx
        )
        
        chunk_keywords = all_chunks_with_keywords[idx]['keywords']
        keyword_score = advanced_keyword_match_score(
            query_keywords,
            chunk_keywords,
            tfidf_scores
        )
        
        vector_score = result['similarity']
        hybrid_score = (alpha * vector_score) + ((1 - alpha) * keyword_score)
        
        result['keyword_score'] = keyword_score
        result['hybrid_score'] = hybrid_score
        result['tfidf'] = sum(tfidf_scores.values())
    
    vector_results.sort(key=lambda x: x['hybrid_score'], reverse=True)
    return vector_results


def clean_text(text):
    """テキストクリーニング"""
    text = re.sub(r'[•·．]+', '', text)
    text = re.sub(r'([^\w\s])\1{3,}', '', text)
    
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if re.match(r'^[^\w\s]+$', line.strip()):
            continue
        if len(line.strip()) > 0 and not re.search(r'[ぁ-んァ-ヶー一-龠a-zA-Z0-9]', line):
            continue
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()


# ============================================
# データベースクラス（変更なし）
# ============================================

class RAGDatabase:
    """RAG対応データベース"""
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self.db_name = os.getenv('DB_NAME')
        
        if self.db_url:
            print("✅ Supabase PostgreSQL接続")
            self.db_type = 'postgresql'
        elif self.db_name and MYSQL_AVAILABLE:
            self.db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'user': os.getenv('DB_USER', 'root'),
                'password': os.getenv('DB_PASSWORD', ''),
                'database': self.db_name,
                'charset': 'utf8mb4',
                'use_unicode': True,
                'collation': 'utf8mb4_unicode_ci',
                'init_command': "SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci"
            }
            print(f"✅ MySQL接続設定完了: {self.db_name}")
            self.db_type = 'mysql'
        else:
            self.db_path = "rag_study_data.db"
            print(f"⚠️ SQLiteモード: {self.db_path}")
            self.db_type = 'sqlite'
    
    def get_connection(self):
        """DB接続を取得"""
        if self.db_type == 'postgresql':
            import psycopg2
            return psycopg2.connect(self.db_url)
        elif self.db_type == 'mysql':
            conn = pymysql.connect(**self.db_config)
            with conn.cursor() as cursor:
                cursor.execute("SET NAMES utf8mb4")
                cursor.execute("SET CHARACTER SET utf8mb4")
                cursor.execute("SET character_set_connection=utf8mb4")
            return conn
        else:
            return sqlite3.connect(self.db_path)
    
    def vector_search(self, query_embedding, top_k=5):
        """ベクトル検索"""
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
            
            query_vec = np.array(query_embedding)
            similarities = []
            
            for row in results:
                try:
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
                    else:
                        chunk_embedding = json.loads(row['embedding'])
                        filename = row['filename']
                        chunk_text = row['chunk_text']
                        page_number = row['page_number']
                    
                    chunk_vec = np.array(chunk_embedding)
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
            else:
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
- 資料から得た情報のみで応えます

# 制約条件
- 学習資料に記載されていない内容は「資料に記載がありません」と答える
- 資料に基づかない推測や創作は禁止
- 親しみやすく励ます口調(〜だよ、〜してみよう、よくできたね)
- 回答は400文字以内を目安に簡潔にまとめる
- 必ず参照した資料のページ番号を示す
- 検定に無関係な内容には丁寧に断る
- 必ず資料から基づいて回答する

# 対応パターン

## パターン1: 知識・説明を求められた場合
1. 資料の内容を基に明確に説明する
2. 具体例を1〜2個挙げる
3. ページ番号を明記する
4. 軽く「理解できたかな?」と確認
5. 資料からの情報のみで回答
6. 専門用語の解説を頼まれた場合は資料でよく使われている単語の解説をしてください

## パターン2: ユーザーが理解を示した場合(★重要★)
ユーザーが以下のような発言をした場合、**必ず理解度確認の問題を出題する**:
- 「分かった」「わかった」「理解した」
- 「なるほど」「そういうことか」
- 「OK」「了解」「大丈夫」

### 対応手順:
1. まず理解を認める(「よし!」「いいね!」)
2. **即座に**「じゃあ、本当に理解できたか確認してみよう!」と言う
3. **必ず問題を1問出題する**(3択問題)
4. ユーザーの回答を待つ

## パターン3: 問題・演習を求められた場合
1. 学習内容に沿った選択式問題を1問出題(A、B、Cの3択)
2. ユーザーの回答を待つ
3. 回答後、以下の対応:
   - **正解の場合**: 褒めて、解説を追加し、次の学習を提案
   - **不正解の場合**: 否定せず「惜しい!」と励まし、ヒントを出して再挑戦を促す

# 禁止事項
- 資料外の情報を創作する
- ユーザーが理解を示したのに問題を出さない
- 間違いを責める口調
- 連続して複数の問題を出す
- 長すぎる説明(400文字を大幅に超える)
"""


def initialize():
    """アプリケーション初期化"""
    global db, client, keyword_extractor
    
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise Exception("OPENAI_API_KEYが設定されていません")
    
    client = OpenAI(api_key=api_key)
    db = RAGDatabase()
    keyword_extractor = AdvancedKeywordExtractor()
    
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
            'sudachi': SUDACHI_AVAILABLE,
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
            'database_type': db.db_type.upper(),
            'sudachi_enabled': SUDACHI_AVAILABLE
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/query', methods=['POST'])
def query():
    """ユーザークエリに応答(高度版ハイブリッド検索)"""
    try:
        data = request.json
        query_text = data.get('query', '').strip()
        conversation_id = data.get('conversation_id')
        
        if not query_text:
            return jsonify({'error': 'クエリが必要です'}), 400
        
        # 会話履歴の取得
        if conversation_id and conversation_id in conversation_history:
            messages = conversation_history[conversation_id]
        else:
            conversation_id = str(uuid.uuid4())
            messages = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]
        
        # RAG検索
        print(f"\n📝 ユーザークエリ: {query_text}")
        query_embedding = create_embedding(query_text)
        results = db.vector_search(query_embedding, top_k=10)
        
        # デバッグログ
        print(f"🔍 ベクトル検索結果: {len(results)}件")
        for i, r in enumerate(results[:5]):
            print(f"  [{i+1}] ページ{r['page']}, 類似度: {r['similarity']:.4f}")
        
        if results:
            # 会話履歴から文脈を抽出
            context = extract_context_from_history(messages, max_turns=2)
            
            # 高度版ハイブリッド検索を適用（文脈考慮）
            results = advanced_hybrid_search(query_text, results, alpha=0.7, context=context)
            results = results[:5]
            
            # デバッグログ
            print(f"\n🎯 高度版ハイブリッド検索結果:")
            for i, r in enumerate(results):
                print(f"  [{i+1}] ページ{r['page']}")
                print(f"      ベクトル: {r['similarity']:.4f}")
                print(f"      キーワード: {r.get('keyword_score', 0.0):.4f}")
                print(f"      TF-IDF: {r.get('tfidf', 0.0):.4f}")
                print(f"      統合: {r.get('hybrid_score', r['similarity']):.4f}")
            
            # 統合スコアでフィルタリング
            relevant_results = [r for r in results if r.get('hybrid_score', r['similarity']) > 0.5]
            
            if relevant_results:
                print(f"✅ 関連性の高い結果: {len(relevant_results)}件\n")
                context_parts = []
                for r in relevant_results:
                    context_parts.append(
                        f"【{r['filename']} - ページ{r['page']}】\n{r['text']}"
                    )
                context = "\n\n".join(context_parts)
                
                user_message = f"""以下は学習資料からの抜粋です。この情報のみを使って回答してください:

{context}

質問: {query_text}"""
            else:
                print("⚠️ 関連性の高い結果なし(統合スコア<0.5)\n")
                user_message = f"質問: {query_text}\n\n(注意: 資料から関連情報が見つかりませんでした。資料に基づいて回答できない場合はその旨を伝えてください)"
        else:
            print("⚠️ 検索結果なし\n")
            user_message = f"質問: {query_text}\n\n(注意: 資料から情報が見つかりませんでした。資料に基づいて回答できない場合はその旨を伝えてください)"
        
        messages.append({"role": "user", "content": user_message})
        
        # GPT-4 APIを呼び出し
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=2000,
            temperature=0.7
        )
        
        assistant_response = response.choices[0].message.content
        messages.append({"role": "assistant", "content": assistant_response})
        
        # 会話履歴を保存
        conversation_history[conversation_id] = messages
        
        # 統計情報
        stats = db.get_stats()
        
        return jsonify({
            'response': assistant_response,
            'conversation_id': conversation_id,
            'stats': stats
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'処理エラー: {str(e)}'}), 500


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
            return jsonify({'error': 'ファイルサイズが大きすぎます(最大50MB)'}), 400
        
        print(f"📤 PDFアップロード開始: {file.filename}")
        
        import tempfile
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            file.save(tmp_file.name)
            temp_path = tmp_file.name
        
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


# ============================================
# PDF処理関数（変更なし）
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
                text = clean_text(text)
                
                print(f"  ページ{i}: {len(text)}文字抽出")
                
                if i == 1:
                    print(f"\n📄 1ページ目の内容(最初の200文字):\n{text[:200]}\n")
                
                pages_text.append({'page': i, 'text': text})
                total_chars += len(text)
            else:
                print(f"  ⚠️ ページ{i}: テキストなし")
    
    if not pages_text:
        raise Exception("PDFからテキストを抽出できませんでした")
    
    print(f"✅ 全{len(pages_text)}ページ抽出完了 (合計{total_chars}文字)")
    
    # 既存データをチェック
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        if db.db_type == 'postgresql':
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = %s", (filename,))
        elif db.db_type == 'mysql':
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = %s", (filename,))
        else:
            cursor.execute("SELECT COUNT(*) FROM pdf_metadata WHERE filename = ?", (filename,))
        
        exists = cursor.fetchone()[0] > 0
        
        if exists:
            print(f"⚠️ 既存データを削除: {filename}")
            if db.db_type == 'postgresql':
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = %s", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = %s", (filename,))
            elif db.db_type == 'mysql':
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = %s", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = %s", (filename,))
            else:
                cursor.execute("DELETE FROM pdf_metadata WHERE filename = ?", (filename,))
                cursor.execute("DELETE FROM pdf_contents WHERE filename = ?", (filename,))
            conn.commit()
        
    finally:
        cursor.close()
    
    # チャンク化とベクトル化
    all_chunks = []
    
    for page_data in pages_text:
        chunks = chunk_text(page_data['text'])
        
        if page_data['page'] == 1 and len(chunks) > 0:
            print(f"\n📝 1ページ目の最初のチャンク:\n{chunks[0][:200]}\n")
        
        for chunk in chunks:
            chunk = clean_text(chunk)
            
            if len(chunk.strip()) < 20:
                continue
            
            embedding = create_embedding(chunk)
            all_chunks.append({
                'page': page_data['page'],
                'text': chunk,
                'embedding': embedding
            })
    
    if len(all_chunks) == 0:
        raise Exception("有効なテキストチャンクが生成できませんでした")
    
    print(f"✅ 全{len(all_chunks)}チャンク処理完了")
    
    # データベースに保存
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
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
        else:
            cursor.execute("""
                INSERT INTO pdf_metadata 
                (filename, page_count, total_chars, total_chunks, added_date)
                VALUES (?, ?, ?, ?, ?)
            """, (filename, len(pages_text), total_chars, len(all_chunks), datetime.now().isoformat()))
        
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
    print("🚀 RAG学習アプリ起動中(高度版ハイブリッド検索)...")
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