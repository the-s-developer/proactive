from sentence_transformers import SentenceTransformer
import logging
import numpy as np
from numpy.linalg import norm

logger = logging.getLogger(__name__)

# Modeli bir kere yükleyip tekrar kullanmak için globalde tutalım
embedding_model = SentenceTransformer('Qwen/Qwen3-Embedding-0.6B')

def create_embedding(text: str) -> list[float]:
    """Verilen metin için bir embedding vektörü oluşturur."""
    logger.debug(f"Creating embedding for text snippet: '{text[:50]}...'")
    return embedding_model.encode(text, show_progress_bar=False).tolist()

def get_cosine_similarity(text1: str, text2: str) -> float:
    """
    İki metin arasında kosinüs benzerlik skorunu hesaplar (0.0 ile 1.0 arası).
    Döndürülen değer ne kadar yüksekse, anlamsal benzerlik o kadar fazladır.
    """
    if not text1 or not text2:
        return 0.0
    try:
        embedding1 = embedding_model.encode(text1, show_progress_bar=False)
        embedding2 = embedding_model.encode(text2, show_progress_bar=False)
        cosine_similarity = np.dot(embedding1, embedding2) / (norm(embedding1) * norm(embedding2))
        return float(cosine_similarity)
    except Exception as e:
        logger.warning(f"Error calculating similarity for texts ('{text1[:20]}...', '{text2[:20]}...'): {e}")
        return 0.0

def calculate_keyword_set_similarity(keywords1: list[str], keywords2: list[str], similarity_threshold: float = 0.7) -> float:
    """
    Birinci anahtar kelime listesinden ikinciye doğru, belirli bir eşiğin üzerindeki eşleşen anahtar kelime skorlarının ortalamasını hesaplar.
    keywords1 içindeki her bir anahtar kelime için, keywords2 içindeki en benzer anahtar kelimeyi bulur.
    Eğer bu en iyi benzerlik 'similarity_threshold' üzerindeyse, o skor ortalamaya dahil edilir.
    Dönen değer, eşiği geçen skorların ortalamasıdır (0.0 ile 1.0 arası). Eğer eşiği geçen skor yoksa 0.0 döner.
    """
    if not keywords1 or not keywords2:
        return 0.0

    try:
        embs1 = embedding_model.encode([kw for kw in keywords1 if kw], show_progress_bar=False)
        embs2 = embedding_model.encode([kw for kw in keywords2 if kw], show_progress_bar=False)

        if embs1.shape[0] == 0 or embs2.shape[0] == 0:
            return 0.0

        embs1_norm = embs1 / norm(embs1, axis=1, keepdims=True)
        embs2_norm = embs2 / norm(embs2, axis=1, keepdims=True)

        sim_matrix = np.dot(embs1_norm, embs2_norm.T)

        # Birinci setteki her bir anahtar kelime için ikinci setteki en yüksek benzerlik skorunu bul
        max_sims_per_kw1 = np.max(sim_matrix, axis=1)

        # Eşiği geçen skorları filtrele
        passing_scores = max_sims_per_kw1[max_sims_per_kw1 >= similarity_threshold]

        # Eğer eşiği geçen skor varsa, bunların ortalamasını al; yoksa 0.0 döndür
        if len(passing_scores) > 0:
            return float(np.mean(passing_scores))
        else:
            return 0.0

    except Exception as e:
        logger.warning(f"Error calculating keyword set similarity: {e}")
        return 0.0