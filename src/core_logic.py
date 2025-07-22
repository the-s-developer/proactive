import logging
import frontmatter
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
import json

from src.vector_store import vector_store
from src.processing import create_embedding, get_cosine_similarity, calculate_keyword_set_similarity
from src.database import get_db, Document, Prediction, UserQuery, TemplatePredictionsLink
from src.llm_gateway import llm_gateway

logger = logging.getLogger(__name__)

def _assemble_final_answer(db: Session, user_query: UserQuery) -> str:
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

def _find_and_rerank_relevant_predictions(db: Session, summary: str, keywords: list[str], top_k: int = 10) -> list[int]:
    """
    Bir doküman için en alakalı Prediction'ları bulur (ön eleme + yeniden sıralama).
    """
    initial_candidate_limit = max(50, top_k * 5) 

    initial_candidate_ids = vector_store.find_similar_predictions(
        query_text=summary, 
        query_keywords=keywords, 
        top_k=initial_candidate_limit 
    )
    if not initial_candidate_ids:
        logger.info("No initial candidates found from vector search for reranking.")
        return []
        
    candidate_predictions = db.query(Prediction).filter(Prediction.id.in_(initial_candidate_ids)).all()
    reranked_predictions = []
    
    KEYWORD_MATCH_THRESHOLD = 0.7 
    
    PROMPT_SUMMARY_WEIGHT = 0.7
    KEYWORD_MATCH_WEIGHT = 0.3
    
    MIN_COMBINED_SCORE = 0.1 

    for pred in candidate_predictions:
        prompt_summary_score = get_cosine_similarity(pred.prediction_prompt, summary)
        
        keyword_match_score_avg = calculate_keyword_set_similarity(pred.keywords or [], keywords, similarity_threshold=KEYWORD_MATCH_THRESHOLD)
        
        combined_score = (prompt_summary_score * PROMPT_SUMMARY_WEIGHT) + \
                         (keyword_match_score_avg * KEYWORD_MATCH_WEIGHT)
        
        if combined_score < MIN_COMBINED_SCORE:
            logger.debug(f"Prediction ID {pred.id} (Prompt: '{pred.prediction_prompt[:20]}...') skipped due to low combined score: {combined_score:.4f}")
            continue

        reranked_predictions.append({
            "id": pred.id, 
            "score": combined_score,
            "prompt_summary_score": prompt_summary_score, 
            "keyword_match_score_avg": keyword_match_score_avg 
        })
        
    reranked_predictions.sort(key=lambda x: x["score"], reverse=True)
    
    final_ids = [p["id"] for p in reranked_predictions[:top_k]]
    logger.info(f"Reranking completed. Returning top {len(final_ids)} relevant prediction IDs.")
    
    return final_ids

def handle_new_document(file_path: str):
    """
    Yeni bir dokümanı işler. İlgili prediction'ları günceller, eski çevirileri geçersiz kılar
    ve abone olan kullanıcı cevaplarını yeniden oluşturur.
    """
    logger.info(f"Starting ingestion for document: {file_path}")
    db: Session = next(get_db())
    try:
        post = frontmatter.load(file_path)
        metadata = post.metadata
        content = post.content
        source_url = metadata.get('url')
        if not source_url or db.query(Document).filter_by(source_url=source_url).first():
            logger.warning(f"Skipping document: {source_url} (missing URL or already exists).")
            return

        new_doc = Document(source_url=source_url, raw_markdown_content=content, publication_date=metadata.get('pub_date'))
        db.add(new_doc); db.commit(); db.refresh(new_doc)
        
        summary = metadata.get('summary', '')
        keywords = list(set([str(k) for k in metadata.get('keywords', [])] + [str(e.get('value', e)) for e in metadata.get('entities', [])]))
        meta_to_embed = {"summary": [summary], "keywords": keywords}
        for meta_type, values in meta_to_embed.items():
            for value in values:
                if value:
                    vector_store.add_document_meta(new_doc.id, source_url, meta_type, value, create_embedding(value))
        
        relevant_prediction_ids = _find_and_rerank_relevant_predictions(db, summary, keywords)
        if not relevant_prediction_ids:
            logger.info("No relevant predictions to update.")
            return

        relevant_predictions = db.query(Prediction).filter(Prediction.id.in_(relevant_prediction_ids)).all()
        updated_prediction_ids = []
        
        for pred in relevant_predictions:
            base_language = getattr(pred, "base_language_code", "en")
            source_content = pred.predicted_value.get("content", {}).get(base_language)
            if source_content is None:
                continue

            logger.info(f"Performing INCREMENTAL update for Prediction ID {pred.id}.")
            update_result = llm_gateway.update_prediction(pred.prediction_prompt, source_content, [content], base_language)
            
            status = (update_result.get("status") or "").strip().lower()
            if status in ["no_change", "error"]:
                logger.info(f"Prediction {pred.id} update is not required (no change or error).")
                continue

            new_data = update_result.get("data")
            logger.info(f"Prediction {pred.id} requires a substantive update.")

            pred.predicted_value["content"][base_language] = new_data
            pred.predicted_value["is_translatable"] = update_result.get("is_translatable", False)
            
            keys_to_delete = [lang for lang in pred.predicted_value["content"] if lang != base_language]
            if keys_to_delete:
                for lang in keys_to_delete:
                    del pred.predicted_value["content"][lang]

            pred.last_updated = datetime.now(timezone.utc)
            db.add(pred)
            updated_prediction_ids.append(pred.id)

        if not updated_prediction_ids:
            logger.info("No predictions were substantively updated.")
            return
            
        db.commit()
        
        distinct_query_ids_to_update = db.query(TemplatePredictionsLink.query_id)\
                                             .filter(TemplatePredictionsLink.prediction_id.in_(updated_prediction_ids))\
                                             .distinct()\
                                             .all()
        
        query_ids_list = [q_id[0] for q_id in distinct_query_ids_to_update]

        queries_to_update = db.query(UserQuery).filter(UserQuery.id.in_(query_ids_list)).all()
        
        for query in queries_to_update:
            if query.is_subscribed:
                query.final_answer = _assemble_final_answer(db, query)
                query.answer_last_updated = datetime.now(timezone.utc)
                db.add(query)
        db.commit()
        logger.info(f"Reactive update of {len(queries_to_update)} final answers finished.")
        
    except Exception as e:
        logger.error(f"Error in handle_new_document: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()
        
def _process_query_logic(db: Session, user_query: UserQuery):
    """
    Bir UserQuery objesi alır ve Analist-Orkestratör mantığını çalıştırarak
    cevabı oluşturur ve veritabanını günceller. Hem yeni hem de güncellenen
    sorgular için ortak mantığı içerir.
    """
    query_text = user_query.query_text

    # AŞAMA 1: ANALİZ
    analysis = llm_gateway.decompose_query_into_tasks(query_text)
    potential_tasks = analysis.get("potential_tasks", [])
    user_lang = analysis.get("user_language_code", "en")
    user_query.language = user_lang 

    if not potential_tasks:
        raise ValueError("LLM Analyst failed to decompose query into tasks.")

    # AŞAMA 2: ADAY TESPİTİ
    candidates_map = {}
    SEMANTIC_MATCH_THRESHOLD = 0.85
    for task in potential_tasks:
        prompt = task['prompt']
        keywords = task['keywords']
        candidate_ids = vector_store.find_similar_predictions(prompt, keywords, top_k=3)
        if candidate_ids:
            candidates = db.query(Prediction).filter(Prediction.id.in_(candidate_ids)).all()
            strong_candidates = []
            for cand in candidates:
                similarity = get_cosine_similarity(prompt, cand.prediction_prompt)
                if similarity >= SEMANTIC_MATCH_THRESHOLD:
                    strong_candidates.append({"id": cand.id, "prompt": cand.prediction_prompt})
            candidates_map[prompt] = strong_candidates
        else:
            candidates_map[prompt] = []

    # AŞAMA 3: ORKESTRASYON
    decomposition = llm_gateway.orchestrate_tasks_and_plan(query_text, potential_tasks, candidates_map)
    render_plan = decomposition.get('render_plan', [])
    prediction_specs = decomposition.get('predictions', [])

    if not render_plan or not prediction_specs:
        raise ValueError("LLM Orchestrator failed to create a final plan.")

    user_query.answer_template_text = render_plan

    # AŞAMA 4: PLANI UYGULAMA
    for spec in prediction_specs:
        placeholder = spec['placeholder_name']
        prediction = None
        if "reuse_prediction_id" in spec:
            prediction = db.query(Prediction).get(spec["reuse_prediction_id"])
        
        elif "new_prediction_prompt" in spec:
            prompt = spec["new_prediction_prompt"]
            keywords = spec.get("keywords", [])
            
            context_hits = vector_store.query_document_metas(prompt, keywords, n_results=5)
            if context_hits:
                context_texts = [h['text'] for h in context_hits]
                llm_output = llm_gateway.fulfill_prediction(prompt, context_texts)
            else:
                llm_output = {"is_translatable": False, "data": {"error": "not_found", "message": "Kaynak dokümanlarda bilgi bulunamadı."}}
            
            new_value = {
                "is_translatable": llm_output.get("is_translatable", False),
                "content": {user_lang: llm_output.get("data")}
            }
            
            # Prediction objesi, isimlendirilmiş argümanlarla (keyword arguments) oluşturuldu.
            prediction = Prediction(
                prediction_prompt=prompt,
                predicted_value=new_value,
                base_language_code=user_lang,
                keywords=keywords,
                status="FULFILLED",
                last_updated=datetime.now(timezone.utc)
            )
            db.add(prediction)
            db.commit()
            db.refresh(prediction)
            vector_store.add_prediction_meta(prediction.id, "prompt_text", prompt, create_embedding(prompt))
            for kw in keywords:
                if kw:
                    vector_store.add_prediction_meta(prediction.id, "keyword", kw, create_embedding(kw))

        if prediction:
            db.add(TemplatePredictionsLink(query_id=user_query.id, prediction_id=prediction.id, placeholder_name=placeholder))

    db.commit()
    db.refresh(user_query, ['predictions'])

    # AŞAMA 5: CEVABI BİRLEŞTİR
    user_query.final_answer = _assemble_final_answer(db, user_query)
    user_query.answer_last_updated = datetime.now(timezone.utc)
    db.commit()

def handle_new_query(query_text: str) -> int | None:
    """Yeni bir kullanıcı sorgusu oluşturur ve işler."""
    logger.info(f"Handling new query: '{query_text}'")
    db: Session = next(get_db())
    try:
        user_query = UserQuery(query_text=query_text, is_subscribed=True)
        db.add(user_query)
        db.commit()
        db.refresh(user_query)
        
        _process_query_logic(db, user_query)

        print(f"\n--- NİHAİ CEVAP (ID: {user_query.id}) ---\n{user_query.final_answer}\n-----------------------\n")
        return user_query.id
    except Exception as e:
        logger.error(f"Error in handle_new_query: {e}", exc_info=True)
        db.rollback()
        return None
    finally:
        db.close()

def update_query_text(query_id: int, new_query_text: str) -> int | None:
    """Mevcut bir sorgunun metnini günceller ve tüm süreci yeniden çalıştırır."""
    logger.info(f"Updating UserQuery ID {query_id} with new text: '{new_query_text}'")
    db: Session = next(get_db())
    try:
        user_query = db.query(UserQuery).filter(UserQuery.id == query_id).first()
        if not user_query:
            logger.warning(f"Update failed: UserQuery ID {query_id} not found.")
            return None
        
        # 1. Eski bağlantıları temizle
        db.query(TemplatePredictionsLink).filter(TemplatePredictionsLink.query_id == query_id).delete(synchronize_session=False)
        
        # 2. Sorgu metnini güncelle
        user_query.query_text = new_query_text
        db.commit()
        db.refresh(user_query)

        # 3. Ana mantığı güncellenmiş obje ile yeniden çalıştır
        _process_query_logic(db, user_query)

        print(f"\n--- GÜNCELLENMİŞ CEVAP (ID: {user_query.id}) ---\n{user_query.final_answer}\n-----------------------\n")
        return user_query.id
    except Exception as e:
        logger.error(f"Error updating query ID {query_id}: {e}", exc_info=True)
        db.rollback()
        return None
    finally:
        db.close()

def update_user_query_subscription(query_id: int, subscribe: bool):
    """Kullanıcının bir sorgu için güncelleme aboneliğini değiştirir."""
    db: Session = next(get_db())
    try:
        user_query = db.query(UserQuery).filter(UserQuery.id == query_id).first()
        if user_query:
            user_query.is_subscribed = subscribe
            db.add(user_query)
            db.commit()
            logger.info(f"UserQuery ID {query_id} subscription status updated to {subscribe}.")
        else:
            logger.warning(f"UserQuery ID {query_id} not found for subscription update.")
    except Exception as e:
        logger.error(f"Error updating subscription: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()