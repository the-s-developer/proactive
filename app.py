import streamlit as st
import sys
import os
import json
from datetime import datetime, timezone
import logging

# Proje kök dizinini Python path'ine ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from logger_config import setup_logging
# 'refulfill_answer' import'u kaldırıldı
from core_logic import handle_new_query, update_user_query_subscription, update_query_text
from database import get_db, UserQuery, Prediction, TemplatePredictionsLink
from answer_monitor import answer_monitor
from sqlalchemy.orm import joinedload

# Loglama ve sayfa ayarları
setup_logging()
logger = logging.getLogger(__name__)
st.set_page_config(layout="wide", page_title="Reaktif Cevap Sistemi")

# Session state değişkenlerini başlat
if 'current_query_id' not in st.session_state:
    st.session_state.current_query_id = None
if 'editing_query_id' not in st.session_state:
    st.session_state.editing_query_id = None
if 'query_input_value' not in st.session_state:
    st.session_state.query_input_value = ""
if 'last_answer_check_time' not in st.session_state:
    st.session_state.last_answer_check_time = datetime.min.replace(tzinfo=timezone.utc)

def get_all_user_queries_with_details():
    """Tüm kullanıcı sorgularını ve ilgili tüm detayları verimli bir şekilde getirir."""
    db = next(get_db())
    try:
        queries = db.query(UserQuery).options(
            joinedload(UserQuery.predictions).joinedload(TemplatePredictionsLink.prediction)
        ).order_by(UserQuery.created_at.desc()).all()
        return queries
    finally:
        db.close()

def update_subscription_and_rerun(query_id: int, subscribe: bool):
    """Abonelik durumunu günceller ve arayüzü yeniler."""
    update_user_query_subscription(query_id=query_id, subscribe=subscribe)
    st.session_state.current_query_id = query_id
    st.rerun()

# 'refulfill_and_show_toast' fonksiyonu kaldırıldı

# --- Streamlit Arayüzü ---
st.title("💡 Reaktif Cevap Sistemi")
st.markdown("Sorular sorun ve sistemin cevapları nasıl oluşturduğunu görün. Yeni belgeler eklendiğinde **cevaplarınızın** reaktif olarak güncellendiğini izleyin!")

st.divider()

# Yeni Sorgu Bölümü
st.header("Yeni Bir Soru Sorun")

user_query_input = st.text_input(
    "Sorgunuzu buraya girin:",
    key="user_query_text_input",
    value=st.session_state.query_input_value,
    placeholder="Örn: İmar hakkı aktarımı ile kamulaştırma arasındaki farklar nelerdir?"
)

if st.button("Sorguyu Gönder", type="primary"):
    if user_query_input:
        with st.spinner("Sorgunuz işleniyor ve ilk cevap oluşturuluyor..."):
            try:
                query_id = handle_new_query(query_text=user_query_input)
                if query_id:
                    st.success(f"Sorgu başarıyla işlendi! ID: {query_id}")
                    st.session_state.current_query_id = query_id
                    st.session_state.query_input_value = ""
                else:
                    st.error("Sorgu işlenirken bir hata oluştu. Logları kontrol edin.")
            except Exception as e:
                st.error(f"Beklenmedik bir hata oluştu: {e}")
                logger.exception("Sorgu gönderiminde kritik hata.")
        st.rerun()
    else:
        st.warning("Lütfen bir sorgu girin.")

st.divider()

# Geçmiş Sorgular ve Cevaplar
st.header("Geçmiş Sorularınız ve Cevaplarınız")

if st.button("🔄 Cevap Güncellemelerini Kontrol Et"):
    with st.spinner("Güncellenen cevaplar kontrol ediliyor..."):
        updated_answers = answer_monitor.get_updated_answers_since(st.session_state.last_answer_check_time)
        st.session_state.last_answer_check_time = datetime.now(timezone.utc)
        if updated_answers:
            st.toast(f"🎉 {len(updated_answers)} adet cevap güncellendi!", icon="🎉")
        else:
            st.toast("Yeni güncellenen cevap bulunamadı.", icon="ℹ️")
    st.rerun()

all_queries = get_all_user_queries_with_details()

if not all_queries:
    st.info("Henüz bir sorgu oluşturulmadı.")
else:
    for query in all_queries:
        is_expanded = st.session_state.current_query_id == query.id
        with st.expander(f"**Sorgu ID: {query.id}** - *'{query.query_text[:70]}...'*", expanded=is_expanded):
            
            # Düzenleme modu aktifse, düzenleme formunu göster
            if st.session_state.editing_query_id == query.id:
                st.subheader(f"Sorgu ID: {query.id} Düzenleniyor")
                new_text = st.text_area(
                    "Sorgu Metni:", 
                    value=query.query_text, 
                    key=f"edit_text_{query.id}",
                    height=150
                )
                
                col1, col2, _ = st.columns([1, 1, 6])
                with col1:
                    if st.button("💾 Kaydet", key=f"save_{query.id}", type="primary"):
                        with st.spinner("Sorgu güncelleniyor ve tüm adımlar yeniden çalıştırılıyor..."):
                            update_query_text(query_id=query.id, new_query_text=new_text)
                            st.session_state.editing_query_id = None # Düzenleme modundan çık
                            st.session_state.current_query_id = query.id # Güncellenen sorgu açık kalsın
                            st.rerun()
                with col2:
                    if st.button("❌ İptal", key=f"cancel_{query.id}"):
                        st.session_state.editing_query_id = None # Düzenleme modundan çık
                        st.rerun()
            else:
                # Normal cevap gösterme modu
                tab1, tab2 = st.tabs(["Nihai Cevap", "Teknik Detaylar"])
                with tab1:
                    # Sütun düzeni "Yeniden Oluştur" butonu olmadan güncellendi
                    col1, col2, col3 = st.columns([6, 2, 2])
                    with col1:
                        st.write(f"**Sorulma Zamanı:** {query.created_at.strftime('%Y-%m-%d %H:%M')}")
                    with col2:
                        if query.is_subscribed:
                            st.button(f"🔔 Abonelikten Çık", key=f"unsub_{query.id}", on_click=update_subscription_and_rerun, args=(query.id, False), help="Bu sorunun güncellemelerini takip etmeyi bırak.")
                        else:
                            st.button(f"🔕 Abone Ol", key=f"sub_{query.id}", on_click=update_subscription_and_rerun, args=(query.id, True), help="Bu sorunun güncellemelerini takip et.")
                    
                    with col3:
                        if st.button("✏️ Düzenle", key=f"edit_{query.id}", help="Bu sorgunun metnini değiştirerek tamamen yeniden çalıştır."):
                            st.session_state.editing_query_id = query.id
                            st.rerun()
                    
                    st.markdown("#### Cevap")
                    if query.answer_last_updated:
                        st.caption(f"Son Güncelleme: {query.answer_last_updated.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    
                    if query.final_answer:
                        status_emoji = '🟢' if query.is_subscribed else '⚪'
                        st.markdown(f"{status_emoji} {query.final_answer}")
                    else:
                        st.warning("Cevap henüz oluşturulmadı veya bekleniyor.")

                with tab2:
                    st.markdown("##### Cevap Planı (Render Plan)")
                    if query.answer_template_text:
                        try:
                            # answer_template_text veritabanından string olarak gelebilir
                            plan_data = json.loads(query.answer_template_text) if isinstance(query.answer_template_text, str) else query.answer_template_text
                            st.json(plan_data)
                        except json.JSONDecodeError:
                            st.code(query.answer_template_text, language="json")
                    else:
                        st.info("Cevap planı bulunamadı.")
                    
                    st.markdown("##### İlişkili Tahminler (Predictions)")
                    if not query.predictions:
                        st.info("Bu cevabı oluşturan tahmin bulunamadı.")
                    
                    for link in query.predictions:
                        pred = link.prediction
                        st.markdown(f"**➡️ Yer Tutucu:** `{link.placeholder_name}` (Prediction ID: {pred.id})")
                        st.text(f"Prompt: {pred.prediction_prompt}")
                        st.text("Değer:")
                        
                        pred_value = pred.predicted_value or {}
                        if isinstance(pred_value, dict) and "error" in pred_value:
                            st.error(f"Bu tahmin için bilgi bulunamadı: {pred_value.get('message', 'Bilinmeyen Hata')}")
                        else:
                            st.json(pred_value)