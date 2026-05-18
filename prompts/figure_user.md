Inspect page {{page_number}} of this scientific paper.

Nearby extracted page text:
{{page_text}}

Return JSON with exactly this shape:
{
  "figures": [
    {
      "type": "figure|table|plot|diagram|screenshot|equation|other",
      "label": "visible label such as Figure 2 or Table 1, or short fallback label",
      "title": "short descriptive title",
      "bbox_pct": [x0, y0, x1, y1],
      "caption": "visible caption or nearby caption text",
      "explanation": "plain explanation of the main scientific point: what the visual shows, including results, comparisons, variables, or evidence when visible; not a full inventory of visible details",
      "why_it_matters": "how this visual supports, limits, or clarifies the paper's argument or evidence",
      "uncertainty": "what may be ambiguous or hard to read"
    }
  ]
}

Bounding boxes must be percentages from 0 to 100 relative to the page image: left, top, right, bottom.
Group multi-panel figures as one figure unless the panels make separate claims.
Ignore ordinary body-text paragraphs, headers, footers, page numbers, and reference-list entries.
Include tables if they carry experimental results or comparisons.
Do not spend space on incidental layout, colors, icons, or decorative details unless they change the scientific interpretation.
Use the caption and nearby page text to explain what claim the visual is evidence for. Refine smaller details only when they are essential to that claim.
