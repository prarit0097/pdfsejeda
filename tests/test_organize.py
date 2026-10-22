import zipfile
import io

from reportlab.lib.pagesizes import A4, landscape

from conftest import make_pdf, make_png, open_out, run_tool, store


def _texts(pdf):
    import pypdf

    r = pypdf.PdfReader(io.BytesIO(pdf))
    return [p.extract_text().splitlines()[0] for p in r.pages]


def test_merge_basic_and_bookmarks():
    a = store(make_pdf(2, bookmarks=True), "a.pdf")
    b = store(make_pdf(3), "b.pdf")
    img = store(make_png(), "pic.png", "image/png")
    task, out = run_tool("merge", [a, b, img], outlinePolicy="retain")
    pdf = open_out(out[task.result_filename])
    assert len(pdf.pages) == 6
    with pdf.open_outline() as o:
        assert [i.title for i in o.root] == ["Chapter 1", "Chapter 2"]


def test_merge_options():
    a = store(make_pdf(1), "a.pdf")
    b = store(make_pdf(2, landscape(A4)), "b.pdf")
    task, out = run_tool("merge", [a, b], blankPageIfOdd=True, tocPolicy="file_names", filenameFooter=True,
                         normalizePageSizes=True, outlinePolicy="one_entry_each_doc", outputFilename="all")
    assert task.result_filename == "all.pdf"
    pdf = open_out(out["all.pdf"])
    assert len(pdf.pages) == 1 + 1 + 1 + 2  # toc + a + blank + b
    widths = {round(float(p.mediabox[2])) for p in pdf.pages}
    assert widths == {595}


def test_split_every_page(pdf3):
    task, out = run_tool("splitByPages", [pdf3], step=1)
    assert task.result_filename.endswith(".zip")
    assert sorted(n for n in out if n.endswith(".pdf")) == ["three-1.pdf", "three-2.pdf", "three-3.pdf"]


def test_split_after_pages_with_names(pdf3):
    task, out = run_tool("splitByPages", [pdf3], pages="1", specificResultFilenames=["intro", ""])
    assert "intro.pdf" in out and len(open_out(out["intro.pdf"]).pages) == 1
    assert len(open_out(out["three-2.pdf"]).pages) == 2


def test_split_by_bookmarks():
    f = store(make_pdf(3, bookmarks=True), "book.pdf")
    task, out = run_tool("splitByBookmarks", [f], bookmarksLevel=1)
    assert {"Chapter 1.pdf", "Chapter 2.pdf", "Chapter 3.pdf"} <= set(out)


def test_split_by_size():
    f = store(make_pdf(6), "s.pdf")
    task, out = run_tool("splitBySize", [f], size=12, sizeUnit="KB")
    pdfs = [n for n in out if n.endswith(".pdf")]
    assert sum(len(open_out(out[n]).pages) for n in pdfs) == 6


def test_split_by_text():
    f = store(make_pdf(4, texts=["Invoice 1", "Invoice 1", "Invoice 2", "Invoice 3"]), "inv.pdf")
    task, out = run_tool("splitByText", [f], area={"x": 60, "y": 40, "width": 300, "height": 50})
    pdfs = sorted(n for n in out if n.endswith(".pdf"))
    assert pdfs == ["Invoice_1.pdf", "Invoice_2.pdf", "Invoice_3.pdf"]
    assert len(open_out(out["Invoice_1.pdf"]).pages) == 2


def test_split_down_the_middle(pdf_landscape):
    task, out = run_tool("splitDownTheMiddle", [pdf_landscape], mode="auto")
    pdf = open_out(out[task.result_filename])
    assert len(pdf.pages) == 4
    box = [float(v) for v in pdf.pages[0].obj.CropBox]
    assert round(box[2] - box[0]) == round(842 / 2)


def test_alternate_mix():
    a = store(make_pdf(2, texts=["A1", "A2"]), "a.pdf")
    b = store(make_pdf(2, texts=["B1", "B2"]), "b.pdf")
    task, out = run_tool("alternateMix", [a, b], reverse=True)
    assert _texts(out[task.result_filename]) == ["A1", "B2", "A2", "B1"]


def test_extract_and_delete(pdf3):
    _, out = run_tool("extractPages", [pdf3], pages="1,3")
    assert _texts(out["three.pdf"]) == ["Page 1", "Page 3"]
    _, out = run_tool("deletePages", [pdf3], pages="2")
    assert _texts(out["three.pdf"]) == ["Page 1", "Page 3"]


def test_combine_reorder(pdf3):
    b = store(make_pdf(1, texts=["B"]), "b.pdf")
    task, out = run_tool("combineReorder", [pdf3, b], filePages=["1:1:0", "0:3:90", "-1:-1:0", "0:3:0"])
    pdf = open_out(out[task.result_filename])
    assert len(pdf.pages) == 4
    assert int(pdf.pages[1].obj.get("/Rotate", 0)) == 90


def test_rotate(pdf3):
    _, out = run_tool("rotatePages", [pdf3], pageRotationsPerSource=["0:2:90"])
    pdf = open_out(out["three.pdf"])
    assert [int(p.obj.get("/Rotate", 0)) for p in pdf.pages] == [0, 90, 0]
    _, out = run_tool("rotatePages", [pdf3], rotation=180, pages="")
    pdf = open_out(out["three.pdf"])  # keep a reference: pages die with their Pdf
    assert {int(p.obj.get("/Rotate", 0)) for p in pdf.pages} == {180}
