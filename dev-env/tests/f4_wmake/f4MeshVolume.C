// Number of cells and total cell volume of the mesh of a case
// Compiled with wmake by the check f4: a program of our own against OpenFOAM's libraries

#include "fvCFD.H"
#include "IOmanip.H"

int main(int argc, char *argv[])
{
    #include "setRootCase.H"
    #include "createTime.H"
    #include "createMesh.H"

    // Enough digits to compare the volume with its exact value
    Info<< "cells: " << mesh.nCells() << nl
        << "volume: " << setprecision(16) << gSum(mesh.V()) << endl;

    return 0;
}
