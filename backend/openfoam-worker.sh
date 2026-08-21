#!/usr/bin/env bash
set -euo pipefail

openfoam_bashrc="${OPENFOAM_BASHRC:-/usr/lib/openfoam/openfoam2312/etc/bashrc}"
if [[ ! -f "$openfoam_bashrc" ]]; then
  echo "OpenFOAM environment file not found: $openfoam_bashrc" >&2
  exit 70
fi

set +u
source "$openfoam_bashrc"
set -u

version="$(foamVersion)"
if [[ "$version" != *2312* ]]; then
  echo "Expected OpenFOAM v2312, found: $version" >&2
  exit 71
fi

benchmark_case="${FOAM_TUTORIALS}/heatTransfer/chtMultiRegionFoam/multiRegionHeater"
if [[ ! -d "$benchmark_case" ]]; then
  echo "Official multiRegionHeater tutorial not found: $benchmark_case" >&2
  exit 72
fi

export THERMOFORM_OPENFOAM_BENCHMARK_CASE="$benchmark_case"
exec "$@"
