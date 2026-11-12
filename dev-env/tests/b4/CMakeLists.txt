# B4: C program on PETSc's C API; PETSc through pkg-config, MPI through CMake's FindMPI
cmake_minimum_required(VERSION 3.20)
project(b4_ksp C)

find_package(MPI REQUIRED COMPONENTS C)
find_package(PkgConfig REQUIRED)
pkg_check_modules(PETSC REQUIRED IMPORTED_TARGET PETSc)

add_executable(b4_ksp b4_ksp.c)
target_link_libraries(b4_ksp PRIVATE PkgConfig::PETSC MPI::MPI_C m)
