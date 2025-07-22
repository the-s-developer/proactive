import sys
import os
import logging
import textwrap
import json
from datetime import datetime

# Proje kök dizinini Python path'ine ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logger_config import setup_logging
from src.database import get_db, Document, UserQuery, AnswerTemplate, Prediction, TemplatePredictionsLink
from src.vector_store import vector_store
from sqlalchemy.orm import Session

setup_logging()
logging.getLogger().setLevel(logging.WARNING) 

def write_header(file_handle, title):
    """Başlıkları dosyaya yazar."""
    header = "\n\n" + "="*70 + "\n"
    header += f"=== {title.upper()} ===\n"
    header += "="*70 + "\n"
    file_handle.write(header)

def dump_postgresql_summary(db: Session, file_handle):
    """PostgreSQL veritabanındaki tüm verileri dosyaya yazar."""
    write_header(file_handle, "PostgreSQL Veritabanı Tam Dökümü")
    
    counts = {
        "Documents": db.query(Document).count(),
        "UserQueries": db.query(UserQuery).count(),
        "AnswerTemplates": db.query(AnswerTemplate).count(),
        "Predictions": db.query(Prediction).count(),
        "Template_Predictions_Link": db.query(TemplatePredictionsLink).count()
    }
    for table, count in counts.items():
        file_handle.write(f"-> {table}: {count} kayıt\n")
    
    file_handle.write("\n\n--- Tüm Dokümanlar (Documents) ---\n")
    all_docs = db.query(Document).order_by(Document.id.asc()).all()
    if not all_docs:
        file_handle.write("Hiç doküman bulunamadı.\n")
    else:
        for doc in all_docs:
            file_handle.write(f"\n[DOCUMENT ID: {doc.id}] - URL: {doc.source_url}\n")
            file_handle.write(f"  Publication Date: {doc.publication_date}\n")
            file_handle.write("-" * 25 + " RAW MARKDOWN CONTENT START " + "-" * 25 + "\n")
            file_handle.write((doc.raw_markdown_content or "İçerik boş.") + "\n")
            file_handle.write("-" * 26 + " RAW MARKDOWN CONTENT END " + "-" * 27 + "\n")

    file_handle.write("\n\n--- Tüm Kullanıcı Sorguları (UserQueries) ---\n")
    all_queries = db.query(UserQuery).order_by(UserQuery.id.asc()).all()
    if not all_queries:
        file_handle.write("Hiç sorgu bulunamadı.\n")
    else:
        for q in all_queries:
            file_handle.write(f"\n[QUERY ID: {q.id}] - Oluşturulma: {q.created_at}\n")
            file_handle.write(f"  Sorgu Metni: {q.query_text}\n")
            if q.answer_template:
                file_handle.write(f"  Şablon Metni: {q.answer_template.template_text}\n")

    file_handle.write("\n\n--- Tüm Tahminler (Predictions) ---\n")
    all_predictions = db.query(Prediction).order_by(Prediction.id.asc()).all()
    if not all_predictions:
        file_handle.write("Hiç prediction bulunamadı.\n")
    else:
        for p in all_predictions:
            file_handle.write(f"\n[PREDICTION ID: {p.id}] - Durum: {p.status}\n")
            file_handle.write(f"  Prompt: {p.prediction_prompt}\n")
            pretty_json = json.dumps(p.predicted_value, indent=2, ensure_ascii=False)
            file_handle.write(f"  Sonuç (Value):\n{textwrap.indent(pretty_json, '    ')}\n")
            file_handle.write(f"  Kaynak Doküman ID(leri): {p.source_document_ids}\n")

def dump_chromadb_summary(file_handle):
    """ChromaDB veritabanındaki tüm verileri dosyaya yazar."""
    write_header(file_handle, "ChromaDB Veritabanı Tam Dökümü")

    try:
        # Document Collection
        doc_count = vector_store.document_collection.count()
        file_handle.write(f"-> 'documents' koleksiyonunda {doc_count} adet vektör (chunk) bulunuyor.\n")
        if doc_count > 0:
            file_handle.write("\n--- Tüm Vektörler (Chunks) ---\n")
            all_items = vector_store.document_collection.get()
            ids, metadatas = all_items.get('ids', []), all_items.get('metadatas', [])
            combined_data = sorted(zip(ids, metadatas), key=lambda x: x[0])
            for item_id, metadata in combined_data:
                file_handle.write(f"\n[CHUNK ID: {item_id}]\n")
                file_handle.write(f"  - Document ID: {metadata.get('document_id', 'N/A')}\n")
                file_handle.write(f"  - Text (Enriched Content): {metadata.get('text', '')}\n")

        # === EKLENEN KISIM ===
        # Prediction Collection
        pred_count = vector_store.prediction_collection.count()
        file_handle.write(f"\n-> 'predictions' koleksiyonunda {pred_count} adet vektör (prompt) bulunuyor.\n")
        if pred_count > 0:
            file_handle.write("\n--- Tüm Prediction Vektörleri (Prompts) ---\n")
            all_items = vector_store.prediction_collection.get()
            ids, metadatas = all_items.get('ids', []), all_items.get('metadatas', [])
            combined_data = sorted(zip(ids, metadatas), key=lambda x: int(x[0])) # ID'leri sayısal sırala
            for item_id, metadata in combined_data:
                file_handle.write(f"\n[PREDICTION ID: {item_id}]\n")
                file_handle.write(f"  - Prompt: {metadata.get('prompt', 'N/A')}\n")
        # === EKLENEN KISIM BİTİŞİ ===

    except Exception as e:
        file_handle.write(f"ChromaDB'den veri alınırken bir hata oluştu: {e}\n")

if __name__ == "__main__":
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_filename = f"database_full_dump_{timestamp}.txt"
    
    print(f"Veritabanlarının tam dökümü '{output_filename}' dosyasına kaydediliyor...")
    
    db_session = next(get_db())
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(f"Veritabanı Tam Döküm Raporu - {timestamp}\n")
            dump_postgresql_summary(db_session, f)
            dump_chromadb_summary(f)
            f.write("\n" + "="*70 + "\n")
            f.write("Döküm tamamlandı.\n")
    finally:
        db_session.close()

    print(f"Rapor başarıyla oluşturuldu: {output_filename}")