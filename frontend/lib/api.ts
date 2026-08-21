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
};
