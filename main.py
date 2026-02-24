import streamlit as st
from ppt_data_gen import slide_data_gen
from ppt_gen import ppt_gen

st.title("PPT Generator")
st.caption("Generation can take a few minutes because multiple model calls are made per presentation.")

with st.form("generate_form", clear_on_submit=False):
    topic = st.text_input("Enter a topic:")
    submitted = st.form_submit_button("Generate")

if submitted:
    if not topic.strip():
        st.warning("Please enter a topic.")
    else:
        with st.spinner("Generating presentation..."):
            try:
                data = slide_data_gen(topic)
                ppt_file = ppt_gen(data)
            except Exception as exc:
                st.error(str(exc))
                st.info(
                    "Tip: For LM Studio set `PPT_LLM_PROVIDER=lm_studio` and "
                    "`PPT_LLM_BASE_URL=http://127.0.0.1:1234` before starting Streamlit."
                )
            else:
                file_name = "Presentation.pptx"
                st.download_button(
                    label="Download Presentation",
                    data=ppt_file,
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
