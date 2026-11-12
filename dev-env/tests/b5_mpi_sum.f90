! B5: sum of the MPI ranks in Fortran; expected n(n-1)/2, which is 6 on 4 ranks
program b5_mpi_sum
  use mpi_f08
  implicit none
  integer :: rank, ranks, total

  call MPI_Init()
  call MPI_Comm_rank(MPI_COMM_WORLD, rank)
  call MPI_Comm_size(MPI_COMM_WORLD, ranks)

  ! Sum of the ranks 0..n-1 through MPI
  call MPI_Allreduce(rank, total, 1, MPI_INTEGER, MPI_SUM, MPI_COMM_WORLD)
  if (rank == 0) print '(a,i0,a,i0)', 'ranks: ', ranks, ' sum of ranks: ', total
  call MPI_Finalize()

  ! Closed form, independent of MPI
  if (total /= (ranks*(ranks - 1))/2) error stop 1
end program b5_mpi_sum
