"""Instant file commands with full paths (benchmark 2026-10-04: the local model faked renames and deletes)."""
import unittest

from chutku.file_intent import parse_file_command
from chutku.quick_intents import quick_proposal


def steps(text):
    proposal = quick_proposal(text, apps=[])
    return None if proposal is None else [(s["tool"], s["arguments"]) for s in proposal["next_steps"]]


class FileCommandTests(unittest.TestCase):
    def test_benchmark_file_goals(self):
        self.assertEqual(steps(r"Rename D:\ChutkuBench\draft.txt to final.txt"),
                         [("filesystem.move", {"source": r"D:\ChutkuBench\draft.txt",
                                               "destination": r"D:\ChutkuBench\final.txt"})])
        self.assertEqual(steps(r"Delete D:\ChutkuBench\junk.tmp"),
                         [("filesystem.recycle", {"path": r"D:\ChutkuBench\junk.tmp"})])
        self.assertEqual(steps(r"Make a copy of D:\ChutkuBench\report.txt named D:\ChutkuBench\report-backup.txt"),
                         [("filesystem.copy", {"source": r"D:\ChutkuBench\report.txt",
                                               "destination": r"D:\ChutkuBench\report-backup.txt"})])
        self.assertEqual(steps(r"Write 'x' into D:\ChutkuBench\x.txt"),
                         [("filesystem.write_text", {"path": r"D:\ChutkuBench\x.txt", "content": "x"})])
        self.assertEqual(steps(r"D:\ChutkuBench mein projects naam ka folder banao"),
                         [("filesystem.create_directory", {"path": r"D:\ChutkuBench\projects"})])
        self.assertEqual(steps(r"Create D:\ChutkuVerify\draft.txt with the text hello"),
                         [("filesystem.write_text", {"path": r"D:\ChutkuVerify\draft.txt", "content": "hello"})])

    def test_two_part_request_becomes_two_steps(self):
        self.assertEqual(
            steps(r"Create the folder D:\ChutkuBench\notes and write 'hello bench' into D:\ChutkuBench\notes\hello.txt"),
            [("filesystem.create_directory", {"path": r"D:\ChutkuBench\notes"}),
             ("filesystem.write_text", {"path": r"D:\ChutkuBench\notes\hello.txt", "content": "hello bench"})])

    def test_several_files_in_a_folder_then_list(self):
        self.assertEqual(steps(r"In D:\ChutkuBench create a.txt containing 'one' and b.txt containing 'two', then list the folder."),
                         [("filesystem.write_text", {"path": r"D:\ChutkuBench\a.txt", "content": "one"}),
                          ("filesystem.write_text", {"path": r"D:\ChutkuBench\b.txt", "content": "two"}),
                          ("filesystem.list", {"path": r"D:\ChutkuBench"})])
        from chutku.file_intent import parse_file_batch
        self.assertIsNone(parse_file_batch(r"In D:\x create a.txt containing 'one' and delete b.txt"))   # unparsed part
        self.assertIsNone(parse_file_batch(r"In D:\x create a.txt and b.txt"))                          # no contents

    def test_a_path_never_swallows_the_next_clause(self):
        self.assertIsNone(parse_file_command(r"rename D:\x\a.txt to final.txt and open it"))
        self.assertIsNone(parse_file_command(r"delete D:\x\junk.tmp and then empty the bin"))

    def test_vague_or_whole_drive_requests_are_never_instant(self):
        for text in (r"Delete everything in C:\Windows\System32", "delete D:\\", r"delete D:\x\*.tmp",
                     r"delete all files in D:\x", "delete my files", r"rename D:\ to E"):
            self.assertIsNone(parse_file_command(text), text)


if __name__ == "__main__":
    unittest.main()
