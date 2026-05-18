Analyze this paper for a fast-reading interface.

Return JSON with exactly this shape:
{
  "title": "paper title",
  "overview": "3-5 sentence plain summary",
  "background_notes": ["3-5 short beginner-friendly notes explaining early terms, acronyms, datasets, or concepts needed to read this paper"],
  "key_takeaways": [
    {
      "text": "concrete takeaway with bracketed plain-language clarification when a technical term needs it",
      "supporting_excerpt": "exact copied paper passage that best supports this takeaway, optional",
      "highlight_ids": ["ids of returned highlights that support this takeaway, optional"]
    }
  ],
  "not_shown": ["1-3 important things the paper does not show or should not be over-interpreted as showing"],
  "code_availability": ["1-2 notes on whether code, data, models, or reproduction artifacts appear released and usable"],
  "reviewer_questions": ["3-5 concrete questions or clarification requests a critical reviewer would ask"],
  "read_this_first": ["3-5 specific paper areas or excerpts to inspect first"],
  "glossary": [{"term": "term or acronym", "definition": "short paper-specific definition"}],
  "highlights": [
    {
      "id": "h1",
      "label": "problem|solution|novelty|method|benchmarking|result|ablation|hyperparams|tradeoff|limitation|failure",
      "snippet": "one complete sentence copied exactly from the paper text, usually 90-260 characters",
      "reason": "why this excerpt helps fast comprehension",
      "comment": "short plain-language explanation of what this highlight means and why it matters"
    }
  ],
  "questions": ["useful follow-up question"]
}

Highlight requirements:
- Background notes should define or contextualize important terms that appear early in the paper. Keep them short, practical, and specific to this paper.
- Key takeaways should be understandable to a researcher outside this exact subfield. Keep the paper-specific claim, but add a short bracketed explanation when needed, e.g. [plain-language meaning]. Avoid assuming the reader already knows the benchmark, assay, model family, or domain acronym.
- For each key takeaway, include a supporting_excerpt when the paper contains a local passage that lets a reader verify the takeaway. Choose the shortest exact copied passage with enough surrounding context to re-read the evidence naturally: it may be one sentence, multiple connected sentences, or a short paragraph. Do not force a fixed length. Leave supporting_excerpt empty only when no local text target supports the takeaway.
- Takeaway supporting_excerpt should often include or overlap one or more returned highlights when those highlights are important evidence for the takeaway, but do not force a highlight link when a separate passage is better evidence.
- For each highlight, provide a stable id such as h1, h2, h3. When a takeaway depends on returned highlights, put those ids in highlight_ids.
- When a figure or table is central evidence for a takeaway, reference it briefly in the takeaway and/or supporting_excerpt, e.g. "(Fig. 2)" or "(Table 1)". Do not force figure references when the text does not support them.
- Not-shown items should prevent common over-reading: state what the paper did not demonstrate, did not compare, did not validate, or did not make usable.
- Code availability should use only paper text. Say when release or usability is unclear.
- Reviewer questions should be specific requests a reviewer would ask the authors to clarify, test, release, or bound.
- Return enough highlights for a reader to follow the paper's argument without reading every section; do not optimize for the absolute minimum.
- Treat highlight labels as a vocabulary, not a checklist. Use only labels that have explicit useful evidence in this paper. Do not add computational-paper-specific labels such as benchmarking, hyperparams, ablation, or failure when the paper does not actually contain those details.
- Add a highlight only if it changes the reader's understanding of the problem, solution, novelty, method, evidence, tradeoff, failure mode, or claim limitation.
- Abstract highlights are allowed when they provide useful orientation, especially for problem, solution, novelty, and main result.
- Do not stop after abstract-level summary. Include concrete body passages for the contribution, mechanism, evaluation, reproducibility details, and limits when they exist.
- If an abstract sentence is the clearest compact statement of the paper's contribution or result, include it; otherwise prefer the more specific body sentence.
- Do not highlight title, author, affiliation, contact, availability, license, preprint, or header/footer text.
- Do not cluster the set in the opening motivation; later method, evaluation, result, hyperparams, and this-paper limitation passages are usually more useful.
- Use the problem label for the task, problem statement, motivating failure mode, or gap that this paper addresses.
- Use the solution label for the paper's proposed system, model, dataset, workflow, intervention, or main answer to the problem.
- Use the novelty label for contribution claims: new systems, datasets, benchmarks, architectures, workflows, evaluation framing, or claimed differences from prior work.
- Use the method label for this paper's data construction, model, system, protocol, evaluation design, or analysis procedure.
- Use the benchmarking label for benchmark construction, benchmark datasets, evaluation setup, baselines, metrics, leaderboards, test splits, scoring protocols, or head-to-head comparisons.
- Use the result label for this paper's findings, measured evidence, comparisons, rankings, or empirical interpretations.
- Use the ablation label for controlled component-removal, sensitivity, variant, or comparison-without-a-component studies.
- Use the hyperparams label for hyperparameters, model choices, runtime, hardware, training cost, model size, data scale, package/environment details, execution budgets, validation checkpoints, or other reproducibility-critical implementation details.
- Use the tradeoff label for the catch: costs, constraints, assumptions, usability limits, or cases where the solution buys one thing by giving up another.
- Use the limitation label only for limitations of this paper's own data, method, evaluation, assumptions, claims, or generalizability. Do not label weaknesses of prior work or background motivation as limitation; label those as problem when they define the problem.
- Use the failure label for reported failure modes, negative cases, error analysis, or situations where the proposed approach breaks down.
- Prefer a balanced guided skim across relevant labels when those facets are present, but do not force every label or invent missing facets.
- Before finalizing, check whether the paper contains explicit benchmarking, hyperparams, ablation, failure, or tradeoff evidence. If one exists, is useful for understanding this paper, and is absent, replace a redundant generic problem/method/result highlight with the best exact sentence for that facet. If that evidence does not exist, leave the label unused.
- Stop when the next highlight repeats an idea already covered.
- Highlights must be complete sentence-level excerpts. Most useful highlights are single sentences; use a compact multi-sentence excerpt only when the claim needs immediate context.
- Avoid adjacent highlights unless they serve different labels.
- Spread highlights across introduction, methods/system, evaluation/results, and limitations/discussion when those sections exist.
- Prefer passages that define the task, name the paper's motivating failure mode, introduce this paper's intervention, explain the mechanism, define the evaluation/baseline/metric, report the main result, state a tradeoff, give reproducibility details, or bound this paper's claim.
- Avoid generic field-motivation sentences unless they create a concrete methodological decision.
- Read-this-first items should help a researcher triage the paper: task, method, evidence, limitations, and claim ceiling.
- Takeaway supporting_excerpt and highlight snippets must be exact copied text from the paper where possible. Do not include page markers such as [Page 2]. Never end an excerpt mid-word or mid-sentence.
- Takeaway supporting_excerpt should usually be broader than a single highlight when local context helps, but do not quote a whole section or a long run of unrelated introduction. It should feel like the natural evidence passage a researcher would inspect after reading the takeaway.
- Highlight snippets must be complete sentence-level excerpts. Most useful highlights are single sentences; use a compact multi-sentence excerpt only when the claim needs immediate context.
- Every returned highlight must include a non-empty comment. The comment should explain the highlighted idea in simpler terms, adding just enough definition or background context for a reader who knows the field lightly. Do not repeat the snippet.

Paper title guess: {{title}}

Paper text:
{{text}}
