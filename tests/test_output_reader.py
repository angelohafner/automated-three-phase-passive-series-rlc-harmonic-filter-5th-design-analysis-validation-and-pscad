"""Check the mapping of original PSCAD OUT blocks by INF indices."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from harmonic_filter.pscad_backend import read_pscad_output


class OutputReaderTests(unittest.TestCase):
    def test_channels_follow_metadata_indices_across_blocks(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "case.inf").write_text(
                'PGB(11) Output Desc="Vpcc_A" Units="V"\n'
                'PGB(1) Output Desc="Iload_A" Units="A"\n', encoding="utf-8")
            (directory / "case_01.out").write_text("\n0 3\n0.001 4\n", encoding="utf-8")
            (directory / "case_02.out").write_text("\n0 270\n0.001 271\n", encoding="utf-8")
            frame = read_pscad_output(directory, "case")
            self.assertEqual(frame.Iload_A.tolist(), [3, 4])
            self.assertEqual(frame.Vpcc_A.tolist(), [270, 271])

    def test_different_block_times_are_rejected(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "case.inf").write_text('PGB(1) Output Desc="Iload_A"\nPGB(11) Output Desc="Vpcc_A"\n')
            (directory / "case_01.out").write_text("\n0 3\n0.001 4\n")
            (directory / "case_02.out").write_text("\n0 270\n0.002 271\n")
            with self.assertRaises(ValueError):
                read_pscad_output(directory, "case")


if __name__ == "__main__":
    unittest.main()
