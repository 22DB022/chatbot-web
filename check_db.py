import sqlite3

conn = sqlite3.connect('rag_study_data.db')
cursor = conn.cursor()

# テーブル一覧
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()
print('📊 テーブル一覧:', tables)

# PDF数
cursor.execute('SELECT COUNT(*) FROM pdf_metadata')
pdf_count = cursor.fetchone()[0]
print(f'📄 PDF数: {pdf_count}')

# チャンク数
cursor.execute('SELECT COUNT(*) FROM pdf_contents')
chunk_count = cursor.fetchone()[0]
print(f'📝 チャンク数: {chunk_count}')

# サンプルデータ
cursor.execute('SELECT filename, page_count FROM pdf_metadata LIMIT 3')
samples = cursor.fetchall()
print(f'📚 サンプルPDF:')
for filename, page_count in samples:
    print(f'  - {filename} ({page_count}ページ)')

conn.close()
print('\n✅ データ確認完了！')
