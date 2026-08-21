from app.domain.cae import OpenFoamCaseRequest


def _header(field_class: str, object_name: str) -> str:
    return (
        "FoamFile\n"
        f"{{ version 2.0; format ascii; class {field_class}; object {object_name}; }}\n"
    )


def thermal_case_files(request: OpenFoamCaseRequest) -> dict[str, str]:
    ambient_k = request.ambient_temperature_c + 273.15
    velocity = request.design.air_velocity
    generic_scalar = lambda name, dimensions, value: (
        _header("volScalarField", name)
        + f"dimensions {dimensions};\ninternalField uniform {value};\n"
        + 'boundaryField { #includeEtc "caseDicts/setConstraintTypes" ".*" { type calculated; value $internalField; } }\n'
    )
    temperature = generic_scalar("T", "[0 0 0 1 0 0 0]", f"{ambient_k:.6f}")
    pressure = generic_scalar("p", "[1 -1 -2 0 0 0 0]", "100000")
    pressure_rgh = generic_scalar("p_rgh", "[1 -1 -2 0 0 0 0]", "100000")
    density = generic_scalar("rho", "[1 -3 0 0 0 0 0]", "1.2")
    alphat = generic_scalar("alphat", "[1 -1 -1 0 0 0 0]", "0")
    turbulent_k = generic_scalar("k", "[0 2 -2 0 0 0 0]", "0.01")
    epsilon = generic_scalar("epsilon", "[0 2 -3 0 0 0 0]", "0.01")
    velocity_field = (
        _header("volVectorField", "U")
        + f"dimensions [0 1 -1 0 0 0 0];\ninternalField uniform ({velocity:.8g} 0 0);\n"
        + 'boundaryField { #includeEtc "caseDicts/setConstraintTypes" ".*" { type calculated; value $internalField; } }\n'
    )
    fluid_change = _header("dictionary", "changeDictionaryDict") + f"""
U
{{
  internalField uniform ({velocity:.8g} 0 0);
  boundaryField
  {{
    ".*" {{ type noSlip; }}
    inlet {{ type fixedValue; value uniform ({velocity:.8g} 0 0); }}
    outlet {{ type pressureInletOutletVelocity; value uniform (0 0 0); }}
    tunnelWalls {{ type slip; }}
    fluid_to_solid {{ type noSlip; }}
  }}
}}
T
{{
  internalField uniform {ambient_k:.6f};
  boundaryField
  {{
    ".*" {{ type zeroGradient; }}
    inlet {{ type fixedValue; value uniform {ambient_k:.6f}; }}
    outlet {{ type inletOutlet; inletValue uniform {ambient_k:.6f}; value uniform {ambient_k:.6f}; }}
    fluid_to_solid
    {{
      type compressible::turbulentTemperatureRadCoupledMixed;
      Tnbr T; kappaMethod fluidThermo; value uniform {ambient_k:.6f}; useImplicit true;
    }}
  }}
}}
p_rgh
{{
  internalField uniform 100000;
  boundaryField
  {{
    ".*" {{ type fixedFluxPressure; value uniform 100000; }}
    outlet {{ type fixedValue; value uniform 100000; }}
  }}
}}
p
{{
  internalField uniform 100000;
  boundaryField {{ ".*" {{ type calculated; value uniform 100000; }} }}
}}
rho
{{
  internalField uniform 1.2;
  boundaryField {{ ".*" {{ type calculated; value uniform 1.2; }} }}
}}
alphat
{{
  internalField uniform 0;
  boundaryField {{ ".*" {{ type calculated; value uniform 0; }} }}
}}
k
{{
  internalField uniform 0.01;
  boundaryField {{ ".*" {{ type calculated; value uniform 0.01; }} }}
}}
epsilon
{{
  internalField uniform 0.01;
  boundaryField {{ ".*" {{ type calculated; value uniform 0.01; }} }}
}}
"""
    solid_change = _header("dictionary", "changeDictionaryDict") + f"""
T
{{
  internalField uniform {ambient_k:.6f};
  boundaryField
  {{
    ".*" {{ type zeroGradient; value uniform {ambient_k:.6f}; }}
    solid_to_fluid
    {{
      type compressible::turbulentTemperatureRadCoupledMixed;
      Tnbr T; kappaMethod solidThermo; value uniform {ambient_k:.6f}; useImplicit true;
    }}
  }}
}}
p
{{
  internalField uniform 100000;
  boundaryField {{ ".*" {{ type calculated; value uniform 100000; }} }}
}}
rho
{{
  internalField uniform 2719;
  boundaryField {{ ".*" {{ type calculated; value uniform 2719; }} }}
}}
"""
    fluid_thermo = _header("dictionary", "thermophysicalProperties") + """
thermoType
{
  type heRhoThermo; mixture pureMixture; transport const; thermo hConst;
  equationOfState perfectGas; specie specie; energy sensibleEnthalpy;
}
mixture
{
  specie { molWeight 28.9; }
  thermodynamics { Cp 1000; Hf 0; }
  transport { mu 1.8e-05; Pr 0.7; }
}
"""
    solid_thermo = _header("dictionary", "thermophysicalProperties") + """
thermoType
{
  type heSolidThermo; mixture pureMixture; transport constIso; thermo hConst;
  equationOfState rhoConst; specie specie; energy sensibleEnthalpy;
}
mixture
{
  specie { molWeight 26.9815; }
  transport { kappa 202.4; }
  thermodynamics { Hf 0; Cp 871; }
  equationOfState { rho 2719; }
}
"""
    fluid_schemes = _header("dictionary", "fvSchemes") + """
ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes
{
  default none; div(phi,U) Gauss upwind; div(phi,K) Gauss linear;
  div(phi,h) Gauss upwind; div(phi,k) Gauss upwind;
  div(phi,epsilon) Gauss upwind; div(phi,R) Gauss upwind;
  div(R) Gauss linear; div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
"""
    fluid_solution = _header("dictionary", "fvSolution") + """
solvers
{
  "(rho|rhoFinal)" { solver PCG; preconditioner DIC; tolerance 1e-7; relTol 0; }
  p_rgh { solver PCG; preconditioner DIC; tolerance 1e-7; relTol 0.01; }
  p_rghFinal { $p_rgh; tolerance 1e-7; relTol 0; }
  h { solver PBiCGStab; preconditioner DILU; tolerance 1e-8; relTol 0.1; minIter 1; }
  hFinal { $h; tolerance 1e-8; relTol 0; minIter 1; }
  "(U|k|epsilon|R)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-7; relTol 0.1; }
  "(U|k|epsilon|R)Final" { $U; tolerance 1e-7; relTol 0; }
}
PIMPLE { momentumPredictor yes; nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 100000; }
relaxationFactors { equations { "h.*" 1; "U.*" 1; } }
"""
    solid_schemes = _header("dictionary", "fvSchemes") + """
ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes { default none; }
laplacianSchemes { default none; laplacian(alpha,h) Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
"""
    solid_solution = _header("dictionary", "fvSolution") + """
solvers
{
  h { solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0.1; }
  hFinal { $h; tolerance 1e-8; relTol 0; }
}
PIMPLE { nNonOrthogonalCorrectors 0; }
"""
    radiation = _header("dictionary", "radiationProperties") + "radiation off;\nradiationModel none;\n"
    heat_source = _header("dictionary", "fvOptions") + f"""
heatSource
{{
  type scalarSemiImplicitSource;
  active true;
  selectionMode all;
  volumeMode absolute;
  sources {{ h ({request.heat_load_w:.8g} 0); }}
}}
"""
    return {
        "0.orig/T": temperature,
        "0.orig/U": velocity_field,
        "0.orig/p": pressure,
        "0.orig/p_rgh": pressure_rgh,
        "0.orig/rho": density,
        "0.orig/alphat": alphat,
        "0.orig/k": turbulent_k,
        "0.orig/epsilon": epsilon,
        "constant/g": _header("uniformDimensionedVectorField", "g")
        + "dimensions [0 1 -2 0 0 0 0];\nvalue (0 0 0);\n",
        "constant/fluid/thermophysicalProperties": fluid_thermo,
        "constant/fluid/turbulenceProperties": _header("dictionary", "turbulenceProperties")
        + "simulationType laminar;\n",
        "constant/fluid/radiationProperties": radiation,
        "constant/solid/thermophysicalProperties": solid_thermo,
        "constant/solid/radiationProperties": radiation,
        "constant/solid/fvOptions": heat_source,
        "system/fluid/changeDictionaryDict": fluid_change,
        "system/fluid/fvSchemes": fluid_schemes,
        "system/fluid/fvSolution": fluid_solution,
        "system/solid/changeDictionaryDict": solid_change,
        "system/solid/fvSchemes": solid_schemes,
        "system/solid/fvSolution": solid_solution,
    }
