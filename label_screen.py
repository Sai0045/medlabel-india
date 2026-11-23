"""Simple medicine-label reader, shared by the two student applications."""
import hashlib
from pathlib import Path

import streamlit as st

from label_questions import answer_question, reference_answer, upload_passages
from label_rag import candidates, explanation
from label_patient import QUESTIONS, NO_USE, CETIRIZINE, INDIA_CETIRIZINE
from reference import lookup, SCHEDULE
from scan import scan


def clear_reading():
    for key in list(st.session_state):
        if key.startswith(("scan_", "words_", "page_", "pick_", "confirm_", "faq_", "source_")) or key in {"reading", "confirmed", "qa_result"}:
            st.session_state.pop(key, None)
    st.session_state["upload_version"] = st.session_state.get("upload_version", 0) + 1


def forget_match():
    st.session_state.pop("confirmed", None)
    st.session_state.pop("qa_result", None)


def questions(pages, key, match=None, printed=""):
    st.subheader("Ask a question")
    source = "Uploaded file"
    if match:
        source = st.radio("Answer from", ("Uploaded file", "Medicine reference"), horizontal=True,
                          key="source_"+key, index=1)
    scope = (key, source)
    selection = None
    if source == "Medicine reference" and match[0] == "product":
        selection = st.selectbox("Common questions", list(QUESTIONS.values()), index=None,
                                 placeholder="Choose a question about this medicine", key="faq_"+key,
                                 on_change=lambda: st.session_state.pop("qa_result", None))
    with st.form("ask_"+key):
        question = st.text_input("Your question", max_chars=400, placeholder="For example, what is the strength?")
        asked = st.form_submit_button("Get answer")
    if asked and question.strip():
        with st.spinner("Checking the source…"):
            if source == "Uploaded file":
                response, citation = answer_question(question, upload_passages(pages))
            else:
                response, citation = reference_answer(question, *match, printed)
        st.session_state["qa_result"] = (scope, question, response, citation)
    saved = st.session_state.get("qa_result")
    if selection and (not saved or saved[0] != scope):
        reply, citation = reference_answer(selection, *match, printed)
        saved = (scope, selection, reply, citation)
    if saved and saved[0] == scope:
        with st.container(border=True):
            st.caption(saved[1])
            st.text(saved[2])
            if saved[3]:
                st.text(saved[3])


def show(name):
    st.set_page_config(page_title=name, page_icon=":material/medication:", layout="centered")
    st.html("""<style>
        .stMainBlockContainer {max-width: 51rem; padding-top: clamp(3rem,7vw,5.5rem)}
        h1 {letter-spacing:-.045em;font-weight:750}
        h2,h3 {letter-spacing:-.025em}
        [data-testid="stFileUploaderDropzone"] {min-height:7rem;border:1px dashed #688f87;border-radius:1rem}
        [data-testid="stText"] {font-family:inherit;font-size:1rem;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}
        [data-testid="stCaptionContainer"] {color:#435c57}
        [data-testid="stExpander"] {border-radius:.8rem}
        </style>""")
    st.title(name)
    st.write("Photograph the printed side of a medicine strip, box or bottle, or upload its PDF. Confirm the name to see what it helps with.")
    consent = st.checkbox("Allow this app to read my file on this host.", key="privacy", on_change=clear_reading)
    st.caption("Cover names and phone numbers. Your file is read on this host and stays in this session.")
    upload = st.file_uploader("Medicine label", type=["jpg", "jpeg", "png", "pdf"], disabled=not consent,
                              key=f"upload_{st.session_state.get('upload_version', 0)}",
                              help="Choose a clear JPG, PNG or PDF of up to 10 MB.")
    st.caption(f"{name} provides educational information from medicine labels and reference documents. It does not provide medical diagnosis, prescriptions, or personalized treatment advice.")
    if not consent or upload is None:
        st.session_state.pop("reading", None)
        forget_match()
        return
    data = upload.getvalue()
    file_id = hashlib.sha256(data).hexdigest() + Path(upload.name).suffix.lower()
    if st.session_state.get("reading", (None,))[0] != file_id:
        forget_match()
        st.session_state.pop("reading",None)
        with st.spinner("Reading the label…"):
            try:
                pages = scan(data, upload.name)
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state.reading = (file_id, pages)
    pages = st.session_state.reading[1]
    page = 1
    if len(pages) > 1:
        page = st.selectbox("Page with the medicine name", range(1, len(pages)+1), key="page_"+file_id, on_change=forget_match)
    with st.expander("Check or correct the scanned words"):
        text = st.text_area("Words on the pack", value=pages[page-1]["text"], key=f"words_{file_id}_{page}", height=120, on_change=forget_match)
    key = hashlib.sha256(f"{file_id}/{page}/{text}".encode()).hexdigest()
    brands, generics = lookup(text)
    options = []
    for brand in brands:
        options.append(("leaflet", brand, brand["brand"] + " · manufacturer leaflet"))
    for product in candidates(text):
        options.append(("product", product, f"{product['name']} · {product['maker']}"))
    for generic in generics:
        options.append(("generic", generic, f"{generic['name']} · generic name · entry {generic['entry']}"))
    if not options:
        st.session_state.pop("confirmed", None)
        st.info("No matching medicine found. Check the scanned words above. You can still ask about the uploaded file.")
        questions(pages, key)
        return
    labels = [option[2] for option in options]
    for i, (kind, record, label) in enumerate(options):
        if labels.count(label) > 1 and kind == "product":
            options[i] = (kind, record, f"{label} · {record['salt']} · {record['source_id']}")
    st.subheader("Does this match your pack?")
    pick = 0
    if len(options) > 1:
        pick = st.selectbox("Compare the name, strength and form", range(len(options)),
                            format_func=lambda i: options[i][2], key="pick_"+key, on_change=forget_match)
    else:
        st.text(options[0][2])
    kind, record, _ = options[pick]
    if kind == "product":
        st.caption("Composition on record")
        st.text(record["salt"])
    match_key = f"{key}/{pick}"
    if st.button("Yes, show medicine information", type="primary", key="confirm_"+match_key):
        st.session_state["confirmed"] = match_key
    if st.session_state.get("confirmed") != match_key:
        questions(pages, key)
        return

    if kind == "product":
        result = explanation(record["rowid"], text)
        patient = result["patient"]
        with st.container(border=True):
            st.subheader(record["name"])
            st.markdown("**What the printed ingredient helps with**" if patient["ingredient_only"] else "**What it helps with**")
            st.text(result["use"] or NO_USE)
            if result["use"]:
                st.caption(patient["use_source"])
                if patient["url"]:
                    st.link_button("Read the source", patient["url"])
            st.markdown("**Active ingredients and strength**")
            st.text((patient["composition"] or record["salt"]).replace(" | ", "\n"))
        if result["effects"]:
            with st.expander("Possible side effects"):
                st.text(result["effects"])
                st.caption(patient["source"])
        with st.expander("Pack details and sources"):
            st.text(f"{record['name']}\nManufacturer: {record['maker']}\nPack: {record['pack']}\n{patient['source']}")
            if patient["quote"]:
                st.caption("Supporting words in the patient Q&A")
                st.text(patient["quote"])
            if patient["evidence"]:
                st.caption("Supporting text in the product catalogue")
                st.text(patient["evidence"])
            st.caption(result["mode"])
            st.write("The supplied catalogue gives no publisher or update date. Compare it with your pack.")
    elif kind == "leaflet":
        st.subheader(record["brand"])
        st.markdown("**What it helps with**")
        st.text(record["use"])
        with st.expander("Ingredients and warnings"):
            st.text(record["description"])
            st.text(record["caution"])
        st.link_button("Read the Indian product leaflet", record["url"])
    else:
        st.subheader(record["name"])
        if record["name"] == "Cetirizine":
            st.markdown("**What oral cetirizine helps with**")
            st.text(CETIRIZINE)
            st.link_button("Read the Indian cetirizine leaflet", INDIA_CETIRIZINE)
        st.write("This generic name appears in the 2022 Indian essential medicines list.")
        st.text(SCHEDULE["section_guide"][record["entry"].split(".")[0]]["topic"])
        if record["forms"]:
            st.text(record["forms"])
        st.link_button(f"Read Gazette page {record['page']}", SCHEDULE["source_url"] + f"#page={record['page']}")
    st.caption("For learning. Ask a doctor or pharmacist how to take your medicine.")
    questions(pages, match_key, (kind, record), text)
