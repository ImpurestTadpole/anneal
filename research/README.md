# Roadmap verification (branch verify-roadmap)

Prototypes and checks for the Anneal roadmap. Main is unchanged.

Optional hooks in the package, off by default:

- `fem.hex8_matrices(nu, h, D=None)`, `FEM(..., D=None)`: anisotropic 6x6 D matrix
- `FEM.assemble_matrix(m24, w)`: any element matrix on the K sparse pattern
- `optimize.simp(..., am=None)`: optional AM (overhang) filter after projection

Run:

    PYTHONPATH=. python research/verify.py
    python research/ccx_check.py <workdir>      # needs gmsh and ccx on PATH

With the hooks off, the 25 tests pass and validation hash V5 is identical to 0.3.0.
