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

    def decompose_query(self, user_query: str, reusable_predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        reusable_text = "No reusable tasks found."
        if reusable_predictions:
            reusable_text = "Here is a list of existing prediction tasks that might be relevant:\n"
            for pred in reusable_predictions:
                reusable_text += f'- ID: {pred["id"]}, Prompt: "{pred["prompt"]}"\n'
        
        meta_prompt = f"""
        ROLE:
        You are an expert, multilingual system architect. Your goal is to create a structured "render plan" for a user query.

        USER QUERY:
        "{user_query}"

        YOUR TASK:
        1.  **DETECT LANGUAGE**: Identify the language of the user's query (e.g., "tr", "en").
        2.  **CREATE RENDER PLAN**: Create a `render_plan` as a JSON array. The plan describes how to display the final answer. Supported `type`s are:
            - "paragraph": For standard text. Use the `content` key. **The content should be formatted using Markdown (e.g., bold, italics, headings #, lists *, blockquotes >).**
            - "list": To iterate over a prediction result. Use `placeholder` for the variable name and `item_template` for the format of each item. Use simple `{{key}}` placeholders in the template. If the list might be empty or contain an error, also include an `empty_message` key. **The `item_template` and `empty_message` should also be Markdown formatted.**
        3.  **GENERATE PREDICTION PROMPT**: For each `placeholder`, define the task. `new_prediction_prompt` must be in ENGLISH.
        4.  **OUTPUT JSON**: Your output MUST be a single, valid JSON object containing the render plan and predictions.

        EXAMPLE OUTPUT:
        {{
          "user_language_code": "tr",
          "render_plan": [
            {{"type": "paragraph", "content": "## İstenen Bilgiler\nİşte istediğiniz bilgiler **Markdown formatında** sunulmuştur:"}},
            {{"type": "list", "placeholder": "items_placeholder", "item_template": "* **{{name}}**: {{description}}", "empty_message": "> *Maalesef, bu konuda herhangi bir detay bulunamadı.*"}}
          ],
          "predictions": [
            {{
              "placeholder_name": "items_placeholder",
              "new_prediction_prompt": "Provide a JSON list of objects with 'name' and 'description' keys for the user's query.",
              "keywords": ["..."]
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
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Error during query decomposition: {e}", exc_info=True)
            return {
                "user_language_code": "en",
                "render_plan": [{"type": "paragraph", "content": "An error occurred while processing your query. Please try again later."}],
                "predictions": []
            }


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
        """
        Mevcut bir prediction'ın kaynak ('en') verisini, yeni gelen bilgi ile günceller.
        Güncellenen verinin çevrilebilir olup olmadığını da yeniden değerlendirir.
        """
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

        IMPORTANT:
        - The UPDATED data you output MUST be in the same language as the EXISTING DATA (source language: '{base_language}'), regardless of the language in the NEW INFORMATION.
        - NEVER change the language of the data unless explicitly told otherwise.

        YOUR TASK:
        1.  Carefully analyze the NEW INFORMATION in relation to the ORIGINAL TASK.
        2.  If the ORIGINAL TASK is to extract a list of items (like benefits, features, steps):
            a.  **Find all relevant items** from both the EXISTING DATA and the NEW INFORMATION.
            b.  **Consolidate and de‑duplicate** them.
            c.  **Add any truly new and distinct items** found ONLY in the NEW INFORMATION to the consolidated list.
            d.  **Provide the complete, updated list.**
            e.  If the NEW INFORMATION is purely redundant or adds no new items/significant modifications to existing ones,
                then respond with \"{{{{\\\"status\\\": \\\"no_change\\\"}}}}\"
        3.  If the ORIGINAL TASK is to extract a single fact (like a definition, a number, a date):
            a.  If the NEW INFORMATION provides a **more accurate, detailed, or different single fact** for the ORIGINAL TASK,
                provide the new fact.
            b.  Otherwise, respond with \"{{{{\\\"status\\\": \\\"no_change\\\"}}}}\"
        4.  **OUTPUT FORMAT**
            Your final output MUST be a single JSON object with:
            - \"status\": one of **\"update\"**, **\"no_change\"**, or **\"error\"**.
            - If \"status\" == \"update\":
                * \"is_translatable\"  (boolean, as in the fulfillment task)
                * \"data\"             (the updated value)
            - If \"status\" == \"no_change\": nothing else is required.
            - If \"status\" == \"error\":
                * \"message\"          (brief error description)

            Example when an update occurs:
            ```json
            {{{{
              \"status\": \"update\",
              \"is_translatable\": true,
              \"data\": [ ... ]
            }}}}
            ```

            Example when no change:
            ```json
            {{{{
              \"status\": \"no_change\"
            }}}}
            ```

            Example on error:
            ```json
            {{{{
              \"status\": \"error\",
              \"message\": \"reason...\"
            }}}}
            ```

        5.  NEVER add explanations or conversational filler. Your output must be ONLY the specified JSON object.
        """

        print("UPDATE PROMPT INPUT:",update_prompt)
        try:
            response = self.client.chat.completions.create(
                model=config.WORKER_MODEL,
                messages=[{"role": "system", "content": update_prompt}],
                response_format={"type": "json_object"}
            )
            print("UPDATE PROMPT OUTPUT:",response.choices[0].message.content)            
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Error during prediction update: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

llm_gateway = LLMGateway()