"""Generate locally from retrieved passages. Only complete source sentences can reach the screen."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

MODEL = Path(__file__).resolve().parent / "reader_model"


@lru_cache(maxsize=1)
def reader():
    import onnxruntime as ort
    from tokenizers import Tokenizer
    ort.disable_telemetry_events()
    for name, item in json.loads((MODEL / "manifest.json").read_text())["files"].items():
        with (MODEL / name).open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                raise ValueError("The local model failed its integrity check.")
    settings = ort.SessionOptions()
    settings.intra_op_num_threads = 1
    settings.inter_op_num_threads = 1
    def session(name):
        return ort.InferenceSession(str(MODEL/name), sess_options=settings, providers=["CPUExecutionProvider"])
    return session("encoder_model_quantized.onnx"), session("decoder_model_quantized.onnx"), Tokenizer.from_file(str(MODEL/"tokenizer.json"))


def normalized(text):
    return " ".join(text.casefold().split()).rstrip(".")


@lru_cache(maxsize=256)
def prediction_for(name, passages):
    return predict_question(f"What is {name} used for?", passages)


def predict_question(question, passages):
    """Do not cache user questions or uploaded text across sessions."""
    import numpy as np
    encoder, decoder, tokenizer = reader()
    prompt = (f"Read the following medicine label. {question} "
              "Copy one complete sentence that answers the question. Label: " + " ".join(passages))
    ids = np.array([tokenizer.encode(prompt).ids[:512]], dtype=np.int64)
    mask = np.ones_like(ids)
    state = encoder.run(["last_hidden_state"], {"input_ids": ids, "attention_mask": mask})[0]
    generated = [0]
    for _ in range(55):
        feed = {"input_ids": np.array([generated], dtype=np.int64), "encoder_hidden_states": state,
                "encoder_attention_mask": mask}
        logits = decoder.run(["logits"], feed)[0][0, -1]
        next_token = int(logits.argmax())
        if next_token == 1:  # FLAN-T5 end-of-sequence
            break
        generated.append(next_token)
    return tokenizer.decode(generated[1:], skip_special_tokens=True).strip()


def generate(name, passages):
    prediction = prediction_for(name, passages)
    for sentence in passages:
        if normalized(prediction) == normalized(sentence):
            return sentence, "Local FLAN-T5 · generated answer matched a complete source sentence"
    # The model often returns a short phrase. Keep its complete source sentence, including any negation.
    phrase_words = re.findall(r"\w+", normalized(prediction))
    if len(phrase_words) >= 3:
        phrase = " ".join(phrase_words)
        matches = [s for s in passages if phrase in normalized(s)]
        if len(matches) == 1:
            return matches[0], "Local FLAN-T5 · generated phrase verified in the displayed source sentence"
        for length in range(len(phrase_words) - 1, 2, -1):
            for i in range(len(phrase_words) - length + 1):
                sub = " ".join(phrase_words[i:i+length])
                matches = [s for s in passages if sub in normalized(s)]
                if len(matches) == 1:
                    return matches[0], "Local FLAN-T5 · generated phrase verified in the displayed source sentence"
    return passages[0], "Retrieved excerpt · generated answer did not pass the source check"


def choose(name, passages):
    try:
        return generate(name, tuple(passages))
    except (ImportError, OSError, RuntimeError, ValueError):
        return passages[0], "Retrieved excerpt · local language model unavailable"
