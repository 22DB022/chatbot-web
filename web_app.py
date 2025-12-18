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
selected_pdfs = {}  # セッションIDごとに選択されたPDFを管理
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


def is_quiz_answer(query: str, messages: List[Dict]) -> bool:
    """
    クエリが問題への回答かどうかを判定
    
    Args:
        query: ユーザーのクエリ
        messages: 会話履歴
    
    Returns:
        問題への回答の場合True
    """
    # 単一文字または短い回答かチェック
    query_clean = query.strip().upper()
    if query_clean not in ['A', 'B', 'C', '1', '2', '3']:
        return False
    
    # 最後のアシスタントメッセージを確認
    assistant_messages = [m for m in messages if m['role'] == 'assistant']
    if not assistant_messages:
        return False
    
    last_message = assistant_messages[-1]['content']
    
    # 選択肢パターンを検出
    # 例: "A) ...", "B) ...", "C) ..."
    choice_patterns = [
        r'[ABC]\)',  # A), B), C)
        r'[123]\)',  # 1), 2), 3)
        r'[ABC]\.', # A., B., C.
        r'\*\*[ABC]\)',  # **A)**, **B)**, **C)**
    ]
    
    import re
    for pattern in choice_patterns:
        if re.search(pattern, last_message):
            return True
    
    # 「どれが正しい」「選んで」などの問題文パターン
    quiz_keywords = ['どれが正しい', '選んで', 'どれでしょう', '次のうち', '挑戦してみて']
    for keyword in quiz_keywords:
        if keyword in last_message:
            return True
    
    return False


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
    for i, result in enumerate(vector_results):
        chunk_keywords = keyword_extractor.extract_keywords(result['text'])
        all_chunks_with_keywords.append({
            'keywords': chunk_keywords,
            'text': result['text']
        })
        
        # デバッグ: 最初のチャンクの詳細を表示
        if i == 0:
            print(f"\n   🔍 デバッグ - チャンク[1]の詳細:")
            print(f"      テキスト: {result['text'][:100]}...")
            print(f"      抽出キーワード: {chunk_keywords[:10]}")
            print(f"      クエリとの共通: {set(query_keywords) & set(chunk_keywords)}")
    
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
    
    def vector_search(self, query_embedding, top_k=5, filtered_filename=None):
        """ベクトル検索（PDF指定可能）"""
        conn = self.get_connection()
        
        try:
            if self.db_type == 'postgresql':
                cursor = conn.cursor()
                if filtered_filename:
                    cursor.execute("""
                        SELECT filename, chunk_text, embedding, page_number 
                        FROM pdf_contents
                        WHERE filename = %s
                    """, (filtered_filename,))
                else:
                    cursor.execute("""
                        SELECT filename, chunk_text, embedding, page_number 
                        FROM pdf_contents
                    """)
            elif self.db_type == 'mysql':
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                if filtered_filename:
                    cursor.execute("""
                        SELECT filename, chunk_text, embedding, page_number 
                        FROM pdf_contents
                        WHERE filename = %s
                    """, (filtered_filename,))
                else:
                    cursor.execute("""
                        SELECT filename, chunk_text, embedding, page_number 
                        FROM pdf_contents
                    """)
            else:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                if filtered_filename:
                    cursor.execute("""
                        SELECT filename, chunk_text, embedding, page_number 
                        FROM pdf_contents
                        WHERE filename = ?
                    """, (filtered_filename,))
                else:
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
- 提供された学習資料を最大限活用して回答します
- 資料から得られる情報を積極的に提供します

# 画像が提供された場合の特別対応 (★重要★)
ユーザーが画像をアップロードした場合は、以下の手順で詳細に分析して回答する:

1. **画像の内容を詳細に観察**
   - テキストが含まれる場合は全て読み取る
   - 図表、グラフ、イラストの意味を理解する
   - レイアウトや構造を把握する

2. **画像の説明を構造化して提示**
   - 【画像の説明】セクションを作成
   - 主要なポイントを箇条書きで整理
   - 具体的な内容を引用しながら説明

3. **関連知識の補足**
   - 【関連知識】セクションを作成
   - 画像に出てきた用語や概念を補足説明
   - 学習資料がある場合はその内容も活用

4. **理解度確認**
   - 画像の内容について質問があるか確認
   - 必要に応じて問題を出題

**画像解説の例**:
```
この画像は、マルチメディア検定の「アナログからデジタルへ」の分野に関する内容を示しています。

【画像の説明】
• アナログからディジタルへの移行:
  - 1970年代から民生品のメディアコンテンツや媒体はアナログからディジタルへと移行
  - 例: 音楽メディアはアナログレコードやカセットテープからCDへと進化し、その後MD、DAT、半導体メモリへと変化

• アナログ時代の課題:
  - アナログメディアは精密な取扱いと時間が必要
  - 再生中の振動、媒体の大きさ、曲の選択、データの複製には注意が必要
  - 複製を繰り返すとデータは劣化する

• ディジタル化の利点:
  - ディジタル化により、アナログ時代の不便さが解決
  - CDは耐久性に優れ、小型化による携帯性、インターネットによる不要な配信、簡便な選曲、高速な複製等、多くの利点が生まれた

【関連知識】
• デジタルとアナログの違い: ...
• マルチメディアにおけるデジタル化の重要性: ...
```

# 制約条件
- 資料に基づいた回答を心がける（資料が参考程度でもOK）
- 抽象的な質問の場合は、資料から関連する情報を整理して提示する
- 親しみやすく励ます口調(〜だよ、〜してみよう、よくできたね)
- 回答は適度な長さで分かりやすくまとめる
- 可能な限りページ番号を示す
- 検定に無関係な内容には丁寧に断る

# 対応パターン

## パターン0: 画像が提供された場合 (★最優先★)
1. 画像の内容を詳細に読み取り、構造化して説明
2. 【画像の説明】と【関連知識】のセクションに分ける
3. 箇条書きで分かりやすく整理
4. 具体的な内容を引用しながら解説
5. 理解度を確認し、必要に応じて問題を出題

## パターン1: 具体的な知識・説明を求められた場合
1. 資料の内容を基に明確に説明する
2. 具体例を1〜2個挙げる
3. ページ番号を明記する
4. 軽く「理解できたかな?」と確認

## パターン1.5: 抽象的な質問（「専門用語を教えて」など）
1. 資料から関連する重要な専門用語を2-3個選ぶ
2. それぞれを簡潔に解説する
3. 「他にも知りたいことがあれば教えてね!」と促す
4. 資料に多くの専門用語がある場合は、代表的なものを選ぶ

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
   - **正解の場合**: 
     * まず「正解!」「その通り!」と明確に褒める
     * なぜ正解なのか簡潔に解説（2-3文）
     * 「次も頑張ろう!」と励ます
   - **不正解の場合**: 
     * 「惜しい!」と励ます（否定しない）
     * 正解を明示（例: 「正解はB）だったんだ」）
     * なぜその選択肢が正解なのか簡潔に解説
     * 「もう一度チャレンジしてみる？」と提案

## パターン3.5: 不明確な問題回答（「b」のみなど）
ユーザーが単に「a」「b」「c」などと答えた場合:
1. 前の問題を参照して正誤判定
2. 質問の意図を再確認しない
3. 直接正誤と解説を提供
4. 一つ前の質問が見つかるまで遡る

## パターン4: 過去問を求められた場合
1. ユーザーの指定に基づき、過去問形式の模擬問題を出題
2. 出題形式・文体・難易度・分野構成を忠実に再現
"出題・解説ルール": {
      "出題単位": "一問ずつ行うこと。",
      "解説要件": [
        "回答や解説では必ず用語の意味や背景も説明すること。",
        "解説文字数は200文字以内。",
        "科目名を必ず明記すること。",
        "出典を必ず明記すること（例：2024年前期 マルチメディア検定ベーシック）。"
      ],
      "問題出典": {
        "使用可能ファイル": [
          "2024年前期 マルチメディア検定ベーシック問題・解答",
          "2024年後期 マルチメディア検定ベーシック問題・解答",
          "2025年前期 マルチメディア検定ベーシック問題・解答",
          "2025年後期 マルチメディア検定ベーシック問題・解答"
        ],

"モード設定": {
      "🧩 出題モード": "年度・分野を指定して過去問をランダム出題。",
      "💡 解説モード": "問題番号を指定して正答と解説を提示。",
      "📝 復習モード": "間違えた問題を再出題し、要点を強調して解説。",
      "📘 過去問モード": {
        "概要": "実際の過去問形式に準拠した模擬問題をオリジナルで生成する。",
        "出題基準": {
          "参照範囲": "2024〜2025年度のマルチメディア検定ベーシック過去問（第1問〈共通問題〉および第34〜42問）",
          "条件": [
            "出題形式・文体・難易度・分野構成を忠実に再現。",
            "出題手順": [
          "① 問題のみを表示する（ユーザーが回答するまで正解は非表示）。",
          "② ユーザーが回答（ア〜エなど）を入力したら、正誤判定と解説を提示する。"
            "問題文・数値・事例・図は必ずオリジナルにする。"
          ]
        },
        "出題構成": {
          "① 共通問題": {
            "内容": "知的財産権・著作権をテーマとする空欄補充・会話文形式・複数選択（ア〜キ）を含む小問。",
            "形式": "高校〜大学初年級レベルの理解型問題。"
          },
          "② 分野別問題": {
            "範囲": [
              "画像（画素数、ビット数、解像度、明度・彩度・色相）",
              "色の知覚（対比・同化・錯視など）",
              "音声のディジタル化（標本化・量子化・符号化）",
              "動画・圧縮・データ量",
              "ネットワーク／Web／マルチメディアの特徴",
              "情報モラル／情報リテラシ"
            ],
            "要求": "分野をバランスよく含めること。"
          }
        },
        "問題形式": {
          "構造": [
            "「以下は〜に関する問題である」から始める。",
            "小問形式（a〜d）で構成。",
            "選択肢はア〜エ（必要に応じてオ〜キ）。",
            "同一解答群から同じ記号を重複使用しない形式も採用可能。"
          ],
          "出力フォーマット": {
            "例": "――――――――――\n第◯問\n問題文\n\na．（設問）\n【解答群】\nア．\nイ．\nウ．\nエ．\n\nb．（設問）\n【解答群】\nア．\nイ．\nウ．\nエ．\n――――――――――\n【正解】\n【簡潔な解説（試験対策向け・1〜2行）】"
          }
        },
        "出題方針": {
          "レベル": "高校〜大学初年級レベル。",
          "特徴": "暗記ではなく、理解していないと解けない応用型問題。",
          "目的": "実戦形式での理解確認と出題傾向の体得。"
        }
      }
    },
    出題例は以下の通りです
    "出力例": {
      "過去問モード例": {
        "第": "1問",
        "問題文": "以下は著作権に関する会話文である。空欄に当てはまる語句を選択肢から選べ。",
        "a": {
          "設問": "A：「著作者が作品を他人に許可なく使用されないようにする権利を何という？」",
          "解答群": ["ア．特許権", "イ．著作権", "ウ．商標権", "エ．意匠権"]
        },
        "b": {
          "設問": "B：「その権利のうち、作者の人格を保護する権利を何という？」",
          "解答群": ["ア．著作権", "イ．著作財産権", "ウ．著作者人格権", "エ．複製権"]
        },
        "正解": { "a": "イ", "b": "ウ" },
        "解説": "著作権には財産権と人格権があり、人格権は作者の名誉や意図を守る権利だよ。"
      }
    }
  }
}

# 資料の活用方針
- 資料から得られる情報は積極的に活用する
- 完全一致しなくても、関連する内容があれば提示する
- 「資料に記載がありません」は、本当に全く関連情報がない場合のみ
- 資料のページ数が示されている場合は、その情報を最大限活用する

# 禁止事項
- 資料と全く無関係な創作をする
- ユーザーが理解を示したのに問題を出さない
- 間違いを責める口調
- 連続して複数の問題を出す
- 画像が提供されたのに簡単な説明で済ませる (★重要★)
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


@app.route('/api/select-pdf', methods=['POST'])
def select_pdf():
    """学習するPDFを選択"""
    try:
        data = request.json
        conversation_id = data.get('conversation_id')
        pdf_name = data.get('pdf_name', '').strip()
        
        if not pdf_name:
            return jsonify({'error': 'PDF名が必要です'}), 400
        
        # PDFが存在するか確認
        pdf_list = db.get_pdf_list()
        pdf_exists = any(pdf['filename'] == pdf_name for pdf in pdf_list)
        
        if not pdf_exists:
            return jsonify({
                'error': f'"{pdf_name}" が見つかりません',
                'available_pdfs': [pdf['filename'] for pdf in pdf_list]
            }), 404
        
        # セッションIDがない場合は新規作成
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        
        # PDFを選択
        selected_pdfs[conversation_id] = pdf_name
        
        # 会話履歴を初期化（新しい科目を選んだ場合）
        if conversation_id in conversation_history:
            conversation_history[conversation_id] = [
                {"role": "system", "content": BASE_SYSTEM_PROMPT}
            ]
        
        print(f"📚 PDF選択: {pdf_name} (Session: {conversation_id[:8]}...)")
        
        return jsonify({
            'success': True,
            'conversation_id': conversation_id,
            'selected_pdf': pdf_name,
            'message': f'"{pdf_name}" を選択しました。学習を始めましょう！'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/get-selected-pdf', methods=['POST'])
def get_selected_pdf():
    """現在選択中のPDFを取得"""
    try:
        data = request.json
        conversation_id = data.get('conversation_id')
        
        if not conversation_id:
            return jsonify({'selected_pdf': None})
        
        selected_pdf = selected_pdfs.get(conversation_id)
        
        return jsonify({
            'conversation_id': conversation_id,
            'selected_pdf': selected_pdf
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/clear-pdf-selection', methods=['POST'])
def clear_pdf_selection():
    """PDF選択をクリア（全資料から検索に戻る）"""
    try:
        data = request.json
        conversation_id = data.get('conversation_id')
        
        if conversation_id and conversation_id in selected_pdfs:
            del selected_pdfs[conversation_id]
            print(f"📚 PDF選択クリア (Session: {conversation_id[:8]}...)")
        
        return jsonify({
            'success': True,
            'message': '全ての資料から検索します'
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
        image_data = data.get('image')  # base64エンコードされた画像データ
        
        if not query_text and not image_data:
            return jsonify({'error': 'クエリまたは画像が必要です'}), 400
        
        # 会話履歴の取得
        if conversation_id and conversation_id in conversation_history:
            messages = conversation_history[conversation_id]
        else:
            conversation_id = str(uuid.uuid4())
            messages = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]
        
        # 画像データの正規化
        has_image = bool(image_data)
        if has_image:
            print(f"\n🖼️ 画像付きクエリを検出: {query_text or '(テキストなし)'}")
            
            # Base64形式を確認・修正
            if image_data.startswith('data:image'):
                # data:image/png;base64,xxxxx の形式（正しい）
                print(f"✅ 画像形式OK: {image_data[:50]}...")
            else:
                # プレフィックスがない場合は追加
                print("⚠️ 画像にdata:プレフィックスがありません。追加します。")
                # 画像タイプを判定（デフォルトはpng）
                if image_data.startswith('/9j/'):
                    image_data = f"data:image/jpeg;base64,{image_data}"
                elif image_data.startswith('iVBOR'):
                    image_data = f"data:image/png;base64,{image_data}"
                else:
                    # その他の場合はpngとして扱う
                    image_data = f"data:image/png;base64,{image_data}"
                print(f"✅ 修正後: {image_data[:50]}...")
        
        # 問題への回答かチェック（画像がない場合のみ）
        if not has_image and is_quiz_answer(query_text, messages):
            print(f"\n💡 問題への回答を検出: {query_text}")
            print("   RAG検索をスキップします")
            
            messages.append({"role": "user", "content": query_text})
            
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=2000,
                temperature=0.7
            )
            
            assistant_response = response.choices[0].message.content
            messages.append({"role": "assistant", "content": assistant_response})
            conversation_history[conversation_id] = messages
            
            stats = db.get_stats()
            
            return jsonify({
                'response': assistant_response,
                'conversation_id': conversation_id,
                'stats': stats
            })
        
        # 通常のRAG検索（画像がある場合も実行）
        print(f"\n📝 ユーザークエリ: {query_text or '(画像のみ)'}")
        
        # 選択されたPDFを取得
        selected_pdf = selected_pdfs.get(conversation_id)
        if selected_pdf:
            print(f"📚 選択中のPDF: {selected_pdf}")
        
        # クエリテキストがある場合のみRAG検索
        if query_text:
            query_embedding = create_embedding(query_text)
            results = db.vector_search(query_embedding, top_k=10, filtered_filename=selected_pdf)
            
            print(f"🔍 ベクトル検索結果: {len(results)}件")
            for i, r in enumerate(results[:5]):
                print(f"  [{i+1}] ページ{r['page']}, 類似度: {r['similarity']:.4f}")
            
            if results:
                # 会話履歴から文脈を抽出
                context = extract_context_from_history(messages, max_turns=2)
                
                # 高度版ハイブリッド検索を適用
                results = advanced_hybrid_search(query_text, results, alpha=0.7, context=context)
                results = results[:5]
                
                print(f"\n🎯 高度版ハイブリッド検索結果:")
                for i, r in enumerate(results):
                    score = r.get('hybrid_score', r['similarity'])
                    status = "✅" if score > 0.25 else "❌"
                    print(f"  [{i+1}] {status} ページ{r['page']}")
                    print(f"      ベクトル: {r['similarity']:.4f}")
                    print(f"      キーワード: {r.get('keyword_score', 0.0):.4f}")
                    print(f"      TF-IDF: {r.get('tfidf', 0.0):.4f}")
                    print(f"      統合: {score:.4f}")
                
                # 統合スコアでフィルタリング
                relevant_results = [r for r in results if r.get('hybrid_score', r['similarity']) > 0.25]
                
                if relevant_results:
                    print(f"✅ 関連性のある結果: {len(relevant_results)}件 (統合スコア>0.25)\n")
                    context_parts = []
                    for r in relevant_results:
                        context_parts.append(
                            f"【{r['filename']} - ページ{r['page']}】\n{r['text']}"
                        )
                    rag_context = "\n\n".join(context_parts)
                else:
                    print("⚠️ 関連性のある結果なし(統合スコア<0.25)\n")
                    rag_context = None
            else:
                print("⚠️ 検索結果なし\n")
                rag_context = None
        else:
            # 画像のみの場合はRAG検索をスキップ
            print("📷 画像のみのクエリ - RAG検索をスキップ")
            rag_context = None
        
        # プロンプト構築
        if has_image:
            if rag_context:
                prompt_text = f"""画像が提供されました。以下の手順で詳細に分析して回答してください:

1. **画像の内容を詳細に観察して説明する**
2. **【画像の説明】セクションを作成し、主要なポイントを箇条書きで整理する**
3. **【関連知識】セクションを作成し、画像の内容に関連する補足説明をする**

以下は学習資料からの抜粋です。画像の内容と関連があれば活用してください:

{rag_context}

{f'質問: {query_text}' if query_text else ''}

※ 画像のテキストは全て読み取り、構造化して詳細に説明してください。"""
            else:
                prompt_text = f"""画像が提供されました。以下の手順で詳細に分析して回答してください:

1. **画像の内容を詳細に観察して説明する**
2. **【画像の説明】セクションを作成し、主要なポイントを箇条書きで整理する**
3. **【関連知識】セクションを作成し、画像の内容に関連する補足説明をする**

{f'質問: {query_text}' if query_text else ''}

(注意: 資料から十分に関連する情報が見つかりませんでしたが、画像の内容を詳細に分析して説明してください)"""
        else:
            if rag_context:
                prompt_text = f"""以下は学習資料からの抜粋です。この情報を活用して回答してください:

{rag_context}

質問: {query_text}

※ 資料から得られる情報を最大限活用してください。"""
            else:
                prompt_text = f"質問: {query_text}\n\n(注意: 資料から情報が見つかりませんでした。資料に基づいて回答できない場合は、資料の登録状況を確認するよう提案してください)"
        
        # メッセージの構築
        if has_image:
            user_message = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt_text
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data,  # 既に正規化済み
                            "detail": "high"  # 高解像度で分析
                        }
                    }
                ]
            }
        else:
            user_message = {"role": "user", "content": prompt_text}
        
        messages.append(user_message)
        
        # GPT-4 APIを呼び出し
        max_tokens = 3000 if has_image else 2000
        
        print(f"🤖 GPT-4{'Vision' if has_image else ''} 呼び出し中...")
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            assistant_response = response.choices[0].message.content
            print(f"✅ GPT-4 応答: {len(assistant_response)}文字")
            
        except Exception as api_error:
            print(f"❌ OpenAI APIエラー: {api_error}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'AI応答エラー: {str(api_error)}'}), 500
        
        # 会話履歴に追加（画像データは保存しない）
        if has_image:
            # テキスト部分のみを保存
            messages[-1] = {"role": "user", "content": query_text or "画像について質問"}
        
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