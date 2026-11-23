"""Run the included teaching image through actual OCR, matching and answer retrieval."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from label_rag import candidates, explanation
from scan import scan
from label_generator import prediction_for


if __name__ == "__main__":
    sample = ROOT / "examples/dolo-650.png"
    page = scan(sample.read_bytes(), sample.name)[0]
    matches = candidates(page["text"])
    assert matches and matches[0]["source_id"] == "med_58235"
    # A test selects the expected identity, corresponding to the user confirmation in the UI.
    result = explanation(matches[0]["rowid"])
    assert result["use"] and result["use"] in [p["excerpt"] for p in result["passages"]]
    evidence = {"fixture":sample.name,"source_id":matches[0]["source_id"],"read":page,
                "mode":result["mode"],"selected_use":result["use"],"retrieved":result["passages"]}
    evidence["model_context"] = result["model_context"]
    evidence["model_generated"] = prediction_for(matches[0]["name"], tuple(result["model_context"]))
    (ROOT / "evaluation/demo_result.json").write_text(json.dumps(evidence, indent=2)+"\n")
    print(evidence["source_id"], evidence["mode"])
