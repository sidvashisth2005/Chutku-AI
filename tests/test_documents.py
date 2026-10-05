import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from chutku.app import PROJECT_ROOT, create_runtime
from chutku.tools import documents

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_word_powerpoint_excel_csv(self):
        make_zip(self.root / "a.docx", {"word/document.xml":
                 f'<w:document {W}><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:r><w:t>World</w:t></w:r></w:p></w:body></w:document>'})
        self.assertEqual(documents.extract(self.root / "a.docx")[0].strip(), "Hello\nWorld")
        make_zip(self.root / "b.pptx", {
            "ppt/slides/slide2.xml": f'<p:sld xmlns:p="p" {A}><a:p><a:r><a:t>Second slide text</a:t></a:r></a:p></p:sld>',
            "ppt/slides/slide1.xml": f'<p:sld xmlns:p="p" {A}><a:p><a:r><a:t>First slide text</a:t></a:r></a:p></p:sld>'})
        text, kind, _ = documents.extract(self.root / "b.pptx")
        self.assertEqual(kind, "powerpoint")
        self.assertLess(text.index("First slide"), text.index("Second slide"))
        make_zip(self.root / "c.xlsx", {
            "xl/sharedStrings.xml": f'<sst {S}><si><t>Name</t></si><si><t>Ravi</t></si></sst>',
            "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row><c t="s"><v>0</v></c><c><v>42</v></c></row>'
                                        f'<row><c t="s"><v>1</v></c><c><v>7</v></c></row></sheetData></worksheet>'})
        self.assertIn("Name | 42\nRavi | 7", documents.extract(self.root / "c.xlsx")[0])
        (self.root / "d.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.assertEqual(documents.extract(self.root / "d.csv")[0], "a | b\n1 | 2")

    def test_pdf(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(200, 200)
        with (self.root / "e.pdf").open("wb") as handle:
            writer.write(handle)
        text, kind, detail = documents.extract(self.root / "e.pdf")
        self.assertEqual(kind, "pdf")
        self.assertIn("may be a scan", detail)

    def test_image_only_deck_uses_ocr(self):
        make_zip(self.root / "f.pptx", {"ppt/slides/slide1.xml": f'<p:sld xmlns:p="p" {A}/>', "ppt/media/image1.png": b"x"})
        with patch.object(documents, "ocr", return_value=("Recognised words", "en-US")):
            text, kind, _ = documents.extract(self.root / "f.pptx")
        self.assertIn("Recognised words", text)
        self.assertIn("OCR", kind)

    def test_unsupported_and_malformed(self):
        (self.root / "g.exe").write_bytes(b"MZ")
        with self.assertRaisesRegex(ValueError, "not supported"):
            documents.extract(self.root / "g.exe")
        (self.root / "h.docx").write_bytes(b"not a zip")
        with self.assertRaises(zipfile.BadZipFile):
            documents.extract(self.root / "h.docx")


class RuntimeDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.runtime.capability_grants.grant("process.launch")
        self.root = self.runtime.granted_root
        self.records = patch.object(documents, "_records_dir", return_value=Path(self.temp.name))
        self.records.start()

    def tearDown(self):
        self.records.stop()
        self.runtime.close()
        self.temp.cleanup()

    def test_extract_text_is_untrusted_and_bounded(self):
        (self.root / "big.txt").write_text("x" * 20000, encoding="utf-8")
        result = self.runtime.run("file.extract_text", {"path": "big.txt"})
        self.assertEqual(result["output"]["provenance"], "external_untrusted")
        self.assertTrue(result["output"]["truncated"])
        self.assertEqual(len(result["output"]["text"]), documents.TEXT_CHARS)

    def test_organize_needs_confirmation_and_undo_respects_changes(self):
        folder = self.root / "desk"
        folder.mkdir()
        for name in ("a.jpg", "b.pdf", "c.mp3", "keep.xyz"):
            (folder / name).write_text(name)
        waiting = self.runtime.run("files.organize", {"path": "desk"})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        self.assertTrue((folder / "a.jpg").exists())  # nothing moved before the click
        done = self.runtime.approve(waiting["approval"]["token"])
        self.assertEqual(done["output"]["moved"], 3)
        (folder / "Images" / "a.jpg").write_text("edited after organising")
        undone = self.runtime.run("files.organize_undo", {"id": done["output"]["undo_id"]})
        self.assertEqual(undone["output"]["restored"], 2)
        self.assertEqual(undone["output"]["left_in_place_because_changed"], ["a.jpg"])
        self.assertTrue((folder / "b.pdf").exists() and (folder / "Images" / "a.jpg").exists())

    def test_script_run_needs_confirmation_and_refuses_chutku_files(self):
        (self.root / "hi.py").write_text("print('ok')\n")
        waiting = self.runtime.run("code.run_python", {"path": "hi.py"})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        done = self.runtime.approve(waiting["approval"]["token"])
        self.assertEqual(done["output"]["stdout"].strip(), "ok")
        refused = self.runtime.run("code.run_python", {"path": str(PROJECT_ROOT / "chutku" / "remind.py")})
        self.assertEqual(str(refused["state"]), "FAILED")
        self.assertIn("not run", refused["error"])


if __name__ == "__main__":
    unittest.main()
