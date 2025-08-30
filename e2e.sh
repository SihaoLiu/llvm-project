# CMake Clean
rm -rf build && mkdir build
# CMake Configure
cmake -B build \
      -G Ninja \
      -S "./llvm" \
      -DCMAKE_C_COMPILER=clang \
      -DCMAKE_CXX_COMPILER=clang++ \
      -DLLVM_ENABLE_PROJECTS="mlir;clang" \
      -DLLVM_TARGETS_TO_BUILD="host" \
      -DLLVM_ENABLE_ASSERTIONS=ON \
      -DCMAKE_BUILD_TYPE=DEBUG \
      -DLLVM_USE_SPLIT_DWARF=ON \
      -DLLVM_ENABLE_LLD=ON \
      -DCLANG_ENABLE_CIR=ON \
      -DLLVM_BUILD_EXAMPLES=ON \
      -DLLVM_ENABLE_RTTI=ON
# CMake Build
cmake --build build -j 30
# CMake Test
cmake --build build --target check-mlir  -j 30
cmake --build build --target check-clang -j 30