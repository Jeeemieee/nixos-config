/* B4: the B2 problem through PETSc's C API
   A = tridiag[-1, 4, -1], n = 1000, manufactured solution x*_i = sin(i), b = A x*
   KSP preonly, PC lu, factor solver mumps; relative error ||x - x*||_2 / ||x*||_2 < 1e-10
   The right-hand side and the error are computed with plain C and libm, not with PETSc */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <petscksp.h>

static char help[] = "B4: tridiagonal system solved with MUMPS through the C API\n";

int main(int argc, char **argv)
{
  const PetscInt     n         = 1000;
  const PetscReal    tolerance = 1e-10;
  Mat                A;
  Vec                b, x, xAll;
  KSP                ksp;
  PC                 pc;
  VecScatter         scatter;
  MatSolverType      solverType;
  KSPConvergedReason reason;
  PetscMPIInt        rank, ranks;
  PetscInt           rowStart, rowEnd;
  PetscBool          passed = PETSC_TRUE;

  PetscFunctionBeginUser;
  PetscCall(PetscInitialize(&argc, &argv, NULL, help));
  PetscCallMPI(MPI_Comm_rank(PETSC_COMM_WORLD, &rank));
  PetscCallMPI(MPI_Comm_size(PETSC_COMM_WORLD, &ranks));

  /* Matrix: at most 3 entries per row, 1 of them possibly in the off-diagonal block */
  PetscCall(MatCreateAIJ(PETSC_COMM_WORLD, PETSC_DECIDE, PETSC_DECIDE, n, n, 3, NULL, 1, NULL, &A));
  PetscCall(MatGetOwnershipRange(A, &rowStart, &rowEnd));
  for (PetscInt i = rowStart; i < rowEnd; i++) {
    if (i > 0) PetscCall(MatSetValue(A, i, i - 1, -1.0, INSERT_VALUES));
    PetscCall(MatSetValue(A, i, i, 4.0, INSERT_VALUES));
    if (i < n - 1) PetscCall(MatSetValue(A, i, i + 1, -1.0, INSERT_VALUES));
  }
  PetscCall(MatAssemblyBegin(A, MAT_FINAL_ASSEMBLY));
  PetscCall(MatAssemblyEnd(A, MAT_FINAL_ASSEMBLY));

  /* Right-hand side b = A x* from the stencil, with libm only */
  PetscCall(MatCreateVecs(A, &x, &b));
  for (PetscInt i = rowStart; i < rowEnd; i++) {
    PetscScalar value = 4.0 * sin((double)i);
    if (i > 0) value -= sin((double)(i - 1));
    if (i < n - 1) value -= sin((double)(i + 1));
    PetscCall(VecSetValue(b, i, value, INSERT_VALUES));
  }
  PetscCall(VecAssemblyBegin(b));
  PetscCall(VecAssemblyEnd(b));

  /* Direct solve with MUMPS */
  PetscCall(KSPCreate(PETSC_COMM_WORLD, &ksp));
  PetscCall(KSPSetOperators(ksp, A, A));
  PetscCall(KSPSetType(ksp, KSPPREONLY));
  PetscCall(KSPGetPC(ksp, &pc));
  PetscCall(PCSetType(pc, PCLU));
  PetscCall(PCFactorSetMatSolverType(pc, MATSOLVERMUMPS));
  PetscCall(KSPSolve(ksp, b, x));
  PetscCall(KSPGetConvergedReason(ksp, &reason));
  PetscCall(PCFactorGetMatSolverType(pc, &solverType));

  /* Gather the solution on rank 0 and compare with x* there */
  PetscCall(VecScatterCreateToZero(x, &scatter, &xAll));
  PetscCall(VecScatterBegin(scatter, x, xAll, INSERT_VALUES, SCATTER_FORWARD));
  PetscCall(VecScatterEnd(scatter, x, xAll, INSERT_VALUES, SCATTER_FORWARD));
  if (rank == 0) {
    const PetscScalar *values;
    double             errorSquared = 0.0, referenceSquared = 0.0, error;
    Dl_info            library;
    char               libraryPath[PATH_MAX] = "unknown";

    PetscCall(VecGetArrayRead(xAll, &values));
    for (PetscInt i = 0; i < n; i++) {
      const double exact = sin((double)i);
      errorSquared += (values[i] - exact) * (values[i] - exact);
      referenceSquared += exact * exact;
    }
    PetscCall(VecRestoreArrayRead(xAll, &values));
    error  = sqrt(errorSquared / referenceSquared);
    passed = (PetscBool)(reason > 0 && error < tolerance && strcmp(solverType, MATSOLVERMUMPS) == 0);

    /* The PETSc library this binary is linked to, for B6 */
    if (dladdr((void *)PetscInitialize, &library) && library.dli_fname) {
      if (!realpath(library.dli_fname, libraryPath)) strcpy(libraryPath, "unknown");
    }

    PetscCall(PetscPrintf(PETSC_COMM_SELF, "ranks: %d n: %" PetscInt_FMT "\n", ranks, n));
    PetscCall(PetscPrintf(PETSC_COMM_SELF, "factor solver: %s converged reason: %d\n", solverType, (int)reason));
    PetscCall(PetscPrintf(PETSC_COMM_SELF, "relative error: %.16e tolerance: %g\n", error, (double)tolerance));
    PetscCall(PetscPrintf(PETSC_COMM_SELF, "petsc library: %s\n", libraryPath));
    PetscCall(PetscPrintf(PETSC_COMM_SELF, "B4 %s\n", passed ? "PASS" : "FAIL"));
  }

  PetscCall(VecScatterDestroy(&scatter));
  PetscCall(VecDestroy(&xAll));
  PetscCall(KSPDestroy(&ksp));
  PetscCall(VecDestroy(&x));
  PetscCall(VecDestroy(&b));
  PetscCall(MatDestroy(&A));
  PetscCall(PetscFinalize());
  return passed ? 0 : 1;
}
