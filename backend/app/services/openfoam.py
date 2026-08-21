import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.cae import OpenFoamCaseRequest
from app.domain.phase2 import CadGenerationRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.cad import generate_cad
from app.services.openfoam_thermal_case import thermal_case_files


OPENFOAM_TEMPLATE_VERSION = "openfoam-cht-v10"


def mesh_required_commands() -> list[str]:
    return [
        "surfaceTransformPoints",
        "surfaceCheck",
        "blockMesh",
        "surfaceFeatureExtract",
        "snappyHexMesh",
        "checkMesh",
        "splitMeshRegions",
        "changeDictionary",
    ]


def _required_commands(solver: str) -> list[str]:
    return [*mesh_required_commands(), solver]


def _case_files(request: OpenFoamCaseRequest, stl: str, case_id: str) -> dict[str, str]:
    design = request.design
    mesh_factor = {"coarse": 0.8, "medium": 1.0, "fine": 1.25}[
        request.mesh_profile
    ]
    width_m = max(
        0.12,
        (design.fin_count * design.fin_thickness + (design.fin_count - 1) * design.fin_spacing + 4) / 1000,
    )
    length_m = 0.09
    base_thickness_m = 0.004
    height_m = (design.fin_height + 4) / 1000
    domain = {
        "x_min": -0.03,
        "x_max": length_m + 0.06,
        "y_min": -0.01,
        "y_max": width_m + 0.01,
        "z_min": -0.005,
        "z_max": height_m + 0.03,
    }
    y_background_target_m = design.fin_thickness * 2 / 1000 / mesh_factor
    cells = {
        "x": max(
            36,
            round((domain["x_max"] - domain["x_min"]) / 0.003 * mesh_factor),
        ),
        "y": max(
            30, round((domain["y_max"] - domain["y_min"]) / y_background_target_m)
        ),
        "z": max(
            24,
            round((domain["z_max"] - domain["z_min"]) / 0.002 * mesh_factor),
        ),
    }
    manifest = {
        "case_id": case_id,
        "template_version": OPENFOAM_TEMPLATE_VERSION,
        "mesh_profile": request.mesh_profile,
        "solver": request.solver,
        "mesh_profile": request.mesh_profile,
        "design": design.model_dump(),
        "boundary_conditions": {
            "heat_load_w": request.heat_load_w,
            "ambient_temperature_c": request.ambient_temperature_c,
            "inlet_velocity_m_s": design.air_velocity,
        },
        "geometry_units": "STL source is millimetres; Allrun scales it to metres",
        "geometry_contract": "closed fused base-and-fin union, fully enclosed by the fluid domain",
        "mesh_strategy": {
            "background_cells": cells,
            "surface_refinement_level": 2,
            "resolution_factor": mesh_factor,
            "target_cells_through_fin_thickness": 2 * mesh_factor,
            "per_region_quality_required": True,
        },
        "field_contract": {
            "fluid": "compressible laminar air",
            "solid": "Al 6063-style isotropic thermal properties",
            "interface": "implicit coupled temperature",
            "heat_source": "absolute sensible-enthalpy source in the entire solid region",
            "response_extraction": "solid Tmax, inlet/outlet area-average pressure, integrated solid interface heat flux",
            "smoke_solve_only": True,
            "production_solve_supported": True,
        },
        "case_validated": False,
        "results_available": False,
        "not_cfd_result": True,
    }
    readme = f"""# Thermoform OpenFOAM CHT starter case

Case: {case_id}
Target solver: {request.solver}

This package contains the exact heat-sink STL, boundary-condition manifest,
snappyHexMesh/region-splitting automation, air and aluminum material models,
initial fields, coupled interface conditions, and an absolute solid heat source.
It is an engineering handoff template, not a converged CFD result.

Before accepting results, an analyst must inspect mesh quality and interfaces,
select turbulence/wall treatment for the target OpenFOAM distribution, confirm
material properties, and perform mesh-independence and convergence studies.

Run `./Allrun` inside an initialized OpenFOAM environment to mesh, split regions,
initialize fields, apply boundary dictionaries, and check both region meshes.
`./Allsolve` performs a one-step field/material smoke solve only. Convergence,
energy balance, response extraction, and mesh-independence remain mandatory.
"""
    allrun = f"""#!/bin/sh
set -eu
cd "$(dirname "$0")"
surfaceTransformPoints -scale '(0.001 0.001 0.001)' constant/triSurface/heatsink-mm.stl constant/triSurface/heatsink.stl
surfaceCheck constant/triSurface/heatsink.stl | tee log.surfaceCheck
blockMesh
surfaceFeatureExtract
snappyHexMesh -overwrite
checkMesh -allGeometry -allTopology
cp -R 0.orig 0
splitMeshRegions -cellZones -overwrite
for field in U alphat epsilon k p_rgh; do
  rm -f "0/solid/$field"
done
changeDictionary -region fluid
changeDictionary -region solid
checkMesh -allRegions -allGeometry -allTopology
echo 'Preprocessing and field initialization complete.'
"""
    allsolve = f"""#!/bin/sh
set -eu
cd "$(dirname "$0")"
{request.solver} | tee log.{request.solver}
"""
    control_dict = f"""FoamFile
{{ version 2.0; format ascii; class dictionary; object controlDict; }}
application {request.solver};
startFrom startTime;
startTime 0;
stopAt endTime;
endTime 0.00001;
deltaT 0.00001;
writeControl timeStep;
writeInterval 1;
purgeWrite 1;
writeFormat ascii;
writePrecision 7;
runTimeModifiable false;
adjustTimeStep false;
maxCo 0.3;
maxDi 10;
functions
{{
  solidTemperature
  {{
    type fieldMinMax; libs (fieldFunctionObjects); region solid;
    fields (T); executeControl writeTime; writeControl writeTime;
  }}
  inletPressure
  {{
    type surfaceFieldValue; libs (fieldFunctionObjects); region fluid;
    regionType patch; name inlet; operation areaAverage; fields (p);
    executeControl writeTime; writeControl writeTime; writeFields false;
  }}
  outletPressure
  {{
    type surfaceFieldValue; libs (fieldFunctionObjects); region fluid;
    regionType patch; name outlet; operation areaAverage; fields (p);
    executeControl writeTime; writeControl writeTime; writeFields false;
  }}
  solidHeatFlux
  {{
    type wallHeatFlux; libs (fieldFunctionObjects); region solid;
    patches (solid_to_fluid); executeControl writeTime; writeControl writeTime;
  }}
  solidHeatRate
  {{
    type surfaceFieldValue; libs (fieldFunctionObjects); region solid;
    regionType patch; name solid_to_fluid; operation areaIntegrate;
    fields (wallHeatFlux); executeControl writeTime; writeControl writeTime;
    writeFields false;
  }}
}}
"""
    block_mesh = f"""FoamFile
{{ version 2.0; format ascii; class dictionary; object blockMeshDict; }}
convertToMeters 1;
vertices
(
  ({domain["x_min"]:.6f} {domain["y_min"]:.6f} {domain["z_min"]:.6f}) ({domain["x_max"]:.6f} {domain["y_min"]:.6f} {domain["z_min"]:.6f})
  ({domain["x_max"]:.6f} {domain["y_max"]:.6f} {domain["z_min"]:.6f}) ({domain["x_min"]:.6f} {domain["y_max"]:.6f} {domain["z_min"]:.6f})
  ({domain["x_min"]:.6f} {domain["y_min"]:.6f} {domain["z_max"]:.6f}) ({domain["x_max"]:.6f} {domain["y_min"]:.6f} {domain["z_max"]:.6f})
  ({domain["x_max"]:.6f} {domain["y_max"]:.6f} {domain["z_max"]:.6f}) ({domain["x_min"]:.6f} {domain["y_max"]:.6f} {domain["z_max"]:.6f})
);
blocks (hex (0 1 2 3 4 5 6 7) ({cells["x"]} {cells["y"]} {cells["z"]}) simpleGrading (1 1 1));
edges ();
boundary
(
 inlet {{ type patch; faces ((0 4 7 3)); }}
 outlet {{ type patch; faces ((1 2 6 5)); }}
 tunnelWalls {{ type wall; faces ((0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)); }}
);
mergePatchPairs ();
"""
    surface_features = """FoamFile
{ version 2.0; format ascii; class dictionary; object surfaceFeatureExtractDict; }
heatsink.stl { extractionMethod extractFromSurface; extractFromSurfaceCoeffs { includedAngle 150; } writeObj yes; }
"""
    snappy = f"""FoamFile
{{ version 2.0; format ascii; class dictionary; object snappyHexMeshDict; }}
castellatedMesh true; snap true; addLayers false;
geometry {{ heatsink.stl {{ type triSurfaceMesh; name heatsink; }} }}
castellatedMeshControls
{{
  maxLocalCells 2000000; maxGlobalCells 4000000; minRefinementCells 0; nCellsBetweenLevels 3;
  features ({{ file "heatsink.eMesh"; level 2; }});
  refinementSurfaces {{ heatsink {{ level (2 2); }} }}
  refinementRegions {{}}
  resolveFeatureAngle 30;
  locationsInMesh
  (
    (({domain["x_min"] / 2:.6f} {width_m / 2:.6f} {height_m / 2:.6f}) fluid)
    (({length_m / 2:.6f} {width_m / 2:.6f} {base_thickness_m / 2:.6f}) solid)
  );
  allowFreeStandingZoneFaces false;
}}
snapControls {{ nSmoothPatch 3; tolerance 2.0; nSolveIter 30; nRelaxIter 5; }}
addLayersControls {{ relativeSizes true; layers {{}}; expansionRatio 1.0; finalLayerThickness 0.3; minThickness 0.1; nGrow 0; featureAngle 60; nRelaxIter 3; nSmoothSurfaceNormals 1; nSmoothNormals 3; nSmoothThickness 10; maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3; minMedianAxisAngle 90; nBufferCellsNoExtrude 0; nLayerIter 50; }}
meshQualityControls {{ #include "meshQualityDict" }}
mergeTolerance 1e-6;
"""
    files = {
        "README.md": readme,
        "case.json": json.dumps(manifest, indent=2, sort_keys=True),
        "Allrun": allrun,
        "Allsolve": allsolve,
        "system/controlDict": control_dict,
        "system/fvSchemes": "FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }\nddtSchemes {}\ngradSchemes {}\ndivSchemes {}\nlaplacianSchemes {}\ninterpolationSchemes {}\nsnGradSchemes {}\n",
        "system/fvSolution": "FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }\nPIMPLE { nOuterCorrectors 1; }\n",
        "system/blockMeshDict": block_mesh,
        "system/surfaceFeatureExtractDict": surface_features,
        "system/snappyHexMeshDict": snappy,
        "system/meshQualityDict": "maxNonOrtho 65; maxBoundarySkewness 20; maxInternalSkewness 4; maxConcave 60; minVol 1e-13; minTetQuality 1e-15; minArea -1; minTwist 0.02; minDeterminant 0.001; minFaceWeight 0.05; minVolRatio 0.01; minTriangleTwist -1; nSmoothScale 8; errorReduction 0.5;\n",
        "system/decomposeParDict": "FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains 2;\nmethod scotch;\n",
        "system/fluid/decomposeParDict": "FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains 2;\nmethod scotch;\n",
        "system/solid/decomposeParDict": "FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains 2;\nmethod scotch;\n",
        "constant/regionProperties": "FoamFile { version 2.0; format ascii; class dictionary; object regionProperties; }\nregions ( fluid (fluid) solid (solid) );\n",
        "constant/triSurface/heatsink-mm.stl": stl,
    }
    files.update(thermal_case_files(request))
    return files


def _zip_files(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            info = zipfile.ZipInfo(filename)
            info.external_attr = (
                0o755 if filename in {"Allrun", "Allsolve"} else 0o644
            ) << 16
            archive.writestr(info, content)
    return output.getvalue()


def _execute_if_requested(
    request: OpenFoamCaseRequest, files: dict[str, str], solver_ready: bool
) -> tuple[str, str | None]:
    if not request.run_solver:
        return "not_requested", None
    required = _required_commands(request.solver)
    missing = [command for command in required if shutil.which(command) is None]
    if missing:
        return "solver_unavailable", f"Missing OpenFOAM commands: {', '.join(missing)}"
    if not solver_ready:
        return (
            "validation_required",
            "Execution blocked: this generated heat-sink case is a preprocessing starter and has not passed geometry, interface, field, and material validation.",
        )
    with tempfile.TemporaryDirectory(prefix="thermoform-openfoam-") as temporary:
        root = Path(temporary)
        for filename, content in files.items():
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (root / "Allrun").chmod(0o755)
        try:
            result = subprocess.run(
                [str(root / "Allrun")],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=request.max_runtime_seconds,
                check=False,
            )
            log = result.stdout + "\n" + result.stderr
            return ("completed" if result.returncode == 0 else "failed"), log[-100000:]
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + "\n" + (exc.stderr or "")
            return "timed_out", output[-100000:]
        except OSError as exc:
            return "failed", str(exc)


def prepare_openfoam_case(
    request: OpenFoamCaseRequest, repository: ArtifactRepository | None = None
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    cad = generate_cad(CadGenerationRequest(design=request.design), repository)
    stl_name = f'{cad["cad_id"]}.stl'
    stl = repository.cad_artifact_path(cad["cad_id"], stl_name).read_text(encoding="utf-8")
    fingerprint = {
        "design": request.design.model_dump(),
        "heat_load_w": request.heat_load_w,
        "ambient_temperature_c": request.ambient_temperature_c,
        "solver": request.solver,
        "mesh_profile": request.mesh_profile,
        "template": OPENFOAM_TEMPLATE_VERSION,
    }
    case_id = repository.version(fingerprint, "cae")
    files = _case_files(request, stl, case_id)
    geometry_validated = bool(cad["freecad_executed"] and cad["stl_generator"] == "FreeCAD")
    solver_ready = False
    solver_status, solver_log = _execute_if_requested(request, files, solver_ready)
    openfoam_available = all(shutil.which(command) is not None for command in _required_commands(request.solver))
    package_name = f"{case_id}.zip"
    repository.save_cae_artifact(case_id, package_name, _zip_files(files))
    if solver_log:
        repository.save_cae_artifact(case_id, "solver.log", solver_log)
    result = {
        "case_id": case_id,
        "case_generated": True,
        "case_validated": False,
        "geometry_validated": geometry_validated,
        "solver_ready": solver_ready,
        "template_version": OPENFOAM_TEMPLATE_VERSION,
        "openfoam_available": openfoam_available,
        "solver_requested": request.run_solver,
        "solver_executed": solver_status in {"completed", "failed", "timed_out"},
        "solver_status": solver_status,
        "results_available": False,
        "result_type": None,
        "not_cfd_result": True,
        "cad_id": cad["cad_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "downloads": {
            "case_package": f"/api/v1/cae/{case_id}/artifacts/{package_name}",
            "solver_log": f"/api/v1/cae/{case_id}/artifacts/solver.log" if solver_log else None,
        },
        "notice": "OpenFOAM preprocessing package generated. No CFD/CAE result exists until the case is validated and a solver run completes successfully.",
        "validation_gates": {
            "watertight_union_geometry": geometry_validated,
            "region_interfaces": False,
            "initial_and_boundary_fields": False,
            "material_properties": False,
            "mesh_quality": False,
            "convergence": False,
            "energy_balance": False,
        },
    }
    repository.save_cae_artifact(case_id, "metadata.json", json.dumps(result, indent=2, sort_keys=True))
    return result
