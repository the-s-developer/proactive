import json
import logging
from typing import Any, Dict, List

# Gerçek projede bu objeler veritabanı modellerinizden (SQLAlchemy) gelir.
# Test için `SimpleNamespace` kullanarak sahte (mock) objeler yaratıyoruz.
from types import SimpleNamespace

# --- GEREKLİ YARDIMCI OBJELERİN SAHTELERİNİ (MOCK) OLUŞTURMA ---

# Fonksiyon içinde çağrılan `llm_gateway` için sahte bir obje
# Test verimiz zaten Türkçe olduğu için `translate_value` hiç çağrılmayacak.
llm_gateway = SimpleNamespace(
    translate_value=lambda *args, **kwargs: {"error": "translation_failed"}
)

# Fonksiyonun içindeki `logger` çağrılarının hata vermemesi için temel bir logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- TEST EDİLECEK FONKSİYON ---
# src/core_logic.py dosyasındaki fonksiyonun son ve düzeltilmiş halini buraya kopyalıyoruz.
# Böylece script başka hiçbir dosyaya ihtiyaç duymaz.

def _assemble_final_answer(db: Any, user_query: Any) -> str:
    """
    LLM'den gelen yapısal "render planını" ve prediction verilerini işleyerek
    nihai, kullanıcı dostu metni oluşturur.
    """
    try:
        if isinstance(user_query.answer_template_text, str):
            render_plan = json.loads(user_query.answer_template_text)
        else:
            render_plan = user_query.answer_template_text
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode render plan for UserQuery ID {user_query.id}: {e}", exc_info=True)
        return "[**Cevap planı ayrıştırılamadı.** Lütfen sistem yöneticinizle iletişime geçin.]"
        
    if not render_plan:
        return "[**Cevap planı oluşturulamadı.**]"

    context = {}
    predictions_to_update = []
    target_lang = user_query.language

    for link in user_query.predictions:
        prediction = link.prediction
        final_value_for_placeholder = None

        if prediction and prediction.predicted_value:
            pred_value_wrapper = prediction.predicted_value
            is_translatable = pred_value_wrapper.get("is_translatable", False)
            content_dict = pred_value_wrapper.get("content", {})
            base_language = getattr(prediction, "base_language_code", "en")

            if not is_translatable:
                final_value_for_placeholder = content_dict.get(base_language)
            else:
                if target_lang in content_dict:
                    final_value_for_placeholder = content_dict[target_lang]
                elif base_language in content_dict:
                    source_data = content_dict[base_language]
                    translated_data = llm_gateway.translate_value(source_data, target_lang, base_language)
                    
                    if not (isinstance(translated_data, dict) and "error" in translated_data):
                        final_value_for_placeholder = translated_data
                        prediction.predicted_value["content"][target_lang] = translated_data
                        predictions_to_update.append(prediction)
                    else:
                        final_value_for_placeholder = translated_data
                else:
                    final_value_for_placeholder = {"error": "source_data_missing", "message": "Kaynak veri mevcut değil."}
        
        if isinstance(final_value_for_placeholder, dict) and "error" in final_value_for_placeholder:
            context[link.placeholder_name] = final_value_for_placeholder 
        elif final_value_for_placeholder is None:
            context[link.placeholder_name] = {"error": "not_found", "message": "Bilgi Bulunamadı."} 
        else:
            context[link.placeholder_name] = final_value_for_placeholder

    if predictions_to_update:
        db.add_all(predictions_to_update)
        db.commit()

    final_answer_parts = []
    try:
        for step in render_plan:
            step_type = step.get("type")

            if step_type == "paragraph":
                final_answer_parts.append(step.get("content", ""))

            elif step_type == "list":
                placeholder = step.get("placeholder")
                item_template = step.get("item_template", "")
                empty_message = step.get("empty_message", "İlgili bilgi bulunamadı.") 
                data_items = context.get(placeholder)

                if isinstance(data_items, dict) and "error" in data_items:
                    final_answer_parts.append(empty_message)
                elif isinstance(data_items, list) and len(data_items) > 0:
                    for item in data_items:
                        if isinstance(item, dict):
                            try:
                                formatted_item = item_template.format(**item)
                                final_answer_parts.append(formatted_item)
                            except KeyError as e:
                                logger.warning(f"Şablon anahtarı {e} veri içinde bulunamadı. Ham şablon ekleniyor. Veri: {item}")
                                final_answer_parts.append(item_template)
                        else:
                            final_answer_parts.append(str(item))
                else:
                    final_answer_parts.append(empty_message)
            else:
                logger.warning(f"Unknown render plan step type: {step_type}")
                final_answer_parts.append(f"[**Bilinmeyen plan tipi:** `{step_type}`]")
        
        return "\n".join(final_answer_parts)
    except Exception as e:
        logger.error(f"Error processing render plan for UserQuery ID {user_query.id}: {e}", exc_info=True)
        return "[**Cevap oluşturulurken şablon işleme hatası oluştu.** Lütfen sistem yöneticinizle iletişime geçin.]"

# --- TESTİ ÇALIŞTIRAN ANA BÖLÜM ---
if __name__ == "__main__":
    print("--- Fonksiyon Test Script'i Başlatıldı ---")

    # 1. Test Verilerini Tanımla
    # Bu, LLM'in üreteceği "render planı"nın bir simülasyonu.
    render_plan = [
        {
            "type": "paragraph",
            "content": "## Donald Trump Hakkındaki Tüm Haberler"
        },
        {
            "type": "paragraph",
            "content": "Aşağıda, Donald Trump hakkında güncel ve önemli haber başlıkları ve özetleri Markdown formatında listelenmiştir:"
        },
        {
            "type": "list",
            "placeholder": "trump_haberleri",
            "item_template": "- **{title}**: {summary}",
            "empty_message": "Bu konuda ilgili haber bulunamadı."
        }
    ]

    # Bu, Prediction'dan gelecek ve veritabanında saklanacak olan asıl veri.
    # Sizden gelen son JSON verisini kullanıyoruz.
    prediction_data = {
        "is_translatable": True,
        "content": {
            "tr": [
                {
                    "title": "Trump, çoğu ülkeye %15 veya %20 genel gümrük vergisi getirmeyi planlıyor",
                    "url": "",
                    "summary": "ABD Başkanı Donald Trump, çoğu ticaret ortağına yüzde 15 veya 20 oranında genel gümrük vergileri uygulayacağını duyurdu."
                },
                {
                    "title": "Trump, Kanada mallarına yüzde 35 tarife uygulanacağını açıkladı",
                    "url": "",
                    "summary": "ABD Başkanı Trump, Kanada'dan ithal edilen mallara yüzde 35 oranında tarife getirileceğini bildirdi."
                },
                {
                    "title": "Trump, bakır ithalatına yüzde 50 tarife uygulanacağını bildirdi",
                    "url": "",
                    "summary": "Donald Trump, 1 Ağustos'tan itibaren bakır ithalatına %50 tarife uygulanacağını duyurdu."
                }
            ]
        }
    }

    # 2. Fonksiyonun İhtiyaç Duyduğu Objeleri Taklit Et (Mocking)
    
    # Sahte veritabanı oturumu. `add_all` ve `commit` metodları hiçbir şey yapmaz.
    mock_db_session = SimpleNamespace(
        add_all=lambda *args: None,
        commit=lambda: None
    )

    # Sahte "Prediction" objesi
    mock_prediction = SimpleNamespace(
        predicted_value=prediction_data,
        base_language_code="tr"
    )

    # Sahte "TemplatePredictionsLink" objesi
    # Render planındaki "placeholder" adını sahte "prediction" objesine bağlar.
    mock_link = SimpleNamespace(
        placeholder_name="trump_haberleri",  # Bu isim render_plan'daki placeholder ile eşleşmeli
        prediction=mock_prediction
    )

    # Ana "UserQuery" objesinin sahtesi
    mock_user_query = SimpleNamespace(
        id=123,
        language="tr",
        answer_template_text=render_plan,
        predictions=[mock_link]
    )

    # 3. Fonksiyonu Test Et ve Çıktıyı Yazdır
    print("\n[INFO] _assemble_final_answer fonksiyonu test ediliyor...")
    
    final_answer = _assemble_final_answer(
        db=mock_db_session,
        user_query=mock_user_query
    )

    print("\n--- FONKSİYON ÇIKTISI BAŞLANGIÇ ---")
    print(final_answer)
    print("--- FONKSİYON ÇIKTISI BİTİŞ ---\n")