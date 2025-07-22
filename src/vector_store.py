import logging
from typing import List
import chromadb
from src import config
from src.processing import embedding_model, create_embedding

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
        self.document_collection = self.client.get_or_create_collection(name="documents")
        self.prediction_collection = self.client.get_or_create_collection(name="predictions")
        logger.info("VectorStore initialized with 'documents' and 'predictions' collections.")

    def add_document_meta(self, doc_id: int, source_url: str, meta_type: str, value: str, embedding: list[float]):
        meta_id = f"doc_{doc_id}_{meta_type}_{abs(hash(value))}"
        self.document_collection.add(
            ids=[meta_id],
            embeddings=[embedding],
            metadatas=[{"document_id": doc_id, "source_url": source_url, "type": meta_type, "text": value}]
        )

    def add_prediction_meta(self, prediction_id: int, meta_type: str, value: str, embedding: list[float]):
        meta_id = f"pred_{prediction_id}_{meta_type}_{abs(hash(value))}"
        self.prediction_collection.add(
            ids=[meta_id],
            embeddings=[embedding],
            metadatas=[{"type": meta_type, "text": value, "prediction_id": prediction_id}]
        )

    def query_document_metas(self, query_text: str, query_keywords: List[str], n_results: int = 5) -> List[dict]:
        """
        Verilen bir metin ve anahtar kelimeler üzerinden DOKÜMANLAR içinde HEDEFLİ hibrit arama yapar.
        Query text'i 'summary' VE 'keywords' alanlarında, anahtar kelimeleri sadece 'keywords' alanında arar.
        """
        if not query_text and not query_keywords:
            return []

        all_hits = {}

        # 1. query_text'i 'summary' VE 'keywords' alanlarında ara
        if query_text:
            text_embedding = embedding_model.encode(query_text).tolist()
            text_results = self.document_collection.query(
                query_embeddings=[text_embedding],
                n_results=n_results,
                where={"type": {"$in": ["summary", "keywords"]}} # Hem summary hem keywords ile eşleştir
            )
            if text_results and text_results["ids"]:
                for i in range(len(text_results["ids"])):
                    for j in range(len(text_results["ids"][i])):
                        hit_id = text_results["ids"][i][j]
                        # Mevcut mesafeden daha iyi (daha düşük) bir mesafe bulursak güncelle
                        meta = text_results["metadatas"][i][j]
                        distance = text_results["distances"][i][j]
                        if hit_id not in all_hits or distance < all_hits[hit_id]["distance"]:
                            all_hits[hit_id] = {
                                "document_id": meta["document_id"],
                                "type": meta["type"],
                                "text": str(meta["text"]),
                                "distance": distance
                            }
        
        # 2. query_keywords'ü sadece 'keywords' alanında ara
        # Bu kısım önceki gibi kalır, çünkü buradaki hedef Prediction'ın keywords'lerini
        # Dokümanın keywords'leri ile eşleştirmektir.
        if query_keywords:
            valid_keywords = [kw for kw in query_keywords if kw]
            if valid_keywords:
                keyword_embeddings = embedding_model.encode(valid_keywords).tolist()
                keyword_results = self.document_collection.query(
                    query_embeddings=keyword_embeddings,
                    n_results=n_results,
                    where={"type": "keywords"} # Sadece keywords tipi ile eşleştir
                )
                if keyword_results and keyword_results["ids"]:
                    for i in range(len(keyword_results["ids"])):
                        for j in range(len(keyword_results["ids"][i])):
                            hit_id = keyword_results["ids"][i][j]
                            meta = keyword_results["metadatas"][i][j]
                            distance = keyword_results["distances"][i][j]
                            if hit_id not in all_hits or distance < all_hits[hit_id]["distance"]:
                                all_hits[hit_id] = {
                                    "document_id": meta["document_id"],
                                    "type": meta["type"],
                                    "text": str(meta["text"]),
                                    "distance": distance
                                }
        
        # Sonuçları mesafeye göre sırala
        return sorted(list(all_hits.values()), key=lambda x: x["distance"])

    def query_prediction_metas(self, query_text: str, n_results: int = 5) -> List[dict]:
        """Verilen bir metne göre prediction'lar içinde anlamsal arama yapar (analiz script'i için)."""
        emb = create_embedding(query_text)
        results = self.prediction_collection.query(
            query_embeddings=[emb],
            n_results=n_results,
            where={"type": {"$in": ["prompt_text", "keyword"]}}
        )
        hits = []
        if results and results["metadatas"] and results["distances"]:
            for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
                hits.append({"prediction_id": meta["prediction_id"], "type": meta["type"], "text": str(meta["text"]), "distance": dist})
        return sorted(hits, key=lambda x: x["distance"])

    def find_similar_predictions(self, query_text: str, query_keywords: List[str], top_k: int = 5) -> List[int]:
        """
        Prompt metni ve anahtar kelimeler üzerinden verimli bir hibrit arama yapar
        ve en alakalı Prediction ID'lerini döndürür.
        """
        if not query_text and not query_keywords:
            return []

        query_embeddings = []
        texts_to_embed = []
        if query_text:
            texts_to_embed.append(query_text)
        if query_keywords:
            texts_to_embed.extend([kw for kw in query_keywords if kw])
            
        if not texts_to_embed:
            return []

        query_embeddings = embedding_model.encode(texts_to_embed).tolist()

        results = self.prediction_collection.query(
            query_embeddings=query_embeddings,
            n_results=top_k,
            where={"type": {"$in": ["prompt_text", "keyword"]}}
        )

        candidate_ids = set()
        if results and results['ids']:
            for id_list in results['ids']:
                for single_id, meta_data in zip(id_list, results['metadatas'][results['ids'].index(id_list)]):
                    candidate_ids.add(meta_data['prediction_id'])

        logger.info(f"Hybrid search yielded a total of {len(candidate_ids)} unique prediction candidates.")
        return list(candidate_ids)

# Singleton instance
vector_store = VectorStore()