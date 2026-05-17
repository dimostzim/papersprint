import fitz

from app.figures import coerce_bbox_pct, crop_figure_image, normalize_figure_items, render_page_image


def test_coerce_bbox_pct_clamps_and_orders_values():
    assert coerce_bbox_pct([90, -5, 10, 120]) == [10.0, 0.0, 90.0, 100.0]
    assert coerce_bbox_pct(["bad", 0, 1, 2]) == [0.0, 0.0, 100.0, 100.0]
    assert coerce_bbox_pct([1, 1, 1.5, 50]) == [0.0, 0.0, 100.0, 100.0]


def test_normalize_figure_items_keeps_structured_visual_notes():
    payload = {
        "figures": [
            {
                "type": "Plot",
                "label": "Figure 1",
                "title": "Result curve",
                "bbox_pct": [10, 20, 80, 70],
                "caption": "Accuracy by method.",
                "explanation": "The plot compares methods.",
                "why_it_matters": "It carries the main result.",
                "uncertainty": "Axis labels are small.",
            },
            {"type": "paragraph", "title": ""},
        ]
    }

    figures = normalize_figure_items(payload, 3)

    assert len(figures) == 1
    assert figures[0]["page_number"] == 3
    assert figures[0]["type"] == "plot"
    assert figures[0]["bbox_pct"] == [10.0, 20.0, 80.0, 70.0]


def test_render_page_and_crop_figure_images(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=240)
    page.insert_text((40, 40), "Figure 1: Example plot")
    page.draw_rect(fitz.Rect(40, 70, 200, 190), color=(0, 0, 0), width=1)
    doc.save(pdf_path)
    doc.close()

    page_image = tmp_path / "page.jpg"
    crop_image = tmp_path / "figure.jpg"

    render_page_image(pdf_path, 1, page_image)
    crop_figure_image(pdf_path, 1, [15, 25, 90, 85], crop_image)

    assert page_image.exists()
    assert crop_image.exists()
    assert page_image.stat().st_size > 0
    assert crop_image.stat().st_size > 0
