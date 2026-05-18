import fitz

from app.citations import expand_citation_numbers, extract_citations, ground_citation_rects
from app.paper_processing import ExtractedPaper


def extracted_from_pages(*texts: str) -> ExtractedPaper:
    pages = [
        {
            "page_number": index + 1,
            "width": 600,
            "height": 800,
            "text": text,
        }
        for index, text in enumerate(texts)
    ]
    return ExtractedPaper("Citation paper", "\n\n".join(texts), pages, [])


def test_expand_citation_numbers_handles_lists_and_ranges():
    assert expand_citation_numbers("8-14") == [8, 9, 10, 11, 12, 13, 14]
    assert expand_citation_numbers("7, 8, 11-13") == [7, 8, 11, 12, 13]
    assert expand_citation_numbers("2; 5") == [2, 5]


def test_extract_citations_keeps_short_inline_contexts_and_single_reference():
    extracted = extracted_from_pages(
        "Prior work [1].",
        "References\n[1] A. Reader. 2022. Short Citation. CHI.",
    )

    citations = extract_citations(extracted)

    assert citations[0]["label"] == "[1]"
    assert citations[0]["title"] == "Short Citation"
    assert citations[0]["contexts"][0]["sentence"] == "Prior work [1]."


def test_extract_citations_maps_references_to_inline_contexts():
    extracted = extracted_from_pages(
        (
            "Prior work created paper cards for inline citations [1, 2]. "
            "Later systems extended citation reading with localized contexts [3-4]."
        ),
        (
            "REFERENCES\n"
            "[1] Jane Doe and John Roe. 2020. Paper Cards for Research Readers. CHI.\n"
            "[2] Pat Smith. 2021. Citation Popups in Scholarly PDFs. UIST.\n"
            "[3] Rui Li. 2022. Local Citation Contexts. IUI.\n"
            "[4] A. Kim. 2023. Future Work in Citation Readers. CSCW."
        ),
    )

    citations = extract_citations(extracted)

    assert [citation["label"] for citation in citations] == ["[1]", "[2]", "[3]", "[4]"]
    assert citations[0]["title"] == "Paper Cards for Research Readers"
    assert citations[0]["year"] == "2020"
    assert citations[0]["contexts"][0]["page_number"] == 1
    assert citations[2]["contexts"][0]["marker"] == "[3-4]"


def test_extract_citations_keeps_inline_citations_when_references_are_missing():
    extracted = extracted_from_pages(
        "A reader may still cite prior work in the body before extraction finds the reference list [12]."
    )

    citations = extract_citations(extracted)

    assert citations[0]["label"] == "[12]"
    assert citations[0]["raw_reference"] == ""
    assert citations[0]["context_count"] == 1


def test_extract_citations_maps_author_year_references_to_contexts():
    extracted = extracted_from_pages(
        (
            "CLASH revealed frequent noncanonical binding (Helwak et al. 2013). "
            "A later chimeric eCLIP dataset was described by Manakov et al. (2022)."
        ),
        (
            "References\n"
            "Helwak A, Kudla G, Dudnakova T et al. Mapping the human miRNA "
            "interactome by CLASH reveals frequent noncanonical binding. Cell "
            "2013;153:654-65.\n"
            "Manakov SA et al. Scalable and deep profiling of mRNA targets for "
            "individual microRNAs with chimeric eCLIP. bioRxiv, https://doi.org/ "
            "10.1101/2022.02.13.480296, 2022, preprint: not peer reviewed.\n"
            "Calin GA, Croce CM. MicroRNA signatures in human cancers. Nat "
            "Rev Cancer 2006;6:857-66."
        ),
    )

    citations = extract_citations(extracted)

    assert [citation["label"] for citation in citations] == [
        "Helwak et al. 2013",
        "Manakov et al. 2022",
        "Calin 2006",
    ]
    assert citations[0]["title"] == "Mapping the human miRNA interactome by CLASH reveals frequent noncanonical binding"
    assert citations[0]["contexts"][0]["marker"] == "Helwak et al. 2013"
    assert citations[1]["contexts"][0]["marker"] == "Manakov et al. (2022)"


def test_extract_citations_maps_author_year_mentions_with_comma():
    extracted = extracted_from_pages(
        "Prior work follows Smith et al., 2020.",
        "References\nSmith J et al. Useful citation detection for papers. Nature 2020;1:1-2.",
    )

    citations = extract_citations(extracted)

    assert citations[0]["label"] == "Smith et al. 2020"
    assert citations[0]["contexts"][0]["marker"] == "Smith et al., 2020"


def test_extract_citations_removes_pdf_control_chars_inside_author_names():
    extracted = extracted_from_pages(
        "Noncanonical sites were reported by Klimentov\x13a et al. 2022.",
        (
            "References\n"
            "Klimentova E, Hejret V, Krcmar J et al. miRBind: a deep learning "
            "method for miRNA binding classification. Genes (Basel) 2022;13:2323."
        ),
    )

    citations = extract_citations(extracted)

    assert citations[0]["label"] == "Klimentova et al. 2022"
    assert citations[0]["resolved"] is True
    assert citations[0]["contexts"][0]["marker"] == "Klimentova et al. 2022"
    assert citations[0]["raw_reference"].startswith("Klimentova E")


def test_extract_citations_maps_two_author_mentions_to_contexts():
    extracted = extracted_from_pages(
        "Disease studies discuss signatures in cancer (Calin and Croce 2006).",
        (
            "References\n"
            "Calin GA, Croce CM. MicroRNA signatures in human cancers. Nat "
            "Rev Cancer 2006;6:857-66."
        ),
    )

    citations = extract_citations(extracted)

    assert citations[0]["second_author"] == "Croce"
    assert citations[0]["contexts"][0]["marker"] == "Calin and Croce 2006"


def test_extract_citations_uses_author_year_inline_markers_as_source_of_truth():
    extracted = extracted_from_pages(
        (
            "Automated ML systems include Auto-sklearn (Feurer et al., 2015), "
            "AutoGluon (Erickson et al., 2020), and TPOT (Olson and Moore, 2016)."
        ),
        (
            "References\n"
            "Feurer M, Klein A, Eggensperger K et al. Efficient and robust automated "
            "machine learning. Advances in neural information processing systems 2015.\n"
            "2024. This wrapped continuation looks numeric but is not a numbered reference.\n"
            "Erickson N et al. AutoGluon-Tabular: Robust and accurate AutoML. arXiv 2020.\n"
            "Olson RS, Moore JH. TPOT: A tree-based pipeline optimization tool. JMLR 2016."
        ),
    )

    citations = extract_citations(extracted)

    assert [citation["label"] for citation in citations] == [
        "Erickson et al. 2020",
        "Feurer et al. 2015",
        "Olson 2016",
    ]
    assert all(citation["resolved"] for citation in citations)
    assert citations[0]["contexts"][0]["marker"] == "Erickson et al., 2020"
    assert citations[1]["contexts"][0]["marker"] == "Feurer et al., 2015"
    assert citations[2]["contexts"][0]["marker"] == "Olson and Moore, 2016"
    assert "AutoGluon-Tabular" in citations[0]["raw_reference"]


def test_extract_citations_keeps_unresolved_author_year_inline_markers():
    extracted = extracted_from_pages(
        "AutoML tools can be brittle in biomedical settings (Feurer et al., 2015)."
    )

    citations = extract_citations(extracted)

    assert citations[0]["label"] == "Feurer et al. 2015"
    assert citations[0]["resolved"] is False
    assert citations[0]["raw_reference"] == ""
    assert citations[0]["contexts"][0]["marker"] == "Feurer et al., 2015"


def test_extract_citations_ignores_years_that_are_not_author_year_markers():
    extracted = extracted_from_pages(
        "University of Malta, Msida MSD 2080, Malta. In 2013, sequencing got cheaper."
    )

    assert extract_citations(extracted) == []


def test_extract_citations_keeps_real_author_year_when_false_years_are_nearby():
    extracted = extracted_from_pages(
        (
            "University of Malta, Msida MSD 2080, Malta. "
            "In 2013, sequencing got cheaper. "
            "CLASH revealed frequent noncanonical binding (Helwak et al. 2013)."
        ),
        (
            "References\n"
            "Helwak A, Kudla G, Dudnakova T et al. Mapping the human miRNA "
            "interactome by CLASH reveals frequent noncanonical binding. Cell "
            "2013;153:654-65."
        ),
    )

    citations = extract_citations(extracted)

    assert [citation["label"] for citation in citations] == ["Helwak et al. 2013"]
    assert citations[0]["contexts"][0]["marker"] == "Helwak et al. 2013"


def test_extract_citations_ignores_month_journal_and_funding_dates_when_references_exist():
    extracted = extracted_from_pages(
        (
            "The article was downloaded on 16 May 2026. "
            "The footer says Bioinformatics, 2025. "
            "This work was supported by Fund 2020. "
            "The real citation is (Helwak et al. 2013)."
        ),
        (
            "References\n"
            "Helwak A, Kudla G, Dudnakova T et al. Mapping the human miRNA "
            "interactome by CLASH reveals frequent noncanonical binding. Cell "
            "2013;153:654-65."
        ),
    )

    citations = extract_citations(extracted)

    assert [citation["label"] for citation in citations] == ["Helwak et al. 2013"]


def test_extract_citations_splits_merged_author_year_references():
    extracted = extracted_from_pages(
        "Prior datasets include (Chakraborty et al. 2017) and (Chou et al. 2016).",
        (
            "References\n"
            "Chakraborty C, Sharma AR, Sharma G et al. Therapeutic miRNA and "
            "siRNA: moving from bench to clinic. Mol Ther Nucleic Acids "
            "2017;8:132-43. Chou C-H, Chang N-W, Shrestha S et al. "
            "miRTarBase 2016: updates to the experimentally validated "
            "miRNA-target interactions database. Nucleic Acids Res 2016;44:D239-47."
        ),
    )

    citations = extract_citations(extracted)

    assert [citation["label"] for citation in citations] == [
        "Chakraborty et al. 2017",
        "Chou et al. 2016",
    ]
    assert all(citation["resolved"] for citation in citations)


def test_extract_citations_resolves_author_particles_from_inline_short_form():
    extracted = extracted_from_pages(
        "CLIP methods were described by Nostrand et al. 2016 and cardiac work by Rooij and Olson 2012.",
        (
            "References\n"
            "Van Nostrand E, Pratt G, Shishkin A et al. Robust transcriptome wide "
            "discovery of RNA-binding protein binding sites with enhanced CLIP. "
            "Nat Methods 2016;13:508-14.\n"
            "van Rooij E, Olson EN. MicroRNA therapeutics for cardiovascular "
            "disease: opportunities and obstacles. Nat Rev Drug Discov 2012;11:860-72."
        ),
    )

    citations = extract_citations(extracted)

    assert [citation["label"] for citation in citations] == [
        "Van Nostrand et al. 2016",
        "van Rooij 2012",
    ]
    assert all(citation["resolved"] for citation in citations)


def test_extract_citations_includes_author_particle_in_inline_marker():
    extracted = extracted_from_pages(
        "The method improves earlier CLIP methods (Van Nostrand et al. 2016).",
        (
            "References\n"
            "Van Nostrand E, Pratt G, Shishkin A et al. Robust transcriptome wide "
            "discovery of RNA-binding protein binding sites with enhanced CLIP "
            "(eCLIP). Nat Methods 2016;13:508-14."
        ),
    )

    citations = extract_citations(extracted)

    assert citations[0]["label"] == "Van Nostrand et al. 2016"
    assert citations[0]["contexts"][0]["marker"] == "Van Nostrand et al. 2016"
    assert citations[0]["contexts"][0]["first_author"] == "Van Nostrand"


def test_extract_citations_keeps_many_author_year_contexts():
    body = " ".join(
        f"Result {index} follows prior work (Hejret et al. 2023)."
        for index in range(12)
    )
    extracted = extracted_from_pages(
        body,
        "References\nHejret V et al. Analysis of chimeric reads. Sci Rep 2023;13:22895.",
    )

    citations = extract_citations(extracted)

    assert citations[0]["label"] == "Hejret et al. 2023"
    assert citations[0]["context_count"] == 12
    assert len(citations[0]["contexts"]) == 12


def test_ground_citation_rects_handles_author_year_markers(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=200)
    page.insert_text((40, 60), "AutoML tools include Auto-sklearn (Feurer et al., 2015).")
    doc.save(pdf_path)
    doc.close()

    extracted = extracted_from_pages(
        "AutoML tools include Auto-sklearn (Feurer et al., 2015).",
        "References\nFeurer M et al. Efficient and robust automated machine learning. NeurIPS 2015.",
    )

    citations = ground_citation_rects(pdf_path, extract_citations(extracted))

    assert citations[0]["contexts"][0]["rects"]


def test_ground_citation_rects_uses_spacing_variants(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((40, 60), "Prior work [1,2] supports this method.")
    doc.save(pdf_path)
    doc.close()

    extracted = extracted_from_pages(
        "Prior work [1, 2] supports this method.",
        (
            "References\n"
            "[1] Jane Doe. 2020. First Reference. CHI.\n"
            "[2] Pat Smith. 2021. Second Reference. UIST."
        ),
    )

    citations = ground_citation_rects(pdf_path, extract_citations(extracted))

    assert citations[0]["contexts"][0]["rects"]
    assert citations[1]["contexts"][0]["rects"]


def test_ground_citation_rects_does_not_match_numeric_marker_inside_gene_name(tmp_path):
    pdf_path = tmp_path / "gene-name.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=220)
    page.insert_text((40, 60), "Genes on the negative strand include PKD1 and PKD1P4-6.")
    page.insert_text((40, 100), "The real citation marker is [6].")
    gene_rect = page.search_for("PKD1P4-6")[0]
    real_citation_rect = page.search_for("[6]")[0]
    doc.save(pdf_path)
    doc.close()

    citations = [
        {
            "id": "ref-6",
            "label": "[6]",
            "contexts": [
                {
                    "page_number": 1,
                    "marker": "[6]",
                    "sentence": "The real citation marker is [6].",
                }
            ],
        }
    ]

    grounded = ground_citation_rects(pdf_path, citations)
    rects = [fitz.Rect(rect) for rect in grounded[0]["contexts"][0]["rects"]]

    assert any(rect.intersects(real_citation_rect) for rect in rects)
    assert not any(rect.intersects(gene_rect) for rect in rects)


def test_ground_citation_rects_falls_back_to_author_prefix_for_diacritics(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=200)
    page.insert_text((40, 60), "Prior work (Klimentová et al. 2022) supports this.")
    author_rect = page.search_for("Klimentová")[0]
    year_rect = page.search_for("2022")[0]
    doc.save(pdf_path)
    doc.close()

    extracted = extracted_from_pages(
        "Prior work (Klimentov\x13a et al. 2022) supports this.",
        (
            "References\n"
            "Klimentova E, Hejret V, Krcmar J et al. miRBind: a deep learning "
            "method for miRNA binding classification. Genes (Basel) 2022;13:2323."
        ),
    )

    citations = ground_citation_rects(pdf_path, extract_citations(extracted))

    assert citations[0]["contexts"][0]["marker"] == "Klimentova et al. 2022"
    assert citations[0]["contexts"][0]["rects"]
    citation_rect = fitz.Rect(citations[0]["contexts"][0]["rects"][0])
    assert citation_rect.x0 <= author_rect.x0
    assert citation_rect.x1 >= year_rect.x1


def test_ground_citation_rects_spans_split_author_year_marker(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=200)
    page.insert_text((40, 60), "Prior work (Klimentov a et al. 2022) supports this.")
    author_rect = page.search_for("Klimentov")[0]
    year_rect = page.search_for("2022")[0]
    doc.save(pdf_path)
    doc.close()

    citations = [
        {
            "label": "Klimentova et al. 2022",
            "contexts": [
                {
                    "page_number": 1,
                    "marker": "Klimentova et al. 2022",
                    "first_author": "Klimentova",
                    "year": "2022",
                }
            ],
        }
    ]

    grounded = ground_citation_rects(pdf_path, citations)

    citation_rect = fitz.Rect(grounded[0]["contexts"][0]["rects"][0])
    assert citation_rect.x0 <= author_rect.x0
    assert citation_rect.x1 >= year_rect.x1


def test_ground_citation_rects_spans_author_with_missing_final_letter(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=200)
    page.insert_text((40, 60), "Prior work (Klimentov et al. 2022) supports this.")
    author_rect = page.search_for("Klimentov")[0]
    year_rect = page.search_for("2022")[0]
    doc.save(pdf_path)
    doc.close()

    citations = [
        {
            "label": "Klimentova et al. 2022",
            "contexts": [
                {
                    "page_number": 1,
                    "marker": "Klimentova et al. 2022",
                    "first_author": "Klimentova",
                    "year": "2022",
                }
            ],
        }
    ]

    grounded = ground_citation_rects(pdf_path, citations)

    citation_rect = fitz.Rect(grounded[0]["contexts"][0]["rects"][0])
    assert citation_rect.x0 <= author_rect.x0
    assert citation_rect.x1 >= year_rect.x1


def test_ground_citation_rects_includes_author_particle(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=200)
    page.insert_text((40, 60), "The method improves earlier CLIP methods (Van Nostrand et al. 2016).")
    particle_rect = page.search_for("Van")[0]
    year_rect = page.search_for("2016")[0]
    doc.save(pdf_path)
    doc.close()

    extracted = extracted_from_pages(
        "The method improves earlier CLIP methods (Van Nostrand et al. 2016).",
        (
            "References\n"
            "Van Nostrand E, Pratt G, Shishkin A et al. Robust transcriptome wide "
            "discovery of RNA-binding protein binding sites with enhanced CLIP "
            "(eCLIP). Nat Methods 2016;13:508-14."
        ),
    )

    grounded = ground_citation_rects(pdf_path, extract_citations(extracted))

    citation_rect = fitz.Rect(grounded[0]["contexts"][0]["rects"][0])
    assert citation_rect.x0 <= particle_rect.x0
    assert citation_rect.x1 >= year_rect.x1


def test_ground_citation_rects_keeps_repeated_author_year_markers_on_page(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=240)
    page.insert_text((40, 60), "First claim (Hejret et al. 2023) supports this.")
    page.insert_text((40, 100), "Second claim (Hejret et al. 2023) supports that.")
    doc.save(pdf_path)
    doc.close()

    extracted = extracted_from_pages(
        "First claim (Hejret et al. 2023) supports this. Second claim (Hejret et al. 2023) supports that.",
        "References\nHejret V et al. Analysis of chimeric reads. Sci Rep 2023;13:22895.",
    )

    grounded = ground_citation_rects(pdf_path, extract_citations(extracted))

    assert len(grounded[0]["contexts"]) == 2
    assert len(grounded[0]["contexts"][0]["rects"]) == 2
