#!/usr/bin/env python

import sys
import os
import logging
import argparse 
from rich.console import Console
from rich.table import Table
from rich.progress import track
from rich import box

# Ensure frontmatter is imported at the top-level
import frontmatter 

# Project root for imports
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, '..'))
sys.path.append(project_root)

from src.logger_config import setup_logging
from src.database import get_db, Prediction, Document
from src.vector_store import vector_store
from src.processing import calculate_keyword_set_similarity, get_cosine_similarity 
import json

# --- KONFİGÜRASYON ---
TOP_N_TO_DISPLAY_GLOBAL = 25 
HIGH_MATCH_THRESHOLD = 0.7  
KEYWORD_SIMILARITY_THRESHOLD = 0.7 
CANDIDATES_PER_ITEM = 10 

TOP_RELEVANT_PREDICTIONS_PER_DOC = 5 
# ---

console = Console()

def analyze_pred_to_doc():
    """
    ANALİZ 1: Prediction -> Doküman
    Her bir Prediction için dokümanlar arasında en iyi anlamsal eşleşmeleri bulur.
    SORU: "Prediction'larım için yeterli ve doğru bağlam (context) var mı?"
    """
    db = next(get_db())
    console.rule("[bold blue]ANALİZ: Prediction'dan Dokümana Eşleşmeler[/bold blue]")
    
    all_predictions = db.query(Prediction).all()
    if not all_predictions:
        console.print("[bold red]Analiz için veritabanında Prediction bulunamadı.[/bold red]")
        db.close()
        return

    all_matches = []
    for pred in track(all_predictions, description="[green]Prediction'lar işleniyor..."):
        # query_document_metas, hem summary hem de keywords alanlarından sonuç döndürüyor.
        # Bu fonksiyonun kendisi zaten hedeflenmiş hibrit aramayı yapıyor.
        results = vector_store.query_document_metas(
            query_text=pred.prediction_prompt,
            query_keywords=pred.keywords or [], 
            n_results=CANDIDATES_PER_ITEM
        )
        
        for hit in results:
            all_matches.append({
                "score": hit['distance'], # Mesafe (distance), düşük değer daha iyi
                "source_id": pred.id,
                "source_text": pred.prediction_prompt,
                "target_id": hit['document_id'],
                "target_meta_type": hit['type'], # Hangi metadata tipiyle eşleştiği ('summary' veya 'keywords')
                "target_meta_text": hit['text'] # Eşleşen metin içeriği (özet veya anahtar kelime)
            })

    # Skorlar (distance) için sıralama, düşük mesafenin (0'a yakın) daha iyi olduğunu unutmayın.
    sorted_matches = sorted(all_matches, key=lambda x: x['score']) 
    console.print(f"\n✅ Toplam [bold green]{len(sorted_matches)}[/bold green] potansiyel eşleşme bulundu.")
    
    table = Table(title=f"✨ En İyi {TOP_N_TO_DISPLAY_GLOBAL} Anlamsal Eşleşme (Prediction -> Doküman)", box=box.MINIMAL_HEAVY_HEAD, header_style="bold magenta")
    table.add_column("Rank", justify="center")
    table.add_column("Distance\n(lower is better)", style="bold", justify="right")
    table.add_column("Kaynak Prediction\n(ID & Prompt)", max_width=30, style="cyan") 
    table.add_column("Hedef Doküman Meta\n(ID, Tip & Metin)", max_width=65, style="green") 
    

    for i, item in enumerate(sorted_matches[:TOP_N_TO_DISPLAY_GLOBAL]):
        score = item['score']
        # Distance (mesafe) olduğu için, eşik kontrolünü tersine çeviriyoruz (küçük değerler iyi)
        # Örneğin, 0.7 benzerlik -> 0.3 mesafe civarı
        score_style = "bold green" if score < (1 - HIGH_MATCH_THRESHOLD) else "white" 
        rank_display = f"⭐ {i + 1}" if score < (1 - HIGH_MATCH_THRESHOLD) else str(i + 1)
        
        source_display_text = f"[dim]#{item['source_id']}[/dim] {item['source_text']}"
        
        target_display_text = (
            f"[dim]#{item['target_id']}[/dim] "
            f"([bold red]{item['target_meta_type']}[/bold red])\n" 
            f"{item['target_meta_text']}" 
        )

        table.add_row(
            rank_display,
            f"[{score_style}]{score:.4f}[/{score_style}]",
            (source_display_text[:28] + '..') if len(source_display_text) > 30 else source_display_text,
            (target_display_text[:63] + '..') if len(target_display_text) > 65 else target_display_text,
        )
    console.print(table)
    db.close()

def analyze_doc_to_pred():
    """
    ANALİZ 2: Doküman -> Prediction
    Her bir Doküman için Prediction'lar arasında en iyi anlamsal eşleşmeleri bulur.
    (Doküman özeti/anahtar kelimeleri ile Prediction prompt/anahtar kelimelerinin ortalama skoruna göre)
    """
    db = next(get_db())
    console.rule("[bold blue]ANALİZ: Dokümandan Prediction'a Eşleşmeler[/bold blue]")
    
    all_docs = db.query(Document).all()
    all_predictions = db.query(Prediction).all()

    if not all_docs:
        console.print("[bold red]Analiz için veritabanında Document bulunamadı.[/bold red]")
        db.close()
        return
    if not all_predictions:
        console.print("[bold red]Analiz için veritabanında Prediction bulunamadı.[/bold red]")
        db.close()
        return

    def get_doc_metadata_for_display_and_query(doc_obj):
        title_display = ""
        summary_display = ""
        summary_for_query = ""
        keywords_for_query = []
        content_snippet = "" # New: to show content if metadata is missing

        try:
            post = frontmatter.loads(doc_obj.raw_markdown_content or "")
            title_display = post.metadata.get('title', 'Başlık Yok')
            summary_display = post.metadata.get('summary', 'Özet Yok')
            summary_for_query = post.metadata.get('summary', '') 
            keywords_for_query = [str(k) for k in post.metadata.get('keywords', [])]
            
            # If title or summary is 'Yok', try to show content snippet
            if title_display == 'Başlık Yok' or summary_display == 'Özet Yok':
                # Take first 100-200 chars of content for display
                content_snippet = (post.content or "")[:200] + ("..." if len(post.content or "") > 200 else "")
                if not content_snippet:
                    content_snippet = "[İçerik de boş]"

        except Exception as e:
            logging.warning(f"Error loading metadata for doc {doc_obj.id}: {e}")
            title_display = f"Hata ({doc_obj.id})"
            summary_display = f"Özet yüklenemedi: {e}"
            content_snippet = "[Metadata yüklenemedi, içerik de gösterilemiyor]" # Fallback if error parsing frontmatter

        return title_display, summary_display, summary_for_query, keywords_for_query, content_snippet


    all_docs.sort(key=lambda doc: get_doc_metadata_for_display_and_query(doc)[0].lower()) # Sort by extracted title

    for doc in track(all_docs, description="[green]Dokümanlar işleniyor..."):
        doc_title_display, doc_summary_display, doc_summary_for_query, doc_keywords_for_query, content_snippet = \
            get_doc_metadata_for_display_and_query(doc)

        console.print(f"\n[bold yellow]Doküman ID: {doc.id}[/bold yellow]")
        console.print(f"  Başlık: \"[italic]{doc_title_display}[/italic]\"")
        console.print(f"  Özet: \"[dim]{doc_summary_display}[/dim]\"")
        
        # Display content snippet if metadata was missing or errored
        if doc_title_display == 'Başlık Yok' or doc_summary_display == 'Özet Yok' or \
           "Hata" in doc_title_display or "yüklenemedi" in doc_summary_display:
            console.print(f"  [bold red]İçerik Snippet (Başlık/Özet Yok/Hata):[/bold red] \"[dim]{content_snippet}[/dim]\"")


        prediction_relevance_scores = []
        for pred in all_predictions:
            prompt_summary_similarity = get_cosine_similarity(pred.prediction_prompt, doc_summary_for_query)
            
            keyword_match_score_avg = calculate_keyword_set_similarity(
                pred.keywords or [], 
                doc_keywords_for_query, 
                similarity_threshold=KEYWORD_SIMILARITY_THRESHOLD
            )

            combined_score = (prompt_summary_similarity * 0.7) + (keyword_match_score_avg * 0.3)
            
            prediction_relevance_scores.append({
                "prediction_id": pred.id,
                "prediction_prompt": pred.prediction_prompt,
                "prediction_keywords": pred.keywords,
                "prompt_summary_similarity": prompt_summary_similarity,
                "keyword_match_score_avg": keyword_match_score_avg,
                "combined_score": combined_score
            })
        
        prediction_relevance_scores.sort(key=lambda x: x["combined_score"], reverse=True)

        if not prediction_relevance_scores:
            console.print("  [dim]Bu dokümanla ilgili skorlanmış Prediction bulunamadı.[/dim]")
            continue

        nested_table = Table(title=f"  [bold blue]En Alakalı {TOP_RELEVANT_PREDICTIONS_PER_DOC} Prediction[/bold blue]", box=box.MINIMAL_HEAVY_HEAD, header_style="bold green")
        nested_table.add_column("Rank", justify="center")
        nested_table.add_column("Combined Score\n(higher is better)", style="bold", justify="right")
        nested_table.add_column("Prediction ID & Prompt", max_width=40, style="white")
        nested_table.add_column("Prompt-Summary Sim", justify="right")
        nested_table.add_column("Keyword Match Avg", justify="right")
        
        for i, item in enumerate(prediction_relevance_scores[:TOP_RELEVANT_PREDICTIONS_PER_DOC]):
            combined_score_val = item['combined_score']
            score_style = "bold green" if combined_score_val >= HIGH_MATCH_THRESHOLD else "white" 
            rank_display = f"⭐ {i + 1}" if combined_score_val >= HIGH_MATCH_THRESHOLD else str(i + 1)
            
            pred_info = f"[dim]#{item['prediction_id']}[/dim] {item['prediction_prompt']}"
            
            nested_table.add_row(
                rank_display,
                f"[{score_style}]{combined_score_val:.4f}[/{score_style}]",
                (pred_info[:38] + '..') if len(pred_info) > 40 else pred_info,
                f"{item['prompt_summary_similarity']:.4f}",
                f"{item['keyword_match_score_avg']:.4f}"
            )
        console.print(nested_table)
    
    db.close()


def analyze_pred_to_pred():
    """
    ANALİZ 3: Prediction -> Prediction
    Her bir Prediction için diğer Prediction'lar arasında en iyi anlamsal eşleşmeleri bulur.
    Bu versiyon, her bir prediction'ın altında ona en benzer N prediction'ı listeler.
    """
    db = next(get_db())
    console.rule("[bold blue]ANALİZ: Prediction'lar Arası Benzerlik (Kopya Tespiti)[/bold blue]")
    
    all_predictions = db.query(Prediction).all()
    if len(all_predictions) < 2:
        console.print("[bold red]Analiz için en az 2 Prediction gereklidir.[/bold red]")
        db.close()
        return

    TOP_SIMILAR_PREDS = 5 

    for pred_a in track(all_predictions, description="[green]Prediction'lar işleniyor..."):
        console.print(f"\n[bold yellow]Prediction ID: {pred_a.id}[/bold yellow]")
        console.print(f"  Prompt: \"[italic]{pred_a.prediction_prompt}[/italic]\"")
        console.print(f"  Keywords: {pred_a.keywords or 'Yok'}")

        results = vector_store.query_prediction_metas(
            query_text=pred_a.prediction_prompt, # Prompt ile diğer prediction prompt/keyword'lerini ara
            n_results=TOP_SIMILAR_PREDS + 1 
        )
        
        similar_preds = [
            hit for hit in results 
            if hit['prediction_id'] != pred_a.id
        ]
        
        if not similar_preds:
            console.print("  [dim]Benzer başka Prediction bulunamadı.[/dim]")
            continue

        nested_table = Table(title=f"  [bold blue]En Benzer {TOP_SIMILAR_PREDS} Prediction[/bold blue]", box=box.MINIMAL_HEAVY_HEAD, header_style="bold green")
        nested_table.add_column("Rank", justify="center")
        nested_table.add_column("Distance\n(lower is better)", style="bold", justify="right")
        nested_table.add_column("Benzer Prediction (ID & Metin)", max_width=60, style="white")

        for i, item in enumerate(similar_preds[:TOP_SIMILAR_PREDS]):
            score = item['distance']
            score_style = "bold green" if score < (1 - HIGH_MATCH_THRESHOLD) else "white" 
            rank_display = f"⭐ {i + 1}" if score < (1 - HIGH_MATCH_THRESHOLD) else str(i + 1)
            
            target_text = f"[dim]#{item['prediction_id']}[/dim] ({item['type']}) {item['text']}"
            
            nested_table.add_row(
                rank_display,
                f"[{score_style}]{score:.4f}[/{score_style}]",
                (target_text[:58] + '..') if len(target_text) > 60 else target_text,
            )
        console.print(nested_table)
    
    db.close()


def main():
    """Ana fonksiyon, argümanları işler ve ilgili analiz fonksiyonunu çağırır."""
    parser = argparse.ArgumentParser(
        description="Vektör veritabanı üzerinde anlamsal analizler çalıştırır.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "analysis_type",
        choices=["pred-to-doc", "doc-to-pred", "pred-to-pred"],
        help="""Çalıştırılacak analiz türü:
- pred-to-doc:  Her bir Prediction için en alakalı dokümanları bulur.
- doc-to-pred:  Her bir doküman için en alakalı Prediction'ları bulur.
- pred-to-pred: Birbirine en çok benzeyen Prediction çiftlerini bulur."""
    )
    args = parser.parse_args()

    if args.analysis_type == "pred-to-doc":
        analyze_pred_to_doc()
    elif args.analysis_type == "doc-to-pred":
        analyze_doc_to_pred()
    elif args.analysis_type == "pred-to-pred":
        analyze_pred_to_pred()

if __name__ == "__main__":
    setup_logging()
    logging.getLogger().setLevel(logging.WARNING) 
    main()