import streamlit as st
from ppt_data_gen import slide_data_gen
from ppt_gen import ppt_gen

st.title("PPT Generator")
st.caption("Generation can take a few minutes because multiple model calls are made per presentation.")

with st.form("generate_form", clear_on_submit=False):
    topic = st.text_input("Enter a topic:")
    content_slide_count = st.number_input(
        "Number of content slides",
        min_value=1,
        max_value=20,
        value=7,
        step=1,
        help="This count excludes title, overview, and thank-you slides.",
    )
    extra_instructions = st.text_area(
        "Extra instructions (optional)",
        placeholder="e.g. Keep it technical, focus on risks, max 2 bullets per slide.",
    )
    submitted = st.form_submit_button("Generate")

progress_message = st.empty()
progress_bar = st.empty()

if submitted:
    if not topic.strip():
        st.warning("Please enter a topic.")
    else:
        try:
            progress_message.info("Starting generation...")
            progress = progress_bar.progress(0)

            def update_progress(message, value=None):
                progress_message.info(message)
                if value is not None:
                    progress.progress(min(max(value, 0.0), 1.0))

            data = slide_data_gen(
                topic,
                slide_count=int(content_slide_count),
                extra_instructions=extra_instructions,
                progress_callback=update_progress,
            )
            update_progress("Building PPTX file...", 0.98)
            ppt_file = ppt_gen(data)
            progress.progress(1.0)
            progress_message.success("Presentation is ready.")
        except Exception as exc:
            progress_bar.empty()
            progress_message.error(str(exc))
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
