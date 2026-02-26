from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Pt
from pptx.enum.text import PP_ALIGN
from pptx.enum.text import MSO_AUTO_SIZE

import re
import io


def sanitize_string(input_str):
    # Remove non-alphanumeric, underscores, hyphens, and periods
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "", input_str)

    # Replace consecutive periods with a single period
    sanitized = re.sub(r"\.{2,}", ".", sanitized)

    # Ensure the string starts and ends with an alphanumeric character
    sanitized = re.sub(r"^[^A-Za-z0-9]+", "", sanitized)
    sanitized = re.sub(r"[^A-Za-z0-9]+$", "", sanitized)

    # Truncate or pad string to meet the 3-63 character length requirement
    sanitized = sanitized[:63] if len(
        sanitized) > 63 else sanitized.ljust(3, "_")

    return sanitized


def hex_to_rgb(hex_color):
    if not isinstance(hex_color, str) or len(hex_color) != 7 or not hex_color.startswith("#"):
        return None
    try:
        return RGBColor(int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))
    except Exception:
        return None


def apply_slide_background(slide, background_rgb):
    if background_rgb is None:
        return
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = background_rgb


def apply_text_frame_style(text_frame, font_name=None, color_rgb=None, size_pt=None, alignment=None):
    for paragraph in text_frame.paragraphs:
        if font_name:
            paragraph.font.name = font_name
        if color_rgb is not None:
            paragraph.font.color.rgb = color_rgb
        if size_pt is not None:
            paragraph.font.size = Pt(size_pt)
        if alignment is not None:
            paragraph.alignment = alignment


def unpack_presentation_data(data):
    if isinstance(data, dict):
        slide_data = data.get("slides") or []
        style = data.get("style") or {}
        return slide_data, style
    return data, {}


def ppt_gen(presentation_data):
    ppt = Presentation()
    slide_data, style = unpack_presentation_data(presentation_data)
    if not slide_data:
        ppt_stream = io.BytesIO()
        ppt.save(ppt_stream)
        ppt_stream.seek(0)
        return ppt_stream

    background_rgb = hex_to_rgb(style.get("background_color", ""))
    title_color_rgb = hex_to_rgb(style.get("title_color", "")) or hex_to_rgb(style.get("accent_color", ""))
    body_color_rgb = hex_to_rgb(style.get("body_color", ""))
    title_font = style.get("font_title", "")
    body_font = style.get("font_body", "")

    # Title Screen
    curr_slide = ppt.slides.add_slide(ppt.slide_layouts[0])
    apply_slide_background(curr_slide, background_rgb)
    curr_slide.shapes.title.text = slide_data[0][0]
    curr_slide.shapes.title.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    apply_text_frame_style(curr_slide.shapes.title.text_frame, font_name=title_font, color_rgb=title_color_rgb)
    curr_slide.shapes.placeholders[1].text = slide_data[0][1]
    curr_slide.shapes.placeholders[1].text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    apply_text_frame_style(curr_slide.shapes.placeholders[1].text_frame, font_name=body_font, color_rgb=body_color_rgb)

    # Overview
    curr_slide = ppt.slides.add_slide(ppt.slide_layouts[1])
    apply_slide_background(curr_slide, background_rgb)
    curr_slide.shapes.title.text = "Overview"
    curr_slide.shapes.title.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    apply_text_frame_style(curr_slide.shapes.title.text_frame, font_name=title_font, color_rgb=title_color_rgb)
    tframe = curr_slide.shapes.placeholders[1].text_frame
    tframe.clear()
    tframe.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for idx, content in enumerate(slide_data[1]):
        para = tframe.paragraphs[0] if idx == 0 else tframe.add_paragraph()
        para.text = content
        para.level = 1
        if body_font:
            para.font.name = body_font
        if body_color_rgb is not None:
            para.font.color.rgb = body_color_rgb

    # Content Slides
    for curr_slide_data in slide_data[2:]:
        curr_slide = ppt.slides.add_slide(ppt.slide_layouts[1])
        apply_slide_background(curr_slide, background_rgb)
        curr_slide.shapes.title.text = curr_slide_data[0]
        curr_slide.shapes.title.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        apply_text_frame_style(curr_slide.shapes.title.text_frame, font_name=title_font, color_rgb=title_color_rgb)
        tframe = curr_slide.shapes.placeholders[1].text_frame
        tframe.clear()
        tframe.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        for idx, content in enumerate(curr_slide_data[1:]):
            para = tframe.paragraphs[0] if idx == 0 else tframe.add_paragraph()
            para.text = content
            para.level = 1
            if body_font:
                para.font.name = body_font
            if body_color_rgb is not None:
                para.font.color.rgb = body_color_rgb

    # Thank You Screen
    curr_slide = ppt.slides.add_slide(ppt.slide_layouts[2])
    apply_slide_background(curr_slide, background_rgb)
    curr_slide.shapes.placeholders[1].text = "Thank You"

    apply_text_frame_style(
        curr_slide.shapes.placeholders[1].text_frame,
        font_name=title_font,
        color_rgb=title_color_rgb,
        size_pt=96,
        alignment=PP_ALIGN.CENTER,
    )

    # f"{sanitize_string(slide_data[0][0])}.pptx"
    ppt_stream = io.BytesIO()
    ppt.save(ppt_stream)
    ppt_stream.seek(0)

    return ppt_stream
