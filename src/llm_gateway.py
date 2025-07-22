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
        3.  **GENERATE TASK PROMPTS**: For each piece of information needed, create a clear, machine-readable `prediction_prompt` in ENGLISH. Each prompt must be a self-contained, reusable command or question. Also, generate relevant `keywords` for each prompt.
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
                model=config.DECOMPOSER_MODEL,
                messages=[{"role": "system", "content": meta_prompt}],
                response_format={"type": "json_object"}
            )
            analysis_result = json.loads(response.choices[0].message.content)
            # Analiz sonucunu, daha sonra orkestratörde dili bulmak için task'lere ekleyelim
            if 'potential_tasks' in analysis_result:
                for task in analysis_result['potential_tasks']:
                    task['__parent_analysis__'] = {'user_language_code': analysis_result.get('user_language_code')}
            return analysis_result
        except Exception as e:
            logger.error(f"Error during query task decomposition: {e}", exc_info=True)
            return {"user_language_code": "en", "potential_tasks": []}

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

        YOUR REASONING PROCESS (Follow these steps internally before generating the final JSON):
        1.  **Review the Goal:** Look at the ORIGINAL USER QUERY to understand the user's overall intent and language for the response.
        2.  **Map Tasks to Data:** For each task in REQUIRED TASKS, examine the AVAILABLE PRE-EXISTING DATA.
            - If there is an available candidate with a prompt that is a clear and direct semantic match for the required task, mark it for **reuse**.
            - If there are no candidates or the candidates are not a good match, mark the task for **creation**.
        3.  **Plan the Output:** Based on your decisions, plan the final `render_plan` and `predictions` list. Ensure every placeholder in the `render_plan` corresponds to a task in the `predictions` list.

        FINAL OUTPUT (Produce ONLY the following JSON object based on your reasoning):
        - A `render_plan` to structure the answer in the user's language.
        - A `predictions` list detailing whether to `reuse_prediction_id` or create a `new_prediction_prompt` for each placeholder.

        EXAMPLE OUTPUT:
        {{
          "render_plan": [
             {{ "type": "paragraph", "content": "Türkiye'nin başkenti {{capital_city}} şehridir." }},
             {{ "type": "paragraph", "content": "Bu şehrin nüfusu yaklaşık {{capital_population}} kişidir." }}
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
            final_plan = json.loads(response.choices[0].message.content)
            
            # Analiz adımından gelen dili nihai plana ekle
            user_language_code = "en"
            if potential_tasks and '__parent_analysis__' in potential_tasks[0]:
                user_language_code = potential_tasks[0]['__parent_analysis__'].get('user_language_code', 'en')
            
            final_plan['user_language_code'] = user_language_code
            return final_plan

        except Exception as e:
            logger.error(f"Error during plan orchestration: {e}", exc_info=True)
            return {{"render_plan": [], "predictions": [], "user_language_code": "en"}}

    def fulfill_prediction(self, prediction_prompt: str, context_chunks: List[str]) -> Dict[str, Any]:
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