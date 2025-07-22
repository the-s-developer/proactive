import json
from openai import OpenAI
from src import config
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class LLMGateway:
    def __init__(self):
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        logger.info("OpenAI client initialized.")

    # YENİ FONKSİYON 1: ANALİST
    def decompose_query_into_tasks(self, user_query: str) -> Dict[str, Any]:
        """
        Kullanıcının sorgusunu analiz eder ve onu bir veya daha fazla atomik,
        makine tarafından yürütülebilir göreve (task) ayırır.
        """
        logger.info("Decomposing query into potential tasks...")
        meta_prompt = f"""
        ROLE:
        You are an expert system analyst. Your job is to break down a user's query into a series of clear, specific, and atomic tasks required to answer it.

        USER QUERY:
        "{user_query}"

        YOUR TASK:
        1.  **DETECT LANGUAGE**: Identify the language of the user's query (e.g., "tr", "en").
        2.  **IDENTIFY CORE TASKS**: Analyze the user's query to understand the underlying information needed.
        3.  **GENERATE TASK PROMPTS**: For each piece of information needed, create a clear, machine-readable "prediction_prompt" in ENGLISH. Each prompt should ask for one specific piece of data. Also, generate relevant "keywords" for each prompt.
        4.  **OUTPUT JSON**: Your output MUST be a single, valid JSON object.

        EXAMPLE:
        User Query: "What is the capital of Turkey and what is its population?"
        
        Your Output:
        {{
          "user_language_code": "tr",
          "potential_tasks": [
            {{
              "prompt": "Provide the capital city of Turkey.",
              "keywords": ["Turkey", "capital city"]
            }},
            {{
              "prompt": "Provide the current population of Ankara.",
              "keywords": ["Ankara", "population", "statistics"]
            }}
          ]
        }}
        """
        try:
            response = self.client.chat.completions.create(
                model=config.DECOMPOSER_MODEL, # Or a faster model for this simple task
                messages=[{"role": "system", "content": meta_prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Error during query task decomposition: {e}", exc_info=True)
            return {"user_language_code": "en", "potential_tasks": []}

    # YENİ FONKSİYON 2: ORKESTRATÖR
    def orchestrate_tasks_and_plan(self, user_query: str, potential_tasks: List[Dict], candidates_map: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """
        Gereken görevleri, mevcut aday Prediction'ları ve orijinal sorguyu alarak
        nihai bir render planı ve görev listesi oluşturur.
        """
        logger.info("Orchestrating final plan...")

        candidates_text = "Analysis of available data:\n"
        for task in potential_tasks:
            prompt = task['prompt']
            candidates_text += f"- For the required task '{prompt}':\n"
            if prompt in candidates_map and candidates_map[prompt]:
                for candidate in candidates_map[prompt]:
                    candidates_text += f"  - Found existing Prediction [ID: {candidate['id']}, Prompt: \"{candidate['prompt']}\"]\n"
            else:
                candidates_text += "  - No existing predictions found. A new one must be created.\n"

        meta_prompt = f"""
        ROLE:
        You are an expert system orchestrator. Your job is to create a final execution plan to answer a user's query, using a list of required tasks and a list of available, pre-existing data points (Predictions).

        ORIGINAL USER QUERY:
        "{user_query}"

        REQUIRED TASKS TO FULFILL THE QUERY:
        {json.dumps(potential_tasks, indent=2)}

        AVAILABLE PRE-EXISTING DATA (CANDIDATE PREDICTIONS):
        {candidates_text}

        YOUR TASK:
        1.  **CREATE RENDER PLAN**: Based on the ORIGINAL USER QUERY, create a `render_plan` in the user's language to display the final answer attractively. Use placeholders for each required task.
        2.  **CREATE FINAL PREDICTION LIST**: Iterate through the REQUIRED TASKS. For each task:
            a. Look at the AVAILABLE PRE-EXISTING DATA. If you find a candidate whose prompt is a very close semantic match for the required task, decide to REUSE it. Use its ID.
            b. If no suitable candidate is found, decide to CREATE a NEW prediction. Use the required task's prompt and keywords.
        3.  **OUTPUT JSON**: Your output MUST be a single, valid JSON object containing the `render_plan` and the final `predictions` list. The predictions list should specify `reuse_prediction_id` for reused tasks, and `new_prediction_prompt` for new ones. Use the placeholder names from your render plan.

        EXAMPLE OUTPUT:
        {{
          "render_plan": [
             {{ "type": "paragraph", "content": "Türkiye'nin başkenti {capital_city} şehridir." }},
             {{ "type": "paragraph", "content": "Bu şehrin nüfusu yaklaşık {capital_population} kişidir." }}
          ],
          "predictions": [
            {{
              "placeholder_name": "capital_city",
              "reuse_prediction_id": 123
            }},
            {{
              "placeholder_name": "capital_population",
              "new_prediction_prompt": "Provide the current population of Ankara.",
              "keywords": ["Ankara", "population", "statistics"]
            }}
          ]
        }}
        """
        try:
            response = self.client.chat.completions.create(
                model=config.DECOMPOSER_MODEL,
                messages=[{"role": "system", "content": meta_prompt}],
                response_format={"type": "json_object"}
            )
            # Add user_language_code to the final output for handle_new_query
            final_plan = json.loads(response.choices[0].message.content)
            final_plan['user_language_code'] = potential_tasks[0].get('user_language_code', 'en') if potential_tasks else 'en'
            return final_plan

        except Exception as e:
            logger.error(f"Error during plan orchestration: {e}", exc_info=True)
            return {"render_plan": [], "predictions": []}

    # --- Diğer fonksiyonlar (fulfill_prediction, translate_value, update_prediction) aynı kalır ---
    def fulfill_prediction(self, prediction_prompt: str, context_chunks: List[str]) -> Dict[str, Any]:
        # Bu fonksiyonun içeriği değişmedi
        logger.info(f"Fulfilling prediction... Model: {config.WORKER_MODEL}")
        context_str = "\n---\n".join(context_chunks)
        rag_prompt = f"""
        ROLE:
        You are a precise, data extraction engine. You will answer the TASK based on the CONTEXT.

        CONTEXT:
        ---
        {context_str}
        ---

        TASK TO FULFILL:
        {prediction_prompt}

        *** VERY IMPORTANT OUTPUT INSTRUCTIONS ***
        1.  First, generate the data requested by the TASK.
        2.  Second, analyze the data you generated.
            - If the data is natural language text (sentences, paragraphs, summaries), it IS translatable.
            - If the data is purely numerical, a date, a boolean, a stock symbol, or a list of such items, it is NOT translatable.
        3.  Your final output MUST be a single JSON object with two keys:
            - "is_translatable": A boolean (`true` or `false`).
            - "data": The actual data you generated in step 1.
        4.  If the information is not in the context, respond with:
            `{{"is_translatable": false, "data": {{"error": "not_found"}}}}`
        5.  NEVER add explanations. Your output must be ONLY the specified JSON object.
        """
        try:
            response = self.client.chat.completions.create(
                model=config.WORKER_MODEL,
                messages=[{"role": "system", "content": rag_prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Error during prediction fulfillment: {e}", exc_info=True)
            return {"is_translatable": False, "data": {"error": str(e)}}

    def translate_value(self, value_to_translate: Any, target_language_code: str, source_language_code: str = "en") -> Any:
        # Bu fonksiyonun içeriği değişmedi
        logger.info(f"Translating value from '{source_language_code}' to '{target_language_code}'...")
        if not isinstance(value_to_translate, (dict, list)):
            return value_to_translate

        value_str = json.dumps(value_to_translate, ensure_ascii=False)
        prompt = f"""
        ROLE: You are a high-fidelity translation service.
        TASK: Translate the following JSON data structure from source language '{source_language_code}' to target language '{target_language_code}'.
        IMPORTANT:
        - You MUST maintain the exact same JSON structure (keys, lists, objects).
        - Only translate the string values within the JSON.
        - Your output MUST be ONLY the translated, valid JSON object.

        JSON TO TRANSLATE:
        {value_str}
        """
        try:
            response = self.client.chat.completions.create(
                model=config.WORKER_MODEL,
                messages=[{"role": "system", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Failed to translate value: {e}", exc_info=True)
            return {"error": "translation_failed", "message": f"Could not translate to {target_language_code}"}

    def update_prediction(self, prediction_prompt: str, current_value_content: Any, new_context_chunks: List[str],base_language: str = "en") -> Dict[str, Any]:
        # Bu fonksiyonun içeriği değişmedi
        logger.info(f"Incrementally updating prediction... Model: {config.WORKER_MODEL}")
        new_context_str = "\n---\n".join(new_context_chunks)
        current_value_str = json.dumps(current_value_content, ensure_ascii=False, indent=2)

        update_prompt = f"""
        ROLE:
        You are an intelligence update analyst. Your task is to update an existing finding based on new information.

        ORIGINAL TASK:
        \"{prediction_prompt}\"

        EXISTING DATA (The current value of the prediction in its source language):
        ```json
        {current_value_str}
        ```

        NEW INFORMATION (A new document's content):
        ---
        {new_context_str}
        ---

        YOUR TASK:
        1.  Carefully analyze the NEW INFORMATION in relation to the ORIGINAL TASK.
        ... (rest of the prompt is unchanged) ...
        """
        try:
            response = self.client.chat.completions.create(
                model=config.WORKER_MODEL,
                messages=[{"role": "system", "content": update_prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Error during prediction update: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

llm_gateway = LLMGateway()