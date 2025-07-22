import json
from sentence_transformers import SentenceTransformer
import numpy as np
from numpy.linalg import norm

#embedding_model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
#embedding_model = SentenceTransformer("LaBSE")
embedding_model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

def get_cosine_similarity(text1: str, text2: str) -> float:
    if not text1 or not text2:
        return 0.0
    e1 = embedding_model.encode(text1, show_progress_bar=False)
    e2 = embedding_model.encode(text2, show_progress_bar=False)
    return float(np.dot(e1, e2) / (norm(e1) * norm(e2)))

def dict_similarity(d1: dict, d2: dict) -> float:
    """
    İki sözlüğü json.dumps ile deterministik biçimde serileştirip
    gömlek‑tabanlı kosinüs benzerliğini döndürür.
    """
    s1 = json.dumps(d1, ensure_ascii=False, sort_keys=True)
    s2 = json.dumps(d2, ensure_ascii=False, sort_keys=True)
    return get_cosine_similarity(s1, s2)



# ---------- Örnek JSON'lar ----------

json_before = {
    "faydalar": [
        {"fayda": "İmar hakkı aktarımı sayesinde vatandaşlar mülklerini daha verimli kullanabilir."},
        {"fayda": "Yasal düzenlemelerle imar hakkı transferi süreçleri daha kolay ve şeffaf hale gelmiştir."},
        {"fayda": "Vatandaşlar, küçük yasal iyileştirmeler sayesinde haklarını daha etkin şekilde kullanabilir."},
        {"fayda": "İmar hakkı aktarımı ile ekonomik değer yaratma imkanları artar."},
        {"fayda": "Yasal düzenlemelerle imar hakkı transferlerinde vatandaşların hakları daha iyi korunur."}
    ]
}
json_after_2 = {
     "faydalar": [
        {"fayda": "emekliler , 2, küçük yasal iyileştirmeler sayesinde haklarını daha etkin şekilde kullanabilir."},
        {"fayda": "İmar hakkı aktarımı sayesinde vatandaşlar mülklerini daha verimli kullanabilir."},
        {"fayda": "Yasal düzenlemelerle imar hakkı transferlerinde vatandaşların hakları daha iyi korunur."},
        {"fayda": "Yasal düzenlemelerle imar hakkı transferi süreçleri daha kolay ve şeffaf hale gelmiştir."},
        {"fayda": "İmar hakkı aktarımı ile ekonomik değer yaratma imkanları artar."}
    ]
}

json_after_extended = {
    "faydalar":  [
        {"fayda2": "Kanuni değişiklikler sayesinde imar hakkı aktarım süreci daha esnek işlemesi sağlanır."},
        {"fayda": "İmar hakkı transferi, mülk sahiplerinin mülk değerlerini korumalarına yardımcı olur."},
        {"fayda": "İmar hakkı aktarımı artık kentsel dönüşüm projelerinde de kullanılabilir, bu da vatandaşlara büyük esneklik sağlar."},
        {"fayda": "Kamulaştırma süreçlerindeki uzun bekleyişler ve mağduriyetler ortadan kalkar, vatandaşlara anında ve adil çözüm sunulur."},
        {"fayda": "Şehir merkezlerindeki yoğunluk azalır ve daha yaşanabilir kentsel alanlar oluşturulur."}
    ] + json_before["faydalar"] 
}

score = dict_similarity(json_before, json_before)
print(f"json_before ↔ json_after_extended benzerlik skoru: {score:.4f}")


score = dict_similarity(json_before, json_after_2)
print(f"json_before ↔ json_after_extended benzerlik skoru: {score:.4f}")

score = dict_similarity(json_before, json_after_extended)
print(f"json_before ↔ json_after_extended benzerlik skoru: {score:.4f}")
