// G7: single-precision y = a*x + y on the GPU, compared with the same loop on the CPU
// n = 1000000, a = 2, x_i = i mod 1000, y_i = 1; all values are exact in single precision

#include <cmath>
#include <cstdio>
#include <vector>

#include <cuda_runtime.h>

// Stop with a message when a CUDA runtime call fails
#define CHECK(call)                                                             \
  do {                                                                          \
    cudaError_t status = (call);                                                \
    if (status != cudaSuccess) {                                                \
      std::printf("CUDA error %d (%s) in %s\n", (int)status,                    \
                  cudaGetErrorString(status), #call);                           \
      std::printf("G7 FAIL\n");                                                 \
      return 1;                                                                 \
    }                                                                           \
  } while (0)

__global__ void saxpy(int n, float a, const float *x, float *y)
{
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) y[i] = a * x[i] + y[i];
}

int main()
{
  const int   n = 1000000;
  const float a = 2.0f;

  // Input data and the CPU reference
  std::vector<float> x(n), yGpu(n, 1.0f), yCpu(n, 1.0f);
  for (int i = 0; i < n; i++) x[i] = (float)(i % 1000);
  for (int i = 0; i < n; i++) yCpu[i] = a * x[i] + yCpu[i];

  // Report the device that runs the kernel
  cudaDeviceProp properties;
  CHECK(cudaGetDeviceProperties(&properties, 0));
  std::printf("device: %s, compute capability %d.%d\n", properties.name, properties.major, properties.minor);

  // Copy to the device, run the kernel, copy back
  float *xDevice = nullptr, *yDevice = nullptr;
  CHECK(cudaMalloc(&xDevice, n * sizeof(float)));
  CHECK(cudaMalloc(&yDevice, n * sizeof(float)));
  CHECK(cudaMemcpy(xDevice, x.data(), n * sizeof(float), cudaMemcpyHostToDevice));
  CHECK(cudaMemcpy(yDevice, yGpu.data(), n * sizeof(float), cudaMemcpyHostToDevice));
  saxpy<<<(n + 255) / 256, 256>>>(n, a, xDevice, yDevice);
  CHECK(cudaGetLastError());
  CHECK(cudaDeviceSynchronize());
  CHECK(cudaMemcpy(yGpu.data(), yDevice, n * sizeof(float), cudaMemcpyDeviceToHost));
  CHECK(cudaFree(xDevice));
  CHECK(cudaFree(yDevice));

  // Maximum absolute difference between the GPU and the CPU result
  float difference = 0.0f;
  for (int i = 0; i < n; i++) difference = std::fmax(difference, std::fabs(yGpu[i] - yCpu[i]));
  std::printf("y[999] gpu %.1f cpu %.1f (expected 1999.0)\n", yGpu[999], yCpu[999]);
  std::printf("maximum absolute difference: %.9g\n", difference);
  std::printf("G7 %s\n", (difference == 0.0f) ? "PASS" : "FAIL");
  return (difference == 0.0f) ? 0 : 1;
}
