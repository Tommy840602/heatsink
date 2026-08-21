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

async function submitJob(task, payload) {
  return request("/jobs", {
    method: "POST",
    body: JSON.stringify({ task, payload }),
  });
}

async function getJob(jobId) {
  return request(`/jobs/${jobId}`);
}

async function cancelJob(jobId) {
  return request(`/jobs/${jobId}/cancel`, { method: "POST" });
}

function caeCampaignPayload(design, settings) {
  return {
    design,
    heat_load_w: 100,
    ambient_temperature_c: 25,
    delta_t_s: 0.00001,
    write_interval_steps: 10,
    segment_runtime_seconds: 3600,
    max_total_runtime_seconds: 18000,
    ...settings,
  };
}

async function runJob(task, payload, onStatus) {
  let job = await submitJob(task, payload);
  onStatus?.(job);
  for (let attempt = 0; attempt < 240; attempt += 1) {
    if (job.status === "finished") return job.result;
    if (["failed", "stopped", "canceled"].includes(job.status)) {
      throw new Error(job.error ?? `${task} job failed`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 750));
    job = await getJob(job.job_id);
    onStatus?.(job);
  }
  throw new Error(`${task} job timed out while polling`);
}

export const api = {
  submitJob,
  getJob,
  cancelJob,
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
  runPhase1: (method, runs, onStatus) =>
    runJob(
      "phase1",
      {
        method,
        runs,
        seed: 42,
        noise_std: 0,
        response_for_analysis: "t_max",
        optimization_generations: 25,
      },
      onStatus,
    ),
  predictModel: (modelId, design) =>
    request(`/models/${modelId}/predict`, {
      method: "POST",
      body: JSON.stringify({ design }),
    }),
  runPhase2: (modelId, datasetVersion, acquisition = "EI", iterations = 3, onStatus) =>
    runJob(
      "phase2",
      {
        model_id: modelId,
        dataset_version: datasetVersion,
        acquisition,
        iterations,
        seed: 42,
        noise_std: 0,
        generate_cad: true,
      },
      onStatus,
    ),
  prepareCae: (design, runSolver = false, onStatus) =>
    runJob(
      "cae",
      {
        design,
        heat_load_w: 100,
        ambient_temperature_c: 25,
        run_solver: runSolver,
        solver: "chtMultiRegionFoam",
      },
      onStatus,
    ),
  runCaeBenchmark: (onStatus) =>
    runJob(
      "cae_benchmark",
      {
        tutorial: "multiRegionHeater",
        max_runtime_seconds: 1800,
        criteria: {
          max_non_orthogonality: 65,
          max_skewness: 4,
          max_final_residual: 0.0001,
          max_energy_imbalance_percent: 5,
          min_residual_samples: 3,
        },
      },
      onStatus,
    ),
  startCaeCampaign: (design, settings) =>
    submitJob("cae_campaign", caeCampaignPayload(design, settings)),
  resumeCaeCampaign: (campaignId, design, settings) =>
    request(`/cae/campaigns/${campaignId}/resume`, {
      method: "POST",
      body: JSON.stringify(caeCampaignPayload(design, settings)),
    }),
  runMeshStudy: (campaignIds, onStatus) =>
    runJob(
      "cae_mesh_study",
      {
        campaign_ids: campaignIds,
        max_t_max_relative_change_percent: 1,
        max_pressure_drop_relative_change_percent: 5,
      },
      onStatus,
    ),
  listCaeCampaigns: (limit = 50) =>
    request(`/cae/campaigns?limit=${limit}`),
  listCaeResumeAttempts: (limit = 50) =>
    request(`/cae/resume-attempts?limit=${limit}`),
  reconcileCaeResumeAttempts: (limit = 50, staleAfterSeconds = 900) =>
    request(
      `/cae/resume-attempts/reconcile?limit=${limit}&stale_after_seconds=${staleAfterSeconds}`,
      { method: "POST" },
    ),
  getCaeResumeWatchdog: () => request("/cae/resume-watchdog"),
  retryCaeResumeAttempt: (attemptId) =>
    request(`/cae/resume-attempts/${attemptId}/retry`, {
      method: "POST",
    }),
  getCaeCampaign: (campaignId) =>
    request(`/cae/campaigns/${campaignId}`),
  listMeshStudies: (limit = 20) =>
    request(`/cae/mesh-studies?limit=${limit}`),
  getMeshStudy: (meshStudyId) =>
    request(`/cae/mesh-studies/${meshStudyId}`),
  generateCad: (design) =>
    request("/cad/generate", {
      method: "POST",
      body: JSON.stringify({ design }),
    }),
  artifactUrl: (path) => `${API_ORIGIN}${path}`,
};
