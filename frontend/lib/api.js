const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const API_ORIGIN = API_URL.replace(/\/api\/v1\/?$/, "");

async function request(path, options) {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) throw new Error(`Thermoform API ${response.status}`);
  return response.json();
}

export const api = {
  health: () => request("/health"),
  validateDesign: (design) =>
    request("/designs/validate", {
      method: "POST",
      body: JSON.stringify(design),
    }),
  generateDoe: (method, runs) =>
    request("/doe/generate", {
      method: "POST",
      body: JSON.stringify({ method, runs, seed: 42 }),
    }),
  predict: (design) =>
    request("/simulations/predict", {
      method: "POST",
      body: JSON.stringify(design),
    }),
  runPhase1: (method, runs) =>
    request("/workflows/phase1/run", {
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
  predictModel: (modelId, design) =>
    request(`/models/${modelId}/predict`, {
      method: "POST",
      body: JSON.stringify({ design }),
    }),
  runPhase2: (modelId, datasetVersion, acquisition = "EI", iterations = 3) =>
    request("/workflows/phase2/run", {
      method: "POST",
      body: JSON.stringify({
        model_id: modelId,
        dataset_version: datasetVersion,
        acquisition,
        iterations,
        seed: 42,
        noise_std: 0,
        generate_cad: true,
      }),
    }),
  generateCad: (design) =>
    request("/cad/generate", {
      method: "POST",
      body: JSON.stringify({ design }),
    }),
  artifactUrl: (path) => `${API_ORIGIN}${path}`,
};
