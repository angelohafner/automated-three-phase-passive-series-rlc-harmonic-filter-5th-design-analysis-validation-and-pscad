# Passive harmonic filter study

The requested implementation is authorized by the detailed study specification.

## Design

- Use the installed PSCAD 5.1 Master Library and public mhi.pscad API.
- Represent the grounded three-phase source with three balanced single-phase
  voltage sources; use explicit per-phase grid R and L.
- Build individual sine controls from time, gain, phase constant, summing
  junction and trigonometric blocks. Sum them into three controlled current sources.
- Measure injected current, PCC-to-grid current, PCC-to-filter current and
  phase-to-neutral PCC voltage independently. Optional linear load adds its
  measured current to the KCL equation.
- Use grounded-wye series RLC branches; size for specified fundamental net kvar
  including resistance. Cover baseline, tuned, detuned, stiff/weak grid and low Q.
- Fit RMS sine-reference phasors on complete steady-state cycles through order 25.
  Compare against an independent complex circuit solution and validate time KCL,
  harmonic KCL, harmonic sequences and steady-state stability.
- Preserve raw PSCAD outputs, export CSV and plots, and save projects/workspace.
- Provide explicit analytic-only mode and a parameterized template workflow.

## Execution Checklist

1. Inspect real definitions, parameters, active ports, compiler and license.
2. Add focused numerical tests, implement configuration, sizing and analysis.
3. Implement guarded API circuit construction and template parameter binding.
4. Run the actual PSCAD cases, inspect failures, validate and export results.
5. Document installation, equations, topology, sequences, limitations and results.
6. Run the tests and audit delivered artifacts against all requested outputs.

## Completion Evidence

- Automatic construction and baseline EMTDC run completed successfully.
- All six comparison cases ran through the saved-base workflow in PSCAD 5.1.
- 964 strengthened numerical validation checks passed on the comparison results.
- Half-step convergence run passed with 0.220132% maximum complex difference.
- A second automatic build with a linear load, third-harmonic zero sequence,
  changed fifth-harmonic angle and disabled eleventh harmonic passed 184 checks.
- 14 unit tests passed, including independent phasors, sizing, KCL, OUT metadata,
  missing small harmonics, unexpected DC and unmodeled waveform content.
- Local source compilation and visual inspection of generated figures completed.
- README, manual template instructions, result index and portable ZIP delivered.
