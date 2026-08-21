export type DesignParameters = {
  fin_count: number;
  fin_thickness: number;
  fin_height: number;
  fin_spacing: number;
  air_velocity: number;
  heat_load?: number;
  ambient_temperature?: number;
};

export type SimulationResult = {
  t_max: number;
  thermal_resistance: number;
  pressure_drop: number;
  mass: number;
  fin_efficiency: number;
  heat_transfer_coefficient: number;
  simulator_version: string;
};

export type ExperimentRecord = DesignParameters &
  SimulationResult & {
    run: number;
  };

export type ModelMetric = {
  model: string;
  r2: number;
  rmse: number;
  mae: number;
  cv_rmse: number;
  training_ms: number;
  inference_ms: number;
};

export type AnovaRow = {
  source: string;
  sum_sq: number;
  df: number;
  mean_sq: number;
  f_value: number;
  p_value: number;
};

export type OptimizationCandidate = {
  design: DesignParameters;
  responses: Pick<
    SimulationResult,
    "t_max" | "thermal_resistance" | "pressure_drop" | "mass"
  >;
};

export type Phase1Result = {
  workflow_id: string;
  status: "completed";
  method: string;
  seed: number;
  experiment_count: number;
  experiments: ExperimentRecord[];
  analysis: {
    response: string;
    r_squared: number;
    rmse: number;
    anova: AnovaRow[];
    main_effects: AnovaRow[];
    interactions: AnovaRow[];
    diagnostics: {
      residual_vs_fitted: { fitted: number; residual: number }[];
      outlier_indices: number[];
      shapiro_p_value: number | null;
    };
  };
  model_id: string;
  model_metrics: Record<string, ModelMetric[]>;
  selected_models: Record<string, string>;
  optimization: {
    mode: string;
    objectives: string[];
    recommended: OptimizationCandidate | null;
    pareto: OptimizationCandidate[];
    evaluations: number;
    success: boolean;
  };
  dataset_version: string;
  model_version: string;
  simulator_version: string;
  traceability: Record<string, unknown>;
};

export type SurrogatePrediction = Pick<
  SimulationResult,
  "t_max" | "thermal_resistance" | "pressure_drop" | "mass"
> & { t_max_uncertainty?: number };

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) throw new Error(`Thermoform API ${response.status}`);
  return response.json() as Promise<T>;
}

export const api = {
  health: () =>
    request<{ status: string; simulator_version: string }>("/health"),
  validateDesign: (design: DesignParameters) =>
    request<{ valid: boolean }>("/designs/validate", {
      method: "POST",
      body: JSON.stringify(design),
    }),
  generateDoe: (method: string, runs: number) =>
    request<{ runs: number; dataset_version: string }>("/doe/generate", {
      method: "POST",
      body: JSON.stringify({ method, runs, seed: 42 }),
    }),
  predict: (design: DesignParameters) =>
    request<SimulationResult>("/simulations/predict", {
      method: "POST",
      body: JSON.stringify(design),
    }),
  runPhase1: (method: string, runs: number) =>
    request<Phase1Result>("/workflows/phase1/run", {
      method: "POST",
      body: JSON.stringify({
        method,
        runs,
        seed: 42,
        noise_std: 0,
        response_for_analysis: "t_max",
        optimization_generations: 25,
      }),
    }),
  predictModel: (modelId: string, design: DesignParameters) =>
    request<SurrogatePrediction>(`/models/${modelId}/predict`, {
      method: "POST",
      body: JSON.stringify({ design }),
    }),
};
