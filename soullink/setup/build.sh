#!/usr/bin/env bash
# Run only in the setup launcher's private MSYS2 UCRT64 environment.
set -euo pipefail
cd /soullink-source
make clean CC=gcc CXX=g++ TOOLCHAIN=
make modern -j"${SOULLINK_JOBS:-4}" CC=gcc CXX=g++ TOOLCHAIN=
python -m soullink.tools.package
