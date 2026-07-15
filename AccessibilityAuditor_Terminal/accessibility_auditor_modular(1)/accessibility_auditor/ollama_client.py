import json
import time

import ollama

from . import config as cfg


def ask_ollama(prompt, image_path=None, num_ctx=4096, num_predict=500):
    user_message = {
        "role": "user",
        "content": prompt
    }

    if image_path is not None:
        user_message["images"] = [str(image_path)]

    print("Calling Ollama...", flush=True)
    start = time.time()

    response = ollama.chat(
        model=cfg.MODEL,
        messages=[
            {
                "role": "system",
                "content": cfg.SYS_PROMPT
            },
            user_message
        ],
        format="json",
        options={
            "temperature": 0,
            "num_ctx": num_ctx,
            "num_predict": num_predict
        }
    )

    print("Ollama finished in", round(time.time() - start, 2), "seconds", flush=True)

    content = response["message"]["content"].strip()

    print("Raw Ollama output:")
    print(content)

    # Remove markdown code fences if the model adds them.
    if content.startswith("```json"):
        content = content.replace("```json", "").replace("```", "").strip()
    elif content.startswith("```"):
        content = content.replace("```", "").strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print("Ollama did not return valid JSON. Using fallback object.", flush=True)

        return {
            "_parse_error": True,
            "raw_output": content,
            "warnings": [
                "Ollama did not return valid JSON."
            ]
        }
