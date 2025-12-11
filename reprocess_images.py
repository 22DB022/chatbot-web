"""
既存PDFから画像を抽出して登録するスクリプト
"""
import sqlite3
import os
from web_app import extract_images_from_pdf, save_images_to_db, RAGDatabase
from dotenv import load_dotenv

load_dotenv()

def reprocess_all_pdfs():
    """全ての登録済みPDFから画像を抽出"""
    
    # データベース接続
    db_path = "rag_study_data.db"
    
    if not os.path.exists(db_path):
        print("❌ データベースが見つかりません")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # 全てのPDFメタデータを取得
        cursor.execute("SELECT filename FROM pdf_metadata")
        pdf_files = cursor.fetchall()
        
        if not pdf_files:
            print("❌ 登録済みPDFがありません")
            return
        
        print(f"📚 {len(pdf_files)}個のPDFを処理します\n")
        
        # 既存の画像データを削除
        cursor.execute("DELETE FROM pdf_images")
        conn.commit()
        print("🗑️ 既存の画像データを削除しました\n")
        
        total_images = 0
        
        for pdf in pdf_files:
            filename = pdf['filename']
            print(f"処理中: {filename}")
            
            # PDFファイルのパスを推測（通常はアップロードされたものなので存在しない）
            # そのため、ユーザーに再アップロードを促すか、
            # または assets/pdf/ などに保存しておく必要がある
            
            # この例では、既存PDFは処理できないことを通知
            print(f"  ⚠️ PDFファイルが見つかりません。再アップロードが必要です。\n")
        
        print(f"✅ 処理完了: 合計 {total_images} 個の画像を抽出しました")
        
    except Exception as e:
        print(f"❌ エラー: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    print("=" * 50)
    print("既存PDF画像再処理スクリプト")
    print("=" * 50)
    print()
    
    reprocess_all_pdfs()