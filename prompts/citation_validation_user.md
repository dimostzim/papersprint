Review these extracted citation candidates.

Return JSON with exactly this shape:
{
  "rejected_contexts": [
    {
      "citation_id": "id from input",
      "context_index": 0,
      "reason": "short reason"
    }
  ]
}

Rules:
- Reject only when the marker is clearly not an in-text citation or clearly does not point to the provided reference.
- Keep normal numeric citations such as [6], [1, 2], and [4-6].
- Keep normal author-year citations such as Smith et al. 2024, Smith et al. (2024), and (Smith and Jones 2024).
- Do not reject a citation just because the surrounding sentence is technical, biomedical, or computational.
- If unsure, keep it by omitting it from rejected_contexts.
- Return only rejected contexts. Do not return kept contexts.

Citation candidates:
{{candidates_json}}
