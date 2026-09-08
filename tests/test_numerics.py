"""Numerical contracts for filter design, phasors and current splitting."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np

from harmonic_filter.config import StudyConfig, Harmonic, SimulationCase
from harmonic_filter.electrical import design_filter, solve_phasors, phase_angle, synthesize_reference
from harmonic_filter.analysis import fit_phasors, current_balance, thd_percent, analyze_case


class FilterDesignTests(unittest.TestCase):
    def test_net_reactive_power_and_tuning_include_damping(self):
        branch = design_filter(480, 30000, 60, 300, quality_factor=5)
        self.assertAlmostEqual(branch.impedance(300).imag, 0, places=12)
        self.assertAlmostEqual(-(480**2 / branch.impedance(60).conjugate()).imag,
                               30000, places=7)
        self.assertAlmostEqual(2 * np.pi * 300 * branch.inductance_h /
                               branch.resistance_ohm, 5, places=12)

    def test_explicit_resistance(self):
        branch = design_filter(480, 30000, 60, 300, resistance_ohm=0.1)
        self.assertAlmostEqual(branch.resistance_ohm, 0.1)
        self.assertAlmostEqual(-(480**2 / branch.impedance(60).conjugate()).imag,
                               30000, places=7)

    def test_unphysical_design_is_rejected(self):
        with self.assertRaises(ValueError):
            design_filter(480, 30000, 60, 55)
        with self.assertRaises(ValueError):
            design_filter(480, 30000, 60, 300, resistance_ohm=20)


class PhasorTests(unittest.TestCase):
    def test_rms_sine_reference_and_thd(self):
        time = np.arange(0.713, 0.913, 1 / 60000)
        waveform = (np.sqrt(2) * 100 * np.sin(2*np.pi*60*time + 0.3)
                    + np.sqrt(2) * 20 * np.sin(2*np.pi*300*time - 0.7) + 3)
        phasors, dc = fit_phasors(time, waveform, 60, 25)
        self.assertAlmostEqual(abs(phasors[1]), 100, places=8)
        self.assertAlmostEqual(np.angle(phasors[1]), 0.3, places=8)
        self.assertAlmostEqual(abs(phasors[5]), 20, places=8)
        self.assertAlmostEqual(np.angle(phasors[5]), -0.7, places=8)
        self.assertAlmostEqual(float(dc), 3, places=8)
        self.assertAlmostEqual(float(thd_percent(phasors)), 20, places=8)

    def test_complex_kcl_is_not_magnitude_subtraction(self):
        load = np.array([10+0j])
        grid = np.array([4+3j])
        branch = np.array([6-3j])
        np.testing.assert_allclose(current_balance(load, grid, branch), 0)
        self.assertGreater(abs(abs(load[0])-abs(grid[0])-abs(branch[0])), 1)

    def test_zero_fundamental_has_undefined_thd(self):
        self.assertTrue(np.isnan(thd_percent(np.zeros(26, complex))))

    def test_harmonic_sequences(self):
        for order in [1, 5, 7, 11, 13, 3]:
            actual = np.exp(1j * np.deg2rad(phase_angle(order, 0, "B")))
            expected = np.exp(-2j*np.pi*order/3)
            self.assertAlmostEqual(abs(actual-expected), 0, places=12)

    def test_grid_and_filter_obey_kcl_and_kvl(self):
        config = StudyConfig()
        for linear_kw in [0, 20]:
            config.linear_load_kw = linear_kw
            for enabled in [False, True]:
                case = SimulationCase("test", filter_enabled=enabled)
                values = solve_phasors(config, case)
                np.testing.assert_allclose(current_balance(values["Iload_A"],
                    values["Isystem_A"], values["Ifilter_A"], values["Ilinear_A"]),
                    0, atol=1e-10)
                self.assertAlmostEqual(abs(values["Iload_A"][5]), 20)

    def test_disabled_component_is_absent(self):
        config = StudyConfig(harmonics=[Harmonic(1, 100, 180), Harmonic(5, 20, 0, False)])
        values = solve_phasors(config, SimulationCase("test"))
        self.assertEqual(values["Iload_A"][5], 0)

    def test_unexpected_dc_fails_validation_even_when_kcl_passes(self):
        config, case = StudyConfig(), SimulationCase("dc_test", filter_enabled=False)
        frame = synthesize_reference(config, case)
        frame["Iload_A"] += 20
        frame["Isystem_A"] += 20
        with TemporaryDirectory() as directory:
            result = analyze_case(frame, config, case, Path(directory), "TEST")
        self.assertFalse(result["validation"].passed.all())

    def test_unmodeled_frequency_fails_validation(self):
        config, case = StudyConfig(), SimulationCase("residual_test", filter_enabled=False)
        frame = synthesize_reference(config, case)
        extra = np.sqrt(2)*15*np.sin(2*np.pi*31*60*frame.time_s)
        frame["Iload_A"] += extra
        frame["Isystem_A"] += extra
        with TemporaryDirectory() as directory:
            result = analyze_case(frame, config, case, Path(directory), "TEST")
        self.assertFalse(result["validation"].passed.all())

    def test_small_missing_harmonic_fails_validation(self):
        config = StudyConfig(harmonics=[Harmonic(1, 100, 180), Harmonic(5, 0.5)])
        actual = StudyConfig(harmonics=[Harmonic(1, 100, 180), Harmonic(5, 0.5, enabled=False)])
        case = SimulationCase("small_test", filter_enabled=False)
        with TemporaryDirectory() as directory:
            result = analyze_case(synthesize_reference(actual, case), config, case, Path(directory), "TEST")
        self.assertFalse(result["validation"].passed.all())


if __name__ == "__main__":
    unittest.main()
