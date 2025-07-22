import sys
import os
import time
import logging
import json
from datetime import datetime, timezone

script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, '..'))
sys.path.append(project_root)

from src.logger_config import setup_logging
from src.database import get_db, Document, Prediction, UserQuery, TemplatePredictionsLink 
from src.core_logic import handle_new_document, handle_new_query, update_user_query_subscription, get_cosine_similarity 
from scripts.reset_database import reset_databases 
from sqlalchemy.orm import joinedload 

setup_logging()
logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO) 

THRESHOLD=0.97
def _are_embeddings_semantically_similar(text1: str, text2: str) -> bool:
    if not text1 or not text2:
        return text1 == text2
    score = get_cosine_similarity(text1, text2)
    logger.debug(f"Semantic similarity score: {score:.4f}, Threshold: {0.97}")
    return score >= THRESHOLD

def run_test_scenario():
    test_results = []
    initial_user_query_obj = None 
    initial_prediction_id = None
    initial_prediction_content_base = None
    base_language = "en"  # Varsayılan, ilk Prediction'ın dilini aşağıda güncelleyeceğiz.

    print("\n" + "="*80)
    print("                 REAKTİF RAG SİSTEMİ TEST SCENARIOS")
    print("="*80 + "\n")

    # Adım 1: Veritabanlarını Sıfırla
    print("[ADIM 1/6] Veritabanları sıfırlanıyor...")
    try:
        reset_databases()
        print("✅ Veritabanları sıfırlandı.\n")
        test_results.append("Adım 1: Veritabanı Sıfırlama -> BAŞARILI ✅")
    except Exception as e:
        print(f"❌ Adım 1 HATA: Veritabanı sıfırlanırken hata oluştu: {e}")
        test_results.append("Adım 1: Veritabanı Sıfırlama -> BAŞARISIZ ❌")
        return 

    # Adım 2: İlk Dokümanı İçeri Aktar
    print("[ADIM 2/6] İlk temel doküman içeri aktarılıyor (İmar Hakkı)...")
    doc_path_1 = os.path.join(project_root, 'documents', 'bloomberght_com_5-soruda-imar-hakki-aktarimi-3737049.md')
    if not os.path.exists(doc_path_1):
        print(f"❌ HATA: Doküman bulunamadı: {doc_path_1}. Lütfen 'documents' klasörünü kontrol edin.")
        test_results.append("Adım 2: Doküman Aktarımı -> BAŞARISIZ ❌ (Dosya Yok)")
        return
    try:
        handle_new_document(file_path=doc_path_1)
        print(f"✅ Doküman aktarıldı: {os.path.basename(doc_path_1)}\n")
        test_results.append("Adım 2: Doküman Aktarımı -> BAŞARILI ✅")
    except Exception as e:
        print(f"❌ Adım 2 HATA: Doküman aktarılırken hata oluştu: {e}")
        test_results.append("Adım 2: Doküman Aktarımı -> BAŞARISIZ ❌")
        return

    time.sleep(1) 

    # Adım 3: Kullanıcı Sorgusu Oluştur (Prediction tetiklenecek)
    print("[ADIM 3/6] Yeni kullanıcı sorgusu işleniyor (Prediction oluşturulacak)...")
    query_text_1 = "İmar hakkı aktarımı nedir ve vatandaş ne kazanır?"
    query_id_1 = None 
    try:
        query_id_1 = handle_new_query(query_text=query_text_1)

        if query_id_1:
            print(f"✅ Sorgu '{query_text_1}' başarıyla işlendi. ID: {query_id_1}")
            db = next(get_db())
            try:
                initial_user_query_obj = db.query(UserQuery).options(joinedload(UserQuery.predictions).joinedload(TemplatePredictionsLink.prediction)).filter(UserQuery.id == query_id_1).first()
                if initial_user_query_obj and initial_user_query_obj.predictions:
                    prediction_obj = initial_user_query_obj.predictions[0].prediction
                    base_language = getattr(prediction_obj, "base_language_code", "en")
                    initial_prediction_id = prediction_obj.id
                    initial_prediction_content_base = prediction_obj.predicted_value.get("content", {}).get(base_language)
                else:
                    print("❌ HATA: Oluşturulan sorguya bağlı Prediction bulunamadı veya yüklenemedi.")
                    test_results.append("Adım 3: Sorgu ve Prediction Oluşturma -> BAŞARISIZ ❌ (Prediction Yok)")
                    return

                print(f"\n[NİHAİ CEVAP (Sorgu ID: {query_id_1}) - İlk Hali]\n{initial_user_query_obj.final_answer}\n")
                print("---")
                print("Cevap Planı (JSON):\n")
                print(json.dumps(initial_user_query_obj.answer_template_text, indent=2, ensure_ascii=False)) 
                print("---\n")
            finally:
                db.close()
            test_results.append("Adım 3: Sorgu ve Prediction Oluşturma -> BAŞARILI ✅")
        else:
            print(f"❌ Adım 3 HATA: Sorgu '{query_text_1}' işlenirken hata oluştu.")
            test_results.append("Adım 3: Sorgu ve Prediction Oluşturma -> BAŞARISIZ ❌")
            return
    except Exception as e:
        print(f"❌ Adım 3 HATA: Beklenmedik hata oluştu: {e}")
        test_results.append("Adım 3: Sorgu ve Prediction Oluşturma -> BAŞARISIZ ❌")
        return

    time.sleep(2) 

    # Adım 4: Prediction'ı Güncellemeyecek Doküman
    print("[ADIM 4/6] Prediction'ı güncellememesi beklenen bir doküman içeri aktarılıyor...")
    doc_not_significant_content = """---
url: https://www.bloomberght.com/imar-hakki-aktarimi-az-farkli-detay-3737052
depth: 2
pub_date: '2025-07-21'
title: "İmar Hakkı Transferinde Benzer Güncellemeler" 
summary: "İmar hakkı transferi ile ilgili küçük yasal düzenleme detayları ve bu düzenlemelerin vatandaşlar için getirdiği minör iyileştirmeler." 
keywords:
- imar hakkı transferi
- yasal güncelleme
- vatandaş faydası
entities:
- value: Çevre ve Şehircilik Bakanlığı
  type: ORGANIZATION
  label: author
---
# İmar Hakkı Transferinde Benzer Güncellemeler
İmar hakkı aktarımına dair kanuni değişiklikler, sürecin daha esnek işlemesini sağlayacak cüzi ayarlamalar içeriyor. Bu sistem, mülk sahiplerinin değerlerini koruması için kritik bir araç olmaya devam ediyor.
"""
    doc_path_not_significant = os.path.join(project_root, 'documents', 'test_imar_hakki_not_significant.md')
    with open(doc_path_not_significant, 'w', encoding='utf-8') as f:
        f.write(doc_not_significant_content)
    
    print(f"  Aktarılan Doküman: {os.path.basename(doc_path_not_significant)}")
    try:
        handle_new_document(file_path=doc_path_not_significant)
        
        db = next(get_db())
        prediction_after_ns = db.query(Prediction).filter(Prediction.id == initial_prediction_id).first() 
        db.close() 

        if initial_prediction_content_base and prediction_after_ns and prediction_after_ns.predicted_value:
            new_content_base_ns = prediction_after_ns.predicted_value.get("content", {}).get(base_language, "")
            similarity_score_ns = get_cosine_similarity(json.dumps(initial_prediction_content_base), json.dumps(new_content_base_ns))
            
            print(f"  --- Debug Sim Puanı (Önemsiz Doküman) ---")
            print(f"  Eski Prediction {base_language.upper()} içeriği ilk: {json.dumps(initial_prediction_content_base, indent=2, ensure_ascii=False)}")
            print(f"  Yeni Prediction {base_language.upper()} içeriği: {json.dumps(new_content_base_ns, indent=2, ensure_ascii=False)}")
            print(f"  Semantik Benzerlik Skoru (eski vs yeni): {similarity_score_ns:.4f} (Eşik: {THRESHOLD} - core_logic.py'de ayarlı)")
            print(f"  -------------------------------------------")

            if _are_embeddings_semantically_similar(json.dumps(initial_prediction_content_base), json.dumps(new_content_base_ns)):
                 print("  ✅ Doğrulama: Prediction içeriği anlamsal olarak değişmedi. (BEKLENEN DAVRANIŞ)")
                 test_results.append("Adım 4: Önemsiz Güncelleme -> BAŞARILI ✅ (Güncellenmedi)")
            else:
                 print("  ❌ Doğrulama: Prediction içeriği anlamsal olarak BEKLENMEDİK şekilde değişti.")
                 test_results.append("Adım 4: Önemsiz Güncelleme -> BAŞARISIZ ❌ (Beklenmedik Güncelleme)")
        else:
            print("  ❌ Doğrulama: Prediction ID bulunamadı veya içeriği boş.")
            test_results.append("Adım 4: Önemsiz Güncelleme -> BAŞARISIZ ❌ (Prediction Yok/Boş)")
        
        print("\n")
    except Exception as e:
        print(f"❌ Adım 4 HATA: Doküman aktarılırken hata oluştu: {e}")
        test_results.append("Adım 4: Önemsiz Güncelleme -> BAŞARISIZ ❌ (Doküman Aktarımı)")
        return
    
    time.sleep(2) 

    # Adım 5: Prediction'ı Güncelleyecek Doküman
    print("[ADIM 5/6] Prediction'ı GÜNCELLEMESİ beklenen bir doküman içeri aktarılıyor...")
    doc_significant_content = """---
url: https://www.bloomberght.com/imar-hakki-aktarimi-buyuk-fark-3737053
depth: 2
pub_date: '2025-07-22'
title: "**İmar Hakkı Aktarımında DEVRİMCİ YENİLİKLER**" 
summary: "**İmar hakkı aktarımı artık sadece kısıtlı alanlar için değil, kentsel dönüşüm bölgelerinde de aktif olarak kullanılacak.** Bu durum, sistemin kapsamını ve vatandaş faydasını **radikal biçimde artırıyor**. Kamulaştırma mağduriyetlerini doğrudan ortadan kaldırıyor ve yeni gayrimenkul fırsatları yaratıyor."
keywords:
- imar hakkı aktarımı
- kentsel dönüşüm
- devrimci
- radikal değişiklik
- kamulaştırma mağduriyeti
- yeni fırsatlar
entities:
- value: Çevre ve Şehircilik Bakanlığı
  type: ORGANIZATION
  label: author
---
# İmar Hakkı Aktarımında DEVRİMCİ YENİLİKLER
Yeni çıkan yasa ile imar hakkı aktarımının uygulama alanı genişletildi. Eskiden sadece koruma alanları ve kamulaştırılamayan parsellerle sınırlıyken, **artık kentsel dönüşüm projelerinde de imar hakkı aktarımı bir araç olarak kullanılabilecek.** Bu, milyonlarca vatandaşı doğrudan etkileyecek ve şehir planlamasında yepyeni bir sayfa açacak. Özellikle eski binaların yenilenmesi süreçlerinde hak sahiplerine büyük esneklik sağlayacak. **Bu devrim niteliğindeki değişiklik, özellikle kamulaştırma süreçlerinde yaşanan uzun bekleyişleri ve mağduriyetleri tamamen ortadan kaldırarak vatandaşlara anında ve adil bir çözüm sunmaktadır.** Ayrıca, **şehir merkezlerindeki yoğunluğu azaltarak daha yaşanabilir kentsel alanlar oluşturulmasına da katkı sağlayacaktır.**
"""
    doc_path_significant = os.path.join(project_root, 'documents', 'test_imar_hakki_significant.md')
    with open(doc_path_significant, 'w', encoding='utf-8') as f:
        f.write(doc_significant_content)
    
    print(f"  Aktarılan Doküman: {os.path.basename(doc_path_significant)}")
    try:
        handle_new_document(file_path=doc_path_significant)
        
        db = next(get_db())
        current_prediction_after_s = db.query(Prediction).filter(Prediction.id == initial_prediction_id).first()
        db.close()

        if initial_prediction_content_base and current_prediction_after_s and current_prediction_after_s.predicted_value:
            new_content_base_s = current_prediction_after_s.predicted_value.get("content", {}).get(base_language, "")
            similarity_score_s = get_cosine_similarity(json.dumps(initial_prediction_content_base), json.dumps(new_content_base_s))
            
            print(f"  --- Debug Sim Puanı (Önemli Doküman - Güncelleme Sonrası) ---")
            print(f"  Eski Prediction {base_language.upper()} içeriği ilk: {json.dumps(initial_prediction_content_base, indent=2, ensure_ascii=False)}")
            print(f"  Yeni Prediction {base_language.upper()} içeriği: {json.dumps(new_content_base_s, indent=2, ensure_ascii=False)}")
            print(f"  Semantik Benzerlik Skoru (eski ilk hali vs yeni): {similarity_score_s:.4f} (Eşik: {THRESHOLD} - core_logic.py'de ayarlı)")
            print(f"  -------------------------------------------")

            if not _are_embeddings_semantically_similar(json.dumps(initial_prediction_content_base), json.dumps(new_content_base_s)):
                print("  ✅ Doğrulama: Prediction içeriği anlamsal olarak DEĞİŞTİ. (BEKLENEN DAVRANIŞ)")
                test_results.append("Adım 5: Önemli Güncelleme -> BAŞARILI ✅ (Güncellendi)")
            else:
                print("  ❌ Doğrulama: Prediction içeriği BEKLENMEDİK şekilde değişmedi veya yeterince anlamlı değil.")
                test_results.append("Adım 5: Önemli Güncelleme -> BAŞARISIZ ❌ (Beklenmedik Güncellenmeme)")
        else:
            print("  ❌ Doğrulama: Prediction ID bulunamadı veya içeriği boş.")
            test_results.append("Adım 5: Önemli Güncelleme -> BAŞARISIZ ❌ (Prediction Yok/Boş)")

        print("\n")
    except Exception as e:
        print(f"❌ Adım 5 HATA: Doküman aktarılırken hata oluştu: {e}")
        test_results.append("Adım 5: Önemli Güncelleme -> BAŞARISIZ ❌ (Doküman Aktarımı)")
        return

    time.sleep(2)

    # Adım 6: Güncellenen Cevabı Kontrol Et
    print(f"[ADIM 6/6] Sorgu ID {query_id_1}'in cevabı GÜNCELLEMEYİ yansıttı mı kontrol ediliyor...")
    db_final = next(get_db())
    try:
        user_query_final_state = db_final.query(UserQuery).filter(UserQuery.id == query_id_1).first()
        print(f"initial query {initial_user_query_obj.final_answer}")
        print(f"final query {user_query_final_state.final_answer}")

        if user_query_final_state and user_query_final_state.final_answer != initial_user_query_obj.final_answer: 
            print(f"✅ Sorgu ID {query_id_1}'in cevabı başarıyla GÜNCEL HALİNE GELDİ (reaktif!).")
            print(f"  Son Güncelleme Zamanı: {user_query_final_state.answer_last_updated}")
            print(f"\n[GÜNCEL NİHAİ CEVAP (Sorgu ID: {query_id_1})]\n{user_query_final_state.final_answer}\n")
            test_results.append("Adım 6: Nihai Cevap Güncellendi mi -> BAŞARILI ✅")
        else:
            print(f"ℹ️ Sorgu ID {query_id_1}'in cevabı değişmedi veya güncellenmedi.")
            print(f"   (Bunun nedeni: Önceki adımda Prediction güncellenmediyse veya anlamsal fark cevabı değiştirmeye yetmediyse).")
            test_results.append("Adım 6: Nihai Cevap Güncellendi mi -> BAŞARISIZ ❌ (Değişmedi)")
    except Exception as e:
        print(f"❌ Adım 6 HATA: Nihai cevap kontrol edilirken hata oluştu: {e}")
        test_results.append("Adım 6: Nihai Cevap Güncellendi mi -> BAŞARISIZ ❌")
    finally:
        db_final.close()

    print("\n" + "="*80)
    print("                TEST SCENARIOS TAMAMLANDI")
    print("="*80 + "\n")

    # --- TEST ÖZETİ BÖLÜMÜ ---
    print("\n" + "="*80)
    print("                     TEST ÖZETİ")
    print("="*80)
    for result in test_results:
        print(result)
    print("="*80 + "\n")

if __name__ == "__main__":
    run_test_scenario()
