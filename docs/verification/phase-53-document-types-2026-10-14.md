# Document types beyond PDF (2026-10-14)

The owner asked that the library accept every type MinerU supports. Done on `feature/meeting-multimodal`, local only (core and worker code; the production worker image was not rebuilt or touched).

## What was measured

A throwaway worker container (same image and read-only models as production, 4 GiB, removed afterwards) was run with a widened allowlist and one real sample of each type was ingested at the fastest tier and read back. Samples were generated with python-pptx, python-docx, openpyxl and LibreOffice.

| Type | Result | Pages |
|---|---|---|
| pptx, ppt, odp | parsed, headings recovered | **one per slide** (10 of 10) |
| xlsx, xls, ods | parsed as tables | one per sheet |
| docx, doc, rtf, odt | parsed | 1 (the parser does not paginate; a hard page break is not a page) |
| epub, html, csv, tsv | parsed | 1 |
| txt, md | **not parsed** (the worker answers "not ready") | not accepted |

Page pictures exist only for PDF and images (a parser limit). Not tried: OFD, MHTML, other formats the MinerU documentation lists; they can be added the same way after the same measurement.

## Change

- `shared/models/document_types.py`: one table (extension, MIME, content rule) used by both core (upload, tier) and the worker (ingest). A type is accepted by content: leading bytes and, for packaged formats, the entries that make the format (`ppt/presentation.xml`, `xl/workbook.xml`, `word/document.xml`, the ODF/EPUB `mimetype` entry), for text types readable UTF-8 without binary bytes (HTML must contain markup). The worker repeats the check on the stored file.
- Native-text types use the fastest reading tier; PDF and images keep OCR. Presentation files the parser was not shown to read (`.pps`, `.ppsx`, `.pptm`, Keynote, Pages, Numbers) are refused with "export it as a PDF or PPTX first".
- Web: the file pickers on the Documents page and the meeting's Documents tab offer the accepted list (a core test pins it equal to the server's list); texts no longer say "export to PDF".
- Phase 53 needed no change: it reads pages through the library service, so a PPTX attachment aligns like a PDF.

## Verification

Worker tests: every accepted type is taken by content and parsed whole; mismatched content (a pptx that is a Word package, a zip that is not a package, a PDF named .ppt, plain text named .rtf, an HTML file with binary bytes, an ODF of the wrong kind, an EPUB with the wrong mimetype) is refused 415; txt, md, exe, pptm and key are refused. Core tests: the same through the upload route, tiers, and the web list equals the server's. **Real end to end (this branch's worker source in the disposable container, real library service, live 7B):** every sample type uploaded, reached Ready with the page counts above; the same 10-slide deck as PDF and as PPTX went through the whole page estimate: 25.8 s and 25.6 s, 20 of 21 windows with the same page and certainty (the one difference was a Low versus an Unknown window; the 7B is not deterministic across runs).

## Limits

A PowerPoint attachment has no thumbnail and the extraction inspector shows its text without a page picture. Non-presentation types are a single page, so an estimate against them is coarse. Converting those to paginated PDF with LibreOffice would give pictures and page boundaries, but is a new component and is not built. Production needs the document-worker image rebuilt and recreated (see the deployment plan in [phase-53](../phase-53.md#10-deployment-and-rollback-plan-nothing-below-is-authorised)).
