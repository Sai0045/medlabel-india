# MedLabel India

## College project report

An Indian medicine strip may show a brand name in large letters and its ingredients in much smaller type. MedLabel India lets a student photograph the printed words, confirm which pack they have and read the information attached to that product. The screen also accepts a leaflet PDF. The app is for education. An individual’s dose and suitability require a qualified clinician or pharmacist.

## Walkthrough

1. Cover any personal details. Allow the app to process the file on its host and upload a clear picture of one pack.
2. Compare the proposed name, form, ingredients and strength with the pack. For a PDF with several pages, select the relevant page. If a letter or number was misread, expand **Check or correct the scanned words**.
3. Select **Yes, show medicine information**. Read the result immediately below the upload. Open the source for its record ID or original leaflet. Uploading a new photo, changing the words or withdrawing consent clears the confirmation.

## Data and retrieval

The supplied CSV and JSONL describe the same 253,973 product records. The importer checks every paired row and the source IDs before indexing it. These are records in a supplied snapshot. They do not establish complete Indian market coverage, regulator approval, present-day pack composition or a clinically reviewed indication. The original files do not give individual product source URLs, authors or revision dates. The four compressed index pieces and the two original file digests are in the catalogue inventory. Full source files are unnecessary to run the app.

OCR reads the picture on the host. A text PDF can supply words directly, while scanned pages go through OCR. SQLite FTS5 uses BM25 to retrieve candidate titles and brands. Exact title matches, printed form, strengths, units and variant words narrow the candidates. A user compares and confirms the identity. A second query retrieves passages exclusively by the confirmed product’s ID. The display presents the salt, strength when present, manufacturer and pack fields. For verified leaflet matches, the app can use the manufacturer’s cited leaflet. The generic reference covers 459 entries of the Indian Gazette.

The importer keeps an introductory use sentence when it explicitly names this exact product and passes conservative text filters. It can keep a short following explanation and an associated side-effect list. This retained 111,438 passages for 53,251 products. The remaining 200,722 can still display structured label details. A row-level identity check cannot establish medical correctness. The app displays the publisher limitation beside the source. It excludes supplied interaction text, prices and dosing instructions. Document content is rendered as text. The app sends no uploads to external inference services.

The bundled FLAN-T5-small model runs on the host CPU. It generates an answer from the confirmed product’s retrieved sentences. If the answer matches a sentence or a unique phrase within one, the app displays the complete source sentence. It falls back to a retrieved excerpt when it cannot verify the generated text. No API key or model download is needed at runtime.

## Examples and results

| Example | Expected observation |
|---|---|
| Upload `examples/dolo-650.png` | Actual OCR reads the teaching label. Confirm Dolo 650 Tablet to see the composition, use and source `med_58235`. |
| Upload `examples/pan40.pdf` | Text extraction finds the PAN 40 formulation. Confirm the manufacturer leaflet and open Alkem’s source. |
| Upload `examples/scanned-paracetamol.pdf` | A PDF page containing only an image goes through OCR. The generic Gazette entry provides its own page reference. |
| Correct the scanned words to `Arpimune ME 50mg Capsule` | Record `med_601` has a description naming a different product. The app withholds that use and side effects. |
| Change the ingredient, strength or unit in the Dolo example | The contradictory Dolo record is excluded. An unknown product gives a message asking for a clearer label or correction. |

The repeatable catalogue experiment takes every 3,503rd row starting at row 1. With 73 full typed titles, the expected source record ranked first in 73 cases. With the final word removed from each title, the source record ranked first in 58 cases and within the first five in 60. Six negative controls passed. The complete queries, expected IDs and retrieved IDs are in the results file. The samples come from the index itself. These values measure catalogue retrieval on typed text. They do not measure performance on photographs taken by students. Real glare, folds, languages other than English script, look-alike packs and ambiguous snippets remain important limitations. Independent medical review and clinical-use validation have not been performed.

All twelve workflow tests passed locally, including FLAN-T5 generation, fallback, and questions from uploaded files or confirmed references. The saved Dolo run records the actual OCR method, retrieved sentences and model output mode. The automated workflow suite uses the teaching fixtures to exercise actual image OCR, text and scanned PDFs, invalid files, name and strength checks, the confirmation boundary, cited answers and reset. No patient records or real-life pack photos were used in this evaluation.

## File guide

| Files | Contents |
|---|---|
| `app.py`, `label_screen.py` | Entry point and single-screen upload, correction, confirmation and results. |
| `reader_model/` | Quantized encoder and decoder, tokenizer, pinned model revision, file hashes and Apache 2.0 licence. |
| `scan.py`, `tools/vision_ocr.swift` | File and image checks, bounded worker, PDF text or image OCR. The optional Swift helper uses Apple Vision. Linux uses English Tesseract. |
| `label_rag.py`, `label_generator.py` | Product retrieval, ingredient/strength checks, confirmed-ID passage retrieval and evidence-constrained response. |
| `catalogue/manifest.json`, `catalogue/part-*.gz` | Counts, input and index checksums, and the ready-to-use compressed search database. Only this reference database is written to temporary storage. |
| `tools/build_catalogue.py`, `tools/evaluate_catalogue.py`, `tools/verify_demo.py` | Pair and validate the original files, rebuild the index, reproduce the retrieval experiment, and record actual example OCR and its cited answer. |
| `reference.py`, `data/indian_brands.json`, `data/indian_schedule.json` | Five manufacturer-leaflet formulations and Indian generic references with page links. |
| `examples/` | Dolo and paracetamol teaching images, a PAN 40 text PDF and a paracetamol scanned PDF. These are typeset fixtures. |
| `tests/test_workflow.py`, `evaluation/catalogue_results.json`, `evaluation/demo_result.json` | Automated workflow tests and measured retrieval results. |
| `requirements.txt`, `packages.txt`, `.streamlit/config.toml` | Python dependencies, Linux OCR dependencies, upload limits and telemetry settings. |
| `.gitignore`, `.gitattributes` | Ignore secrets, environments and compiled helpers. Keep images and PDFs as binary files. |
| `README.md`, `PROJECT_REPORT.md` | Clone/run/personalisation guide and this report. |

## Source documents

The generic entries refer to the Indian Schedule I notification. The five leaflet formulations cover PAN 20, PAN 40, PAN-D, Crocin Advance and Crocin 650. For the larger supplied catalogue, use the displayed source ID and one-based CSV data row or JSONL line to locate the original. [Gazette of India](https://nppa.gov.in/storage/uploads/pdf/240231-1pdf-5c368fdb58fe07ad7ece3b7cf2542d0d.pdf#page=59) · [PAN tablets](https://www.alkemlabs.com/pdf/adverse/PAN.pdf) · [PAN-D](https://www.alkemlabs.com/pdf/adverse/PAN%20D.pdf) · [Crocin Advance](https://www.crocin.com/content/dam/cf-consumer-healthcare/panadol/en_in/documents/Crocin%20advance.pdf) · [Crocin 650](https://www.crocin.com/content/dam/cf-consumer-healthcare/panadol/en_in/documents/Crocin%20650.pdf)

## Student contribution

Add your name, college, department, term and guide. Describe the changes you actually made, commits you can demonstrate, sources you checked, and tests you personally ran. Credit the supplied starter and assistance in line with your college rules. One useful viva demonstration is to change 650 mg to 650 mcg and explain which stage excludes the candidate.

Model source and redistribution terms are recorded in `reader_model/manifest.json` and `reader_model/LICENSE`. [Google model card](https://huggingface.co/google/flan-t5-small) · [Pinned ONNX conversion](https://huggingface.co/Xenova/flan-t5-small/tree/311454e83bc784267fd7eef5940ee854144abbec)

## Ask a question

After uploading an image or PDF, type a question in **Ask a question** and press **Get answer**. Before confirmation, the source is the original upload, including when the brand is unknown. Answers quote a matching line and show its page and line number. For a multi-page leaflet you can ask about a particular page. After confirmation, **Medicine reference** is selected. Switch back to **Uploaded file** at any time.

Try **What is the strength?** with `examples/pan40.pdf`. The upload answers **Pantoprazole 40 mg** on page 1, line 2. It has no answer to **What is it used for?**. Selecting the confirmed manufacturer leaflet makes its documented use available. Questions and private upload text are processed on the app host and kept out of shared model caches. OCR can misread characters. Check important wording on the original file. The app declines personal dosing advice.

The `label_questions.py` module retrieves candidate lines for the question from the selected source and passes the eligible lines to FLAN-T5. It quotes a complete source passage, asks for clarification when multiple field values match, and declines unsupported questions. To repeat the five saved questions and inspect the observed answers and citations in `evaluation/question_results.json`, run `python tools/evaluate_questions.py`.

## Patient reference and common uses

Photograph the printed name and ingredients or use `examples/cetzine-10.png`, the included classroom label. Confirm **Cetzine Tablet**. The reader explains that cetirizine helps with sneezing and a runny nose caused by allergies. Select **What are the common side effects?** to see the catalogue's answer **Sleepiness**, with record `med_33942`. Switch to **Uploaded file** and ask **What is the strength?** to get the actual printed text and its page and line. [Indian Cetzine prescribing information](https://india-pharma.gsk.com/media/kdbnpjsp/cetzine-tablet-and-cetzine-suspension.pdf#page=1)

The extra files describe the same 253,973 products and provide eight questions for each. The importer compared all 2,031,784 answers in the CSV and JSONL, validated each product against the previous catalogue and verified that the gzip copy expands to the same JSONL. It accepted 252,311 ingredient breakdowns and 36,339 product-associated side-effect lists. Agreement between supplied files checks consistency. The files lack a named clinical reviewer and do not establish current Indian market coverage.

The reader first looks for a matching Indian product leaflet. Where product-specific catalogue text and the patient question agree on a narrow indication, it can give that use in plain language. The build found 185 such product rows. Another rule can show an ingredient-level explanation when the printed name, strength and tablet form support it. The build flagged 2,695 candidate rows for this additional check. Counts can overlap. An example is telmisartan for high blood pressure. Records without supported use or effects say what information is missing. The source panel identifies the evidence for each answer. [India Hypertension Control Initiative](https://cdn.who.int/media/docs/default-source/india-news/india-hypertension-control-initiative/cvh-hpertension-india.pdf)

Six FAQ topics concern timing, meals, missed doses, pregnancy or breastfeeding, alcohol, and serious risks or interactions. The app directs these questions to the pack leaflet or a pharmacist. The dataset repeats broad drug-class answers, and some conflict with Indian product instructions. For example, the supplied meal advice for Augmentin 625 Duo conflicts with section 4.2 of its leaflet. The app excludes that advice. [Augmentin Duo Indian prescribing information](https://india-pharma.gsk.com/media/3wpapw52/augmentin-duo-tablets.pdf#page=2)

`label_patient.py` reads the confirmed record and the curated Indian references. `catalogue/patient.sqlite` contains the derived evidence. `catalogue/patient_manifest.json` lists the counts, the eight questions and each input hash. `tools/build_patient_catalogue.py` recreates the index when the original downloads are available. `tools/evaluate_patient.py` exercises real image OCR, the eight FAQ topics, unsupported information and source isolation. The expected answers, actual answers and citations are in `evaluation/patient_results.json`. All 12 checks passed in the recorded run. Neither these checks nor the small typeset fixture set establish clinical accuracy.

To reproduce the patient evaluation with the included index, run `python tools/evaluate_patient.py`. To rebuild the derived patient index first, run this command from the project folder with your download paths.

```sh
python tools/build_patient_catalogue.py /path/to/indian_medicines_qa_patient_complete.csv /path/to/indian_medicines_rag_patient_documents.jsonl --gzip-mirror /path/to/indian_medicines_rag_patient_documents.jsonl.gz
```
