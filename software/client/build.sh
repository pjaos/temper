#!/bin/bash
mkdir src/temper/assets

set -e # Stop on code check or test errors
./check_code.sh # Run some checks on the code before building it
#./run_tests.sh
cp pyproject.toml src/temper/assets
# Use poetry command to build python wheel
poetry --output=linux --clean -vvv build
