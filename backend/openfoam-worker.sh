#!/usr/bin/env bash
set -o pipefail

openfoam_bashrc="${OPENFOAM_BASHRC:-/usr/lib/openfoam/openfoam2312/etc/bashrc}"
if [[ ! -f "$openfoam_bashrc" ]]; then
  echo "OpenFOAM environment file not found: $openfoam_bashrc" >&2
  exit 70
fi

worker_command=("$@")
set --
set +e
set +u
source "$openfoam_bashrc"
source_status=$?
set -- "${worker_command[@]}"
set -e
set -u
if [[ $source_status -ne 0 ]]; then
  echo "OpenFOAM environment failed to load from: $openfoam_bashrc" >&2
  exit 70
fi

version="${WM_PROJECT_VERSION:-}"
if [[ -z "$version" ]] && [[ -x /usr/bin/openfoam2312 ]]; then
  version="$(/usr/bin/openfoam2312 -show-api)"
fi
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
