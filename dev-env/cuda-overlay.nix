# PETSc and SLEPc with CUDA 12.6 for the numerics-cuda block
# Each setting is explained where it is made; what was validated is in docs/DEV-ENVIRONMENTS.md
# Returns the overlay and the unfree names it needs
let
  # GPU architecture of the RTX 3500 Ada (compute capability 8.9)
  cudaArch = "89";
in
{
  # Unfree packages allowed by name (no global allowUnfree); each name is required
  unfreeNames = [
    "cuda_nvcc"
    "cuda_cudart"
    "cuda_cccl"
    "cuda_nvml_dev"
    "cuda_nvtx"
    "libcublas"
    "libcusparse"
    "libcusolver"
    "libcurand"
    "libcufft"
    "libnvjitlink"
    "cuda_nvrtc"
  ];

  overlay =
    final: prev:
    let
      lib = final.lib;
      cudaPackages = final.cudaPackages_12_6;

      # PETSc's --with-cuda-dir wants one prefix with bin/nvcc, include, lib and lib/stubs,
      # the Nix CUDA packages are split per library and per output
      # The name must start with "cuda-": nixpkgs' petsc postInstall derives the
      # petscvariables prefix (CUDA_INCLUDE, CUDA_LIB) from the first word of each
      # buildInput's name, and removeStubsFromRunpathHook only recognises stub
      # directories of the form *-cuda*/stubs in a RUNPATH
      petscCudaToolkit = final.symlinkJoin {
        name = "cuda-petsc-toolkit-${cudaPackages.cudaMajorMinorVersion}";
        paths =
          # Single-output packages
          [
            cudaPackages.cuda_nvcc # bin/nvcc, crt/host_config.h
            cudaPackages.cuda_cudart # cuda.h, libcudart, stub lib/stubs/libcuda.so
            cudaPackages.cccl # thrust/version.h
          ]
          # NVML: PETSc's configure requires nvml.h and nvmlInit_v2, only a stub exists
          ++ [
            cudaPackages.cuda_nvml_dev.include
            cudaPackages.cuda_nvml_dev.stubs
          ]
          # Shared library and headers only; the static and stubs outputs of the math
          # libraries would shadow the real libraries or only add closure size
          ++ lib.concatMap
            (p: [
              p.lib
              p.include
            ])
            [
              cudaPackages.nvtx # libnvToolsExt (PETSc's basic CUDA library list)
              cudaPackages.libcublas
              cudaPackages.libcusparse
              cudaPackages.libcusolver
              cudaPackages.libcurand
              cudaPackages.libcufft
            ];
        # The merged nix-support directory would propagate setup hooks of single packages
        postBuild = "rm -rf $out/nix-support";
      };

      # The build sandbox has neither a GPU nor a driver, while libpetsc.so needs
      # libcuda.so.1 and libnvidia-ml.so.1 at load time: inside the build the stubs are
      # loaded instead, and the petsc4py/slepc4py unit tests use the host device as
      # default device (test_device.py initialises the default device)
      sandboxCheckEnv = ''
        export LD_LIBRARY_PATH=${petscCudaToolkit}/lib/stubs''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
        export PETSC_OPTIONS="-default_device_type host"
      '';
    in
    {
      inherit petscCudaToolkit;

      # One PETSc: pkgs.petsc is built with the same arguments that
      # python313Packages.petsc4py passes, so both are the same derivation
      petsc =
        (prev.petsc.override {
          python3Packages = final.python313Packages;
          pythonSupport = true;
        }).overrideAttrs
          (old: {
            # Replaces the stub directory in every RUNPATH by the driver directory;
            # propagated because downstream builds (SLEPc) link with PETSc's -L<stubs>
            propagatedNativeBuildInputs = (old.propagatedNativeBuildInputs or [ ]) ++ [
              cudaPackages.removeStubsFromRunpathHook
            ];

            # nvcc force-includes cuda_runtime.h, also in PETSc's first compiler check that
            # runs before --with-cuda-dir is evaluated; as a buildInput the toolkit's
            # include and lib directories are on the compiler wrappers' search paths
            buildInputs = old.buildInputs ++ [ petscCudaToolkit ];

            configureFlags = old.configureFlags ++ [
              "--with-cuda=1"
              "--with-cuda-dir=${petscCudaToolkit}"
              "--with-cuda-arch=${cudaArch}"
            ];

            # "make check" runs two GPU examples when PETSC_HAVE_CUDA is set; run the CPU
            # HYPRE example instead of the HYPRE/CUDA one and skip runex19_cuda, all
            # other checks stay enabled
            postPatch = old.postPatch + ''
              substituteInPlace makefile \
                --replace-fail 'HYPRE_TEST=runex19_hypre_cuda;' 'HYPRE_TEST=runex19_hypre;' \
                --replace-fail "\''${RUN_TEST} runex19_cuda;" 'echo "Skipped runex19_cuda: no GPU in the Nix build sandbox";'
            '';

            preInstallCheck = (old.preInstallCheck or "") + sandboxCheckEnv;
          });

      # SLEPc follows the overlay's PETSc by itself; only the missing GPU needs handling
      slepc = prev.slepc.overrideAttrs (old: {
        postPatch = old.postPatch + ''
          substituteInPlace makefile \
            --replace-fail "\''${RUN_TEST} testtest10_cuda;" 'echo "Skipped testtest10_cuda: no GPU in the Nix build sandbox";'
        '';

        # Already at configure time: SLEPc's configure imports petsc4py.PETSc
        preConfigure = (old.preConfigure or "") + sandboxCheckEnv;
      });
    };
}
