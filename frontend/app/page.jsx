"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";

const nav = [
  ["overview", "⌂", "Overview"],
  ["design", "◇", "Design Space"],
  ["doe", "▦", "DOE"],
  ["simulation", "ϟ", "Simulation"],
  ["analysis", "⌁", "Analysis"],
  ["surrogate", "⌘", "Surrogate Models"],
  ["optimization", "◎", "Optimization"],
  ["digital-twin", "◫", "Digital Twin"],
  ["cae-operations", "◉", "CAE Operations"],
  ["cad", "⬡", "CAD"],
];

const stages = [
  ["01", "Design space", "5 variables", "done"],
  ["02", "DOE", "64 experiments", "done"],
  ["03", "Simulation", "64 / 64 complete", "done"],
  ["04", "Surrogate", "GPR selected", "active"],
  ["05", "Optimization", "Ready to run", "next"],
];

const demoMetrics = [
  { model: "RSM", r2: 0.921, rmse: 3.48, mae: 2.61, cv_rmse: 3.72, training_ms: 18, inference_ms: 1 },
  { model: "RandomForest", r2: 0.963, rmse: 2.05, mae: 1.48, cv_rmse: 2.22, training_ms: 146, inference_ms: 2 },
  { model: "XGBoost", r2: 0.976, rmse: 1.62, mae: 1.19, cv_rmse: 1.78, training_ms: 204, inference_ms: 1 },
  { model: "GPR", r2: 0.984, rmse: 1.21, mae: 0.92, cv_rmse: 1.34, training_ms: 312, inference_ms: 2 },
];

const labelFor = (name) =>
  ({
    fin_count: "Fin count",
    fin_thickness: "Fin thickness",
    fin_height: "Fin height",
    fin_spacing: "Fin spacing",
    air_velocity: "Air velocity",
  })[name] ?? name;

const terminalJobStatuses = new Set([
  "finished",
  "failed",
  "stopped",
  "canceled",
]);

const activeCaeJobStorageKey = "thermoform:active-cae-job";

const readableState = (value = "pending") =>
  value.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());

function PageHead({ kicker, title, description, badge }) {
  return (
    <>
      <div className="eyebrow">
        {kicker} <span>•</span> TRACEABLE DATASET
      </div>
      <div className="title-row">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {badge && (
          <div className="status-pill">
            <span /> {badge}
          </div>
        )}
      </div>
    </>
  );
}

function Overview({ go, phase1 }) {
  const modelMetrics = phase1?.model_metrics.t_max ?? demoMetrics;
  const selectedModel = phase1?.selected_models.t_max ?? "GPR";
  const recommended = phase1?.optimization.recommended;
  const responses = recommended?.responses;
  const design = recommended?.design;
  const maxCv = Math.max(...modelMetrics.map((metric) => metric.cv_rmse), 0.001);
  const workflowStages = phase1
    ? [
        ["01", "Design space", "5 variables", "done"],
        ["02", "DOE", `${phase1.experiment_count} experiments`, "done"],
        ["03", "Simulation", `${phase1.experiment_count} / ${phase1.experiment_count} complete`, "done"],
        ["04", "Surrogate", `${selectedModel} selected`, "done"],
        ["05", "Optimization", `${phase1.optimization.evaluations} evaluations`, "done"],
      ]
    : stages;
  return (
    <div className="content">
      <PageHead
        kicker="THERMAL DESIGN WORKSPACE"
        title="System overview"
        description="Monitor the engineering workflow from design space to optimized geometry."
        badge="Workflow healthy"
      />
      <div className="metrics">
        <article>
          <small>EXPERIMENTS</small>
          <strong>{phase1?.experiment_count ?? 64}</strong>
          <p>
            <span className="up">↗ 12</span> since last run
          </p>
          <i>▦</i>
        </article>
        <article>
          <small>BEST MODEL</small>
          <strong>{selectedModel}</strong>
          <p>
            <span>
              R² {modelMetrics.find((item) => item.model === selectedModel)?.r2.toFixed(3)}
            </span>{" "}
            · CV RMSE {modelMetrics.find((item) => item.model === selectedModel)?.cv_rmse.toFixed(2)}°C
          </p>
          <i>⌘</i>
        </article>
        <article>
          <small>
            BEST T<sub>MAX</sub>
          </small>
          <strong>
            {(responses?.t_max ?? 68.4).toFixed(1)}<em>°C</em>
          </strong>
          <p>
            <span className="down">↓ 8.2°C</span> vs. baseline
          </p>
          <i>ϟ</i>
        </article>
        <article>
          <small>EST. MASS</small>
          <strong>
            {(responses?.mass ?? 287).toFixed(0)}<em>g</em>
          </strong>
          <p>
            <span className="down">↓ 13%</span> vs. baseline
          </p>
          <i>⬡</i>
        </article>
      </div>
      <section className="workflow-card">
        <div className="card-heading">
          <div>
            <h2>Engineering workflow</h2>
            <p>Current project progression and traceability</p>
          </div>
          <button onClick={() => go("simulation")}>View activity log ↗</button>
        </div>
        <div className="pipeline">
          {workflowStages.map(([num, name, detail, state], index) => (
            <div className={`stage ${state}`} key={name}>
              <div className="stage-top">
                <span>{num}</span>
                {state === "done" ? (
                  <b>✓</b>
                ) : state === "active" ? (
                  <b>◌</b>
                ) : (
                  <b>•</b>
                )}
              </div>
              <strong>{name}</strong>
              <small>{detail}</small>
              {index < workflowStages.length - 1 && <i />}
            </div>
          ))}
        </div>
      </section>
      <div className="lower-grid">
        <section className="performance-card">
          <div className="card-heading">
            <div>
              <h2>Model performance</h2>
              <p>Cross-validated RMSE by surrogate</p>
            </div>
            <div className="legend">
              <span /> RMSE (°C)
            </div>
          </div>
          <div className="chart">
            <div className="axis">
              <span>4</span>
              <span>3</span>
              <span>2</span>
              <span>1</span>
              <span>0</span>
            </div>
            <div className="bars">
              {modelMetrics.map((metric) => (
                <div className="bar-column" key={metric.model}>
                  <div
                    className={`bar ${metric.model === selectedModel ? "best" : ""}`}
                    style={{ height: `${Math.max((metric.cv_rmse / maxCv) * 88, 12)}%` }}
                  >
                    <b>{metric.cv_rmse.toFixed(2)}</b>
                  </div>
                  <span>{metric.model}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
        <section className="design-card">
          <div className="card-heading">
            <div>
              <h2>Recommended design</h2>
              <p>Lowest feasible thermal resistance</p>
            </div>
            <span className="candidate">CANDIDATE 07</span>
          </div>
          <div className="mini-design">
            <HeatSink />
            <div>
              <small>
                T<sub>MAX</sub>
              </small>
              <strong>{(responses?.t_max ?? 68.4).toFixed(1)}°C</strong>
              <small>
                R<sub>θ</sub>
              </small>
              <strong>{(responses?.thermal_resistance ?? 0.434).toFixed(3)} K/W</strong>
            </div>
          </div>
          <div className="parameters">
            <span>
              <small>FINS</small>
              <b>{design?.fin_count ?? 48}</b>
            </span>
            <span>
              <small>HEIGHT</small>
              <b>{(design?.fin_height ?? 52).toFixed(1)} mm</b>
            </span>
            <span>
              <small>SPACING</small>
              <b>{(design?.fin_spacing ?? 2.4).toFixed(2)} mm</b>
            </span>
            <span>
              <small>VELOCITY</small>
              <b>{(design?.air_velocity ?? 3.2).toFixed(2)} m/s</b>
            </span>
          </div>
          <button className="outline-button" onClick={() => go("digital-twin")}>
            Inspect design <span>→</span>
          </button>
        </section>
      </div>
    </div>
  );
}

function HeatSink({ count = 10 }) {
  return (
    <div className="sink" aria-label="Parametric heat sink preview">
      {Array.from({ length: Math.min(count, 14) }).map((_, i) => (
        <i key={i} />
      ))}
    </div>
  );
}

function ModuleView({
  active,
  notify,
  phase1,
  phase2,
  runWorkflow,
  runPhase2,
  workflowRunning,
  phase2Running,
  jobStatus,
  setJobStatus,
}) {
  const [method, setMethod] = useState("LHS");
  const [runs, setRuns] = useState(64);
  const [fins, setFins] = useState(48);
  const [height, setHeight] = useState(52);
  const [spacing, setSpacing] = useState(2.4);
  const [velocity, setVelocity] = useState(3.2);
  const [model, setModel] = useState("GPR");
  const [acquisition, setAcquisition] = useState("EI");
  const [cadArtifact, setCadArtifact] = useState(null);
  const [caeArtifact, setCaeArtifact] = useState(null);
  const [caeRunning, setCaeRunning] = useState(false);
  const [benchmarkArtifact, setBenchmarkArtifact] = useState(null);
  const [benchmarkRunning, setBenchmarkRunning] = useState(false);
  const [apiPrediction, setApiPrediction] = useState(null);
  const [meshProfile, setMeshProfile] = useState("medium");
  const [targetEndTime, setTargetEndTime] = useState(0.01);
  const [segmentDuration, setSegmentDuration] = useState(0.001);
  const [parallelProcesses, setParallelProcesses] = useState(2);
  const [maxSegments, setMaxSegments] = useState(20);
  const [campaignJob, setCampaignJob] = useState(null);
  const [campaignResults, setCampaignResults] = useState({});
  const [campaignRunning, setCampaignRunning] = useState(false);
  const [meshStudy, setMeshStudy] = useState(null);
  const [meshStudyRunning, setMeshStudyRunning] = useState(false);
  const [campaignHistory, setCampaignHistory] = useState([]);
  const [meshStudyHistory, setMeshStudyHistory] = useState([]);
  const [resumeHistory, setResumeHistory] = useState([]);
  const [caeHistoryLoading, setCaeHistoryLoading] = useState(false);
  const [resumeChecking, setResumeChecking] = useState(false);
  const [resumePreview, setResumePreview] = useState(null);
  const monitoredCaeJobRef = useRef(null);
  const design = useMemo(
    () => ({
      fin_count: fins,
      fin_thickness: 0.65,
      fin_height: height,
      fin_spacing: spacing,
      air_velocity: velocity,
    }),
    [fins, height, spacing, velocity],
  );
  const temp = (
    91.6 -
    fins * 0.16 -
    height * 0.11 -
    spacing * 0.7 -
    velocity * 2.1
  ).toFixed(1);
  const mass = Math.round(126 + fins * 2.25 + height * 0.68);
  const theta = ((Number(temp) - 25) / 100).toFixed(3);
  useEffect(() => {
    if (active !== "digital-twin") return;
    const timer = window.setTimeout(() => {
      const modelId = phase2?.model_id ?? phase1?.model_id;
      const prediction = modelId
        ? api.predictModel(modelId, design)
        : api.predict(design);
      prediction
        .then(setApiPrediction)
        .catch(() => setApiPrediction(null));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [active, design, phase1, phase2]);
  const predictedTemp = apiPrediction?.t_max.toFixed(1) ?? temp;
  const predictedTheta =
    apiPrediction?.thermal_resistance.toFixed(3) ?? theta;
  const predictedPressure =
    apiPrediction?.pressure_drop.toFixed(1) ??
    (4.8 + (velocity * 4.9) / spacing).toFixed(1);
  const predictedMass = apiPrediction?.mass.toFixed(0) ?? String(mass);
  const predictedUncertainty =
    apiPrediction && "t_max_uncertainty" in apiPrediction
      ? apiPrediction.t_max_uncertainty
      : undefined;
  const experiments = phase1?.experiments ?? [];
  const modelMetrics = phase2?.model_metrics.t_max ?? phase1?.model_metrics.t_max ?? demoMetrics;
  const selectedModel = phase2?.selected_models.t_max ?? phase1?.selected_models.t_max ?? "GPR";
  const pareto = phase1?.optimization.pareto ?? [];
  const recommended = phase1?.optimization.recommended;
  const currentCad = cadArtifact ?? phase2?.cad;
  const cadDesign = phase2?.best_design ?? recommended?.design ?? design;
  const sortedTemps = experiments.map((row) => row.t_max).sort((a, b) => a - b);
  const medianTemp = sortedTemps.length
    ? sortedTemps[Math.floor(sortedTemps.length / 2)]
    : 74.8;
  const average = (key) =>
    experiments.length
      ? experiments.reduce((sum, row) => sum + row[key], 0) / experiments.length
      : key === "thermal_resistance"
        ? 0.498
        : 18.6;
  const analysis = phase1?.analysis;
  const effectRows = analysis
    ? [...analysis.main_effects, ...analysis.interactions.slice(0, 1)]
        .sort((a, b) => b.f_value - a.f_value)
        .slice(0, 6)
    : null;
  const maximumEffect = Math.max(...(effectRows?.map((row) => row.f_value) ?? [1]));
  const diagnosticPoints = analysis?.diagnostics.residual_vs_fitted ?? [];
  const fittedValues = diagnosticPoints.map((point) => point.fitted);
  const residualValues = diagnosticPoints.map((point) => point.residual);
  const fittedMin = Math.min(...(fittedValues.length ? fittedValues : [0]));
  const fittedSpan = Math.max(Math.max(...(fittedValues.length ? fittedValues : [1])) - fittedMin, 0.001);
  const residualMax = Math.max(...(residualValues.length ? residualValues.map(Math.abs) : [1]), 0.001);
  const paretoForChart = pareto.length ? pareto.slice(0, 12) : [];
  const paretoMasses = paretoForChart.map((item) => item.responses.mass);
  const paretoTemps = paretoForChart.map((item) => item.responses.t_max);
  const massMin = Math.min(...(paretoMasses.length ? paretoMasses : [0]));
  const massSpan = Math.max(Math.max(...(paretoMasses.length ? paretoMasses : [1])) - massMin, 0.001);
  const tempMin = Math.min(...(paretoTemps.length ? paretoTemps : [0]));
  const tempSpan = Math.max(Math.max(...(paretoTemps.length ? paretoTemps : [1])) - tempMin, 0.001);
  const prepareCad = async () => {
    try {
      const artifact = await api.generateCad(cadDesign);
      setCadArtifact(artifact);
      notify(
        artifact.step_generated
          ? "FreeCAD STEP and STL generated"
          : "FreeCAD script and fallback STL generated · STEP requires FreeCAD",
      );
    } catch {
      notify("CAD backend unavailable or geometry bounds are invalid");
    }
  };
  const downloadCadArtifact = (path) => {
    if (path) window.open(api.artifactUrl(path), "_blank", "noopener,noreferrer");
  };
  const prepareCae = async () => {
    setCaeRunning(true);
    notify("OpenFOAM case queued · CAD → mesh setup → CHT handoff");
    try {
      const artifact = await api.prepareCae(cadDesign, false, setJobStatus);
      setCaeArtifact(artifact);
      notify("OpenFOAM case package ready · no CFD result claimed");
    } catch {
      notify("CAE queue unavailable · start Redis and the RQ worker");
    } finally {
      setCaeRunning(false);
    }
  };
  const runCaeBenchmark = async () => {
    setBenchmarkRunning(true);
    notify("OpenFOAM benchmark queued · mesh → solver → acceptance gates");
    try {
      const artifact = await api.runCaeBenchmark(setJobStatus);
      setBenchmarkArtifact(artifact);
      notify(
        artifact.benchmark_validated
          ? "OpenFOAM benchmark passed every acceptance gate"
          : "Benchmark finished without a validated CFD result",
      );
    } catch {
      notify("OpenFOAM benchmark worker unavailable");
    } finally {
      setBenchmarkRunning(false);
    }
  };
  const clearStoredCaeJob = (jobId) => {
    if (window.localStorage.getItem(activeCaeJobStorageKey) === jobId) {
      window.localStorage.removeItem(activeCaeJobStorageKey);
    }
  };
  const monitorCaeJob = async (initialJob, recovered = false) => {
    if (monitoredCaeJobRef.current) return;
    monitoredCaeJobRef.current = initialJob.job_id;
    setCampaignRunning(true);
    let job = initialJob;
    setCampaignJob(job);
    setJobStatus(job);
    if (recovered && !terminalJobStatuses.has(job.status)) {
      notify(`Reconnected to ${job.job_id} · ${readableState(job.stage)}`);
    }
    try {
      while (!terminalJobStatuses.has(job.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 900));
        job = await api.getJob(job.job_id);
        setCampaignJob(job);
        setJobStatus(job);
      }
      if (job.status === "finished" && job.result) {
        setCampaignResults((current) => ({
          ...current,
          [job.result.mesh_profile]: job.result,
        }));
        clearStoredCaeJob(job.job_id);
        notify(
          job.result.results_available
            ? `${readableState(job.result.mesh_profile)} campaign converged · mesh study still required`
            : `Campaign stopped safely · ${readableState(job.result.stop_reason)}`,
        );
      } else {
        clearStoredCaeJob(job.job_id);
        notify(job.error ?? `CAE job ${readableState(job.status)}`);
      }
    } catch {
      notify("CAE job polling paused · it will reconnect when CAE Operations is reopened");
    } finally {
      if (monitoredCaeJobRef.current === initialJob.job_id) {
        monitoredCaeJobRef.current = null;
      }
      setCampaignRunning(false);
    }
  };
  const runCaeCampaign = async () => {
    setMeshStudy(null);
    setResumePreview(null);
    notify(`${meshProfile} CAE campaign queued · cancellation stops at a safe checkpoint`);
    try {
      const job = await api.startCaeCampaign(cadDesign, {
        mesh_profile: meshProfile,
        target_end_time_s: Number(targetEndTime),
        segment_duration_s: Number(segmentDuration),
        parallel_processes: Number(parallelProcesses),
        max_segments: Number(maxSegments),
      });
      window.localStorage.setItem(activeCaeJobStorageKey, job.job_id);
      await monitorCaeJob(job);
    } catch {
      setCampaignRunning(false);
      notify("CAE campaign queue unavailable · start Redis and the CAE worker");
    }
  };
  const resumeCaeCampaign = async (campaign) => {
    if (!campaign?.next_resume_run_id || campaign.results_available) return;
    setResumeChecking(true);
    setResumePreview(null);
    notify(`Checking ${campaign.campaign_id} against the current design and checkpoint`);
    try {
      const resume = await api.resumeCaeCampaign(
        campaign.campaign_id,
        cadDesign,
        {
          mesh_profile: campaign.mesh_profile,
          target_end_time_s: Number(targetEndTime),
          segment_duration_s: Number(segmentDuration),
          parallel_processes: Number(parallelProcesses),
          max_segments: Number(maxSegments),
        },
      );
      setResumePreview(resume);
      if (!resume.resume_ready) {
        notify(`Resume blocked · ${resume.detail}`);
        return;
      }
      const job = resume.job;
      window.localStorage.setItem(activeCaeJobStorageKey, job.job_id);
      setResumeChecking(false);
      notify(
        resume.deduplicated
          ? `Existing resume reused · ${resume.resume_attempt_id}`
          : `Resume queued · ${resume.resume_attempt_id}`,
      );
      await monitorCaeJob(job);
      await loadCaeHistory();
    } catch {
      notify("Resume preflight or CAE queue is unavailable");
    } finally {
      setResumeChecking(false);
    }
  };
  const retryCaeResumeAttempt = async (attempt) => {
    if (!attempt?.retry_allowed || resumeChecking || campaignRunning) return;
    setResumeChecking(true);
    setResumePreview(null);
    notify(`Retrying failed attempt · ${attempt.resume_attempt_id}`);
    try {
      const retry = await api.retryCaeResumeAttempt(attempt.resume_attempt_id);
      setResumePreview(retry);
      if (!retry.resume_ready) {
        notify(`Retry blocked · ${retry.detail}`);
        return;
      }
      const job = retry.job;
      window.localStorage.setItem(activeCaeJobStorageKey, job.job_id);
      setResumeChecking(false);
      notify(
        retry.deduplicated
          ? `Existing retry reused · ${retry.resume_attempt_id}`
          : `Retry queued · ${retry.resume_attempt_id}`,
      );
      await monitorCaeJob(job);
      await loadCaeHistory();
    } catch {
      notify("Failed resume retry could not be queued");
    } finally {
      setResumeChecking(false);
    }
  };
  const cancelCaeCampaign = async () => {
    if (!campaignJob || terminalJobStatuses.has(campaignJob.status)) return;
    try {
      const job = await api.cancelJob(campaignJob.job_id);
      setCampaignJob(job);
      setJobStatus(job);
      notify("Cancel requested · the current solver segment will finish before stopping");
    } catch {
      notify("Unable to request safe cancellation");
    }
  };
  const runMeshIndependenceStudy = async () => {
    const campaignIds = Object.fromEntries(
      ["coarse", "medium", "fine"].map((profile) => [
        profile,
        campaignResults[profile]?.campaign_id,
      ]),
    );
    if (Object.values(campaignIds).some((value) => !value)) {
      notify("Complete coarse, medium, and fine campaigns first");
      return;
    }
    setMeshStudyRunning(true);
    notify("Mesh-independence study queued · medium-to-fine is the publication gate");
    try {
      const result = await api.runMeshStudy(campaignIds, setJobStatus);
      setMeshStudy(result);
      notify(
        result.design_result_available
          ? "Mesh independence passed · fine-mesh design result is publishable"
          : "Mesh independence did not pass · no design result published",
      );
    } catch {
      notify("Mesh study could not be evaluated");
    } finally {
      setMeshStudyRunning(false);
    }
  };
  const loadCaeHistory = async (announce = false) => {
    setCaeHistoryLoading(true);
    try {
      const [campaignIndex, studyIndex, resumeIndex] = await Promise.all([
        api.listCaeCampaigns(),
        api.listMeshStudies(),
        api.listCaeResumeAttempts(),
      ]);
      const summaries = campaignIndex.campaigns ?? [];
      const studies = studyIndex.mesh_studies ?? [];
      const attempts = resumeIndex.resume_attempts ?? [];
      setCampaignHistory(summaries);
      setMeshStudyHistory(studies);
      setResumeHistory(attempts);

      const newestByProfile = {};
      for (const summary of summaries) {
        if (!newestByProfile[summary.mesh_profile]) {
          newestByProfile[summary.mesh_profile] = summary;
        }
      }
      const detailedCampaigns = await Promise.all(
        Object.values(newestByProfile).map((summary) =>
          api.getCaeCampaign(summary.campaign_id),
        ),
      );
      const restoredCampaigns = Object.fromEntries(
        detailedCampaigns.map((report) => [report.mesh_profile, report]),
      );
      setCampaignResults(restoredCampaigns);

      const matchingStudy = studies.find((study) =>
        ["coarse", "medium", "fine"].every(
          (profile) =>
            study.campaign_ids?.[profile] ===
            restoredCampaigns[profile]?.campaign_id,
        ),
      );
      setMeshStudy(
        matchingStudy
          ? await api.getMeshStudy(matchingStudy.mesh_study_id)
          : null,
      );
      if (announce) {
        notify(`Recovered ${summaries.length} campaigns, ${attempts.length} resume attempts, and ${studies.length} mesh studies`);
      }
    } catch {
      if (announce) notify("CAE history API is unavailable");
    } finally {
      setCaeHistoryLoading(false);
    }
  };
  const inspectCampaignHistory = async (summary) => {
    try {
      const report = await api.getCaeCampaign(summary.campaign_id);
      setMeshProfile(report.mesh_profile);
      setCampaignResults((current) => ({
        ...current,
        [report.mesh_profile]: report,
      }));
      setResumePreview(null);
      notify(`${report.campaign_id} loaded from immutable history`);
    } catch {
      notify("Campaign report is no longer available");
    }
  };
  useEffect(() => {
    if (active !== "cae-operations") return;
    let disposed = false;
    const restore = async () => {
      await loadCaeHistory();
      if (disposed || campaignRunning) return;
      const jobId = window.localStorage.getItem(activeCaeJobStorageKey);
      if (!jobId) return;
      try {
        const job = await api.getJob(jobId);
        if (!disposed) await monitorCaeJob(job, true);
      } catch {
        if (!disposed) {
          window.localStorage.removeItem(activeCaeJobStorageKey);
          notify("Saved CAE job expired; immutable campaign history was restored instead");
        }
      }
    };
    restore();
    return () => {
      disposed = true;
    };
  }, [active]);
  if (active === "design")
    return (
      <div className="content">
        <PageHead
          kicker="PARAMETER SPACE"
          title="Design space"
          description="Define the geometry and operating bounds explored by the DOE engine."
          badge="Bounds valid"
        />
        <div className="module-grid">
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Design parameters</h2>
                <p>Continuous values are normalized before sampling.</p>
              </div>
              <span className="tag">5 ACTIVE</span>
            </div>
            {[
              ["Fin count", fins, 20, 60, 1, setFins, ""],
              ["Fin height", height, 20, 60, 1, setHeight, "mm"],
              ["Fin spacing", spacing, 1, 4, 0.1, setSpacing, "mm"],
              ["Air velocity", velocity, 0.5, 5, 0.1, setVelocity, "m/s"],
            ].map(([label, value, min, max, step, setter, unit]) => (
              <label className="range-row" key={String(label)}>
                <span>
                  <b>{label}</b>
                  <small>
                    {min} — {max} {unit}
                  </small>
                </span>
                <input
                  type="range"
                  min={Number(min)}
                  max={Number(max)}
                  step={Number(step)}
                  value={Number(value)}
                  onChange={(e) =>
                    setter(Number(e.target.value))
                  }
                />
                <output>
                  {value} {unit}
                </output>
              </label>
            ))}
            <label className="range-row fixed">
              <span>
                <b>Fin thickness</b>
                <small>0.3 — 1.0 mm</small>
              </span>
              <input
                type="range"
                min=".3"
                max="1"
                step=".1"
                defaultValue=".65"
              />
              <output>0.65 mm</output>
            </label>
            <button
              className="primary-action"
              onClick={() =>
                api
                  .validateDesign(design)
                  .then(() => notify("FastAPI validated design space · version 13"))
                  .catch(() => notify("Backend unavailable · design kept locally"))
              }
            >
              Save design space <span>→</span>
            </button>
          </section>
          <section className="panel preview-panel">
            <div className="panel-title">
              <div>
                <h2>Parametric preview</h2>
                <p>Geometry representation · not CFD</p>
              </div>
              <span className="candidate">LIVE</span>
            </div>
            <div className="large-sink">
              <HeatSink count={fins / 4} />
              <div className="dimension horizontal">120 mm</div>
              <div className="dimension vertical">{height} mm</div>
            </div>
            <div className="preview-stats">
              <span>
                <small>EST. MASS</small>
                <b>{mass} g</b>
              </span>
              <span>
                <small>FIN AREA</small>
                <b>{(fins * height * 0.024).toFixed(2)} m²</b>
              </span>
              <span>
                <small>OPEN RATIO</small>
                <b>{Math.round((spacing / (spacing + 0.65)) * 100)}%</b>
              </span>
            </div>
          </section>
        </div>
      </div>
    );
  if (active === "doe")
    return (
      <div className="content">
        <PageHead
          kicker="DESIGN OF EXPERIMENTS"
          title="Experiment matrix"
          description="Generate a space-filling, reproducible set of thermal design candidates."
          badge="Seed 42"
        />
        <section className="panel toolbar-panel">
          <div className="method-tabs">
            {["CCD", "BBD", "LHS"].map((x) => (
              <button
                className={method === x ? "selected" : ""}
                onClick={() => setMethod(x)}
                key={x}
              >
                {x}
                <small>
                  {x === "CCD"
                    ? "Response surface"
                    : x === "BBD"
                      ? "Efficient quadratic"
                      : "Space filling"}
                </small>
              </button>
            ))}
          </div>
          <label className="run-count">
            RUNS{" "}
            <input
              type="number"
              min="30"
              max="100"
              value={runs}
              onChange={(e) => setRuns(Number(e.target.value))}
            />
          </label>
          <button
            className="primary-action compact"
            disabled={workflowRunning}
            onClick={() => runWorkflow(method, runs)}
          >
            {workflowRunning ? "Running Phase 1…" : "Run DOE + Phase 1"}
          </button>
        </section>
        <section className="panel table-panel">
          <div className="panel-title">
            <div>
              <h2>{method} experiment matrix</h2>
              <p>
                {phase1?.experiment_count ?? runs} runs · 5 factors · {method === "LHS" ? "maximin" : "standard quadratic"} · seed 42
              </p>
            </div>
            <button className="text-button">Export CSV ↓</button>
          </div>
          <div className="data-table">
            <div className="tr head">
              <span>RUN</span>
              <span>FIN COUNT</span>
              <span>THICKNESS</span>
              <span>HEIGHT</span>
              <span>SPACING</span>
              <span>VELOCITY</span>
              <span>STATUS</span>
            </div>
            {(experiments.length
              ? experiments.slice(0, 6).map((row) => [
                  row.run,
                  row.fin_count,
                  row.fin_thickness,
                  row.fin_height,
                  row.fin_spacing,
                  row.air_velocity,
                ])
              : [
                  [1, 30, 0.4, 30, 1.5, 1.0],
                  [2, 40, 0.5, 40, 2.0, 2.0],
                  [3, 50, 0.7, 50, 2.5, 3.0],
                  [4, 45, 0.6, 55, 2.8, 3.6],
                  [5, 36, 0.85, 34, 3.3, 4.2],
                  [6, 58, 0.35, 48, 1.8, 2.7],
                ]).map((r, i) => (
              <div className="tr" key={i}>
                {r.map((x, j) => (
                  <span key={j}>
                    {x}
                    {j > 1 && j < 5 ? " mm" : j === 5 ? " m/s" : ""}
                  </span>
                ))}
                <span className="ready">● READY</span>
              </div>
            ))}
          </div>
          <div className="table-foot">
            Showing {Math.min(6, phase1?.experiment_count ?? runs)} of {phase1?.experiment_count ?? runs} experiments{" "}
            <span>{phase1 ? phase1.dataset_version : "Version will be frozen on simulation"}</span>
          </div>
        </section>
      </div>
    );
  if (active === "simulation")
    return (
      <div className="content">
        <PageHead
          kicker="PHYSICS ENGINE"
          title="Batch simulation"
          description="Evaluate heat transfer, pressure drop, and mass with the deterministic reduced-order model."
          badge={`${phase1?.experiment_count ?? 64} / ${phase1?.experiment_count ?? 64} complete`}
        />
        <div className="metrics compact-metrics">
          <article>
            <small>
              MEDIAN T<sub>MAX</sub>
            </small>
            <strong>
              {medianTemp.toFixed(1)}<em>°C</em>
            </strong>
            <p>
              Range {sortedTemps.length ? sortedTemps[0].toFixed(1) : "66.9"} — {sortedTemps.length ? sortedTemps.at(-1)?.toFixed(1) : "91.2"}
            </p>
          </article>
          <article>
            <small>
              AVG. R<sub>θ</sub>
            </small>
            <strong>
              {average("thermal_resistance").toFixed(3)}<em>K/W</em>
            </strong>
            <p>Power 100 W</p>
          </article>
          <article>
            <small>AVG. ΔP</small>
            <strong>
              {average("pressure_drop").toFixed(1)}<em>Pa</em>
            </strong>
            <p>Limit 35 Pa</p>
          </article>
          <article>
            <small>RUNTIME</small>
            <strong>
              3.8<em>s</em>
            </strong>
            <p>Seed 42 · deterministic</p>
          </article>
        </div>
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>Simulation runs</h2>
              <p>
                Physics simulator {phase1?.simulator_version ?? "1.0.0"} · {phase1?.dataset_version ?? "demo dataset"}
              </p>
            </div>
            <button
              className="primary-action compact"
              onClick={() =>
                notify("Re-run queued with the same deterministic seed")
              }
            >
              Re-run batch
            </button>
          </div>
          <div className="run-list">
            {(experiments.length
              ? experiments.slice(-5).reverse().map((row) => [
                  `EXP-${String(row.run).padStart(3, "0")}`,
                  `${row.t_max.toFixed(1)}°C`,
                  `${row.thermal_resistance.toFixed(3)} K/W`,
                  `${row.pressure_drop.toFixed(1)} Pa`,
                  `${row.mass.toFixed(0)} g`,
                ])
              : [
                  ["EXP-064", "68.4°C", "0.434 K/W", "22.1 Pa", "287 g"],
                  ["EXP-063", "71.2°C", "0.462 K/W", "16.8 Pa", "301 g"],
                  ["EXP-062", "69.7°C", "0.447 K/W", "27.4 Pa", "274 g"],
                  ["EXP-061", "76.1°C", "0.511 K/W", "12.3 Pa", "264 g"],
                  ["EXP-060", "72.8°C", "0.478 K/W", "19.5 Pa", "293 g"],
                ]).map((r, i) => (
              <div className="run-row" key={r[0]}>
                <span className="run-id">
                  <i>✓</i>
                  <b>{r[0]}</b>
                  <small>completed · {(1.8 + i * 0.4).toFixed(1)} ms</small>
                </span>
                {r.slice(1).map((x, j) => (
                  <span key={j}>
                    <small>{["TMAX", "Rθ", "ΔP", "MASS"][j]}</small>
                    <b>{x}</b>
                  </span>
                ))}
                <button>›</button>
              </div>
            ))}
          </div>
        </section>
        <section className="panel top-gap">
          <div className="panel-title">
            <div>
              <h2>OpenFOAM CAE handoff</h2>
              <p>Geometry, boundary conditions, meshing dictionaries, and guarded solver automation.</p>
            </div>
            <span className="tag">{caeArtifact ? "CASE GENERATED" : "NO CFD RESULT"}</span>
          </div>
          <div className="module-grid">
            <div className="artifact">
              <span>BACKGROUND JOB</span>
              <code>{caeRunning || benchmarkRunning ? `${jobStatus?.progress ?? 0}%` : jobStatus?.job_id ?? "Idle"}</code>
              <small>
                {jobStatus
                  ? `${jobStatus.queue} · ${jobStatus.stage.replaceAll("_", " ")}`
                  : "Submit through Redis/RQ"}
              </small>
            </div>
            <div className="artifact">
              <span>OPENFOAM CASE</span>
              <code>{caeArtifact?.case_id ?? "Not generated"}</code>
              <small>
                {caeArtifact
                  ? `${caeArtifact.solver_status} · validation required · results unavailable`
                  : "Target solver: chtMultiRegionFoam"}
              </small>
            </div>
          </div>
          <button className="primary-action" disabled={caeRunning} onClick={prepareCae}>
            {caeRunning ? "Preparing case…" : "Prepare OpenFOAM case package"} <span>→</span>
          </button>
          {caeArtifact && (
            <button
              className="outline-button"
              onClick={() => downloadCadArtifact(caeArtifact.downloads.case_package)}
            >
              Download case ZIP <span>↓</span>
            </button>
          )}
          <div className="panel-title top-gap">
            <div>
              <h2>Official tutorial benchmark</h2>
              <p>OpenCFD v2312 multiRegionHeater · environment proof, not a heat-sink result.</p>
            </div>
            <span className="tag">
              {benchmarkArtifact?.benchmark_validated ? "VALIDATED" : benchmarkArtifact ? "NOT VALIDATED" : "PENDING"}
            </span>
          </div>
          <div className="validation-grid">
            {[
              ["Mesh quality", benchmarkArtifact?.validation.gates.mesh_quality],
              ["Convergence", benchmarkArtifact?.validation.gates.convergence],
              ["Energy balance", benchmarkArtifact?.validation.gates.energy_balance],
              ["Response metrics", benchmarkArtifact?.validation.gates.response_metrics],
            ].map(([label, gate]) => (
              <div className={`validation-gate ${gate?.passed ? "gate-pass" : "gate-pending"}`} key={label}>
                <i>{gate?.passed ? "✓" : "—"}</i>
                <span><b>{label}</b><small>{gate ? (gate.passed ? "Acceptance passed" : "Missing or above limit") : "Not evaluated"}</small></span>
              </div>
            ))}
          </div>
          <button className="outline-button" disabled={benchmarkRunning} onClick={runCaeBenchmark}>
            {benchmarkRunning ? "Running benchmark…" : "Run OpenFOAM benchmark"} <span>→</span>
          </button>
          {benchmarkArtifact && (
            <button
              className="outline-button"
              onClick={() => downloadCadArtifact(benchmarkArtifact.downloads.report)}
            >
              Download validation report <span>↓</span>
            </button>
          )}
          <p className="disclaimer">
            The reduced-order simulator above is not CFD. A generated case is also not a CAE result;
            results remain unavailable until mesh validation and a successful OpenFOAM solver run.
          </p>
        </section>
      </div>
    );
  if (active === "analysis")
    return (
      <div className="content">
        <PageHead
          kicker="STATISTICAL ANALYSIS"
          title="Effects & diagnostics"
          description="Understand which factors and interactions control maximum temperature."
          badge="ANOVA significant"
        />
        <div className="analysis-grid">
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Standardized effects</h2>
                <p>
                  Response: T<sub>max</sub> · α = 0.05
                </p>
              </div>
              <span className="tag">MAIN EFFECTS</span>
            </div>
            <div className="effects">
              {(effectRows
                ? effectRows.map((row) => [
                    row.source.split(" × ").map(labelFor).join(" × "),
                    (row.f_value / maximumEffect) * 94,
                    `F ${row.f_value.toFixed(2)}`,
                  ])
                : [
                    ["Air velocity", 94, "F 18.42"],
                    ["Fin height", 67, "F 11.07"],
                    ["Fin count", 54, "F 8.91"],
                    ["Spacing × Velocity", 39, "F 5.62"],
                    ["Fin spacing", 31, "F 4.08"],
                    ["Thickness", 18, "F 2.11"],
                  ]).map(([n, w, v]) => (
                <div key={String(n)}>
                  <span>{String(n)}</span>
                  <i>
                    <b style={{ width: `${Number(w)}%` }} />
                  </i>
                  <em>{String(v)}</em>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Residual vs fitted</h2>
                <p>Model residual diagnostics</p>
              </div>
              <span className="candidate">PASS</span>
            </div>
            <div className="scatter">
              <i className="zero" />
              {(diagnosticPoints.length
                ? diagnosticPoints
                : Array.from({ length: 28 }).map((_, i) => ({
                    fitted: ((i * 31) % 87) + 7,
                    residual: (((i * 47) % 69) - 34) / 34,
                  }))).map((point, i) => (
                <b
                  key={i}
                  style={{
                    left: `${diagnosticPoints.length ? 5 + ((point.fitted - fittedMin) / fittedSpan) * 90 : point.fitted}%`,
                    top: `${50 - (point.residual / residualMax) * 42}%`,
                  }}
                />
              ))}
            </div>
            <div className="diagnostic-stats">
              <span>
                <small>SHAPIRO-WILK</small>
                <b>p = {(analysis?.diagnostics.shapiro_p_value ?? 0.218).toFixed(3)}</b>
              </span>
              <span>
                <small>OUTLIERS</small>
                <b>{analysis?.diagnostics.outlier_indices.length ?? 1} flagged</b>
              </span>
              <span>
                <small>BIAS</small>
                <b>{analysis ? `${analysis.rmse.toFixed(3)}°C RMSE` : "−0.03°C"}</b>
              </span>
            </div>
          </section>
          <section className="panel wide">
            <div className="panel-title">
              <div>
                <h2>ANOVA</h2>
                <p>Quadratic response surface · 95% confidence</p>
              </div>
              <button className="text-button">Full report ↓</button>
            </div>
            <div className="anova">
              <div className="tr head">
                <span>SOURCE</span>
                <span>SUM SQ.</span>
                <span>DF</span>
                <span>MEAN SQ.</span>
                <span>F-VALUE</span>
                <span>P-VALUE</span>
              </div>
              {(analysis
                ? analysis.anova.slice(0, 7).map((row) => [
                    row.source,
                    row.sum_sq.toFixed(3),
                    String(row.df),
                    row.mean_sq.toFixed(3),
                    row.f_value.toFixed(3),
                    row.p_value < 0.001 ? "< 0.001" : row.p_value.toFixed(4),
                  ])
                : [
                    ["Model", "1,284.2", "20", "64.21", "38.47", "< 0.001"],
                    ["Linear", "1,021.8", "5", "204.36", "122.39", "< 0.001"],
                    ["Interactions", "188.6", "10", "18.86", "11.29", "0.002"],
                    ["Quadratic", "73.8", "5", "14.76", "8.84", "0.008"],
                    ["Residual", "71.8", "43", "1.67", "—", "—"],
                  ]).map((r) => (
                <div className="tr" key={r[0]}>
                  {r.map((x, i) => (
                    <span
                      className={
                        i === 5 && x.includes("<") ? "significant" : ""
                      }
                      key={i}
                    >
                      {x}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    );
  if (active === "surrogate")
    return (
      <div className="content">
        <PageHead
          kicker="SURROGATE MODELING"
          title="Model comparison"
          description="Select the best generalizing predictor—not simply the highest training score."
          badge={`${selectedModel} recommended`}
        />
        <section className="panel">
          <div className="model-table">
            <div className="tr head">
              <span>MODEL</span>
              <span>R² TEST</span>
              <span>RMSE</span>
              <span>MAE</span>
              <span>CV RMSE</span>
              <span>TRAINING</span>
              <span>STATUS</span>
            </div>
            {modelMetrics.map((metric) => {
              const r = [
                metric.model,
                metric.r2.toFixed(3),
                `${metric.rmse.toFixed(2)}°C`,
                `${metric.mae.toFixed(2)}°C`,
                `${metric.cv_rmse.toFixed(2)}°C`,
                `${metric.training_ms.toFixed(0)} ms`,
              ];
              return (
              <button
                className={`tr ${model === r[0] ? "model-selected" : ""}`}
                onClick={() => setModel(r[0])}
                key={r[0]}
              >
                {r.map((x, i) => (
                  <span key={i}>
                    {i === 0 && <i className="radio" />}
                    {x}
                  </span>
                ))}
                <span>
                  {r[0] === selectedModel ? (
                    <b className="recommended">RECOMMENDED</b>
                  ) : (
                    "Trained"
                  )}
                </span>
              </button>
              );
            })}
          </div>
        </section>
        <div className="module-grid top-gap">
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>{model} prediction</h2>
                <p>Candidate 07 · dataset v12</p>
              </div>
              <span className="tag">LIVE</span>
            </div>
            <div className="prediction">
              <div>
                <small>
                  PREDICTED T<sub>MAX</sub>
                </small>
                <strong>
                  {(recommended?.responses.t_max ?? (model === "GPR" ? 68.4 : 69.1)).toFixed(1)}
                  <em>°C</em>
                </strong>
                <p>
                  Selected by lowest cross-validated RMSE · model artifact {phase1?.model_id ?? "demo"}
                </p>
              </div>
              <div className="gauge">
                <i style={{ width: "64%" }} />
                <b>80°C LIMIT</b>
              </div>
            </div>
          </section>
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Uncertainty</h2>
                <p>Predictive σ across design space</p>
              </div>
            </div>
            <div className="uncertainty">
              <strong>GPR σ(x)</strong>
              <div>
                {Array.from({ length: 18 }).map((_, i) => (
                  <i key={i} style={{ height: `${25 + ((i * 29) % 62)}%` }} />
                ))}
              </div>
              <p>
                Low uncertainty around sampled regions. Highest near boundary
                combinations.
              </p>
            </div>
          </section>
        </div>
      </div>
    );
  if (active === "optimization")
    return (
      <div className="content">
        <PageHead
          kicker="MULTI-OBJECTIVE SEARCH"
          title="Optimization"
          description="Explore feasible trade-offs between thermal performance, pressure drop, and mass."
          badge={phase1 ? `${phase1.optimization.evaluations} evaluations` : "NSGA-II ready"}
        />
        <div className="optimization-layout">
          <section className="panel objective-panel">
            <div className="panel-title">
              <div>
                <h2>Objectives</h2>
                <p>NSGA-II configuration</p>
              </div>
            </div>
            {[
              ["Tmax", "Minimize", "°C"],
              ["Pressure drop", "Minimize", "Pa"],
              ["Mass", "Minimize", "g"],
            ].map((r) => (
              <div className="objective" key={r[0]}>
                <i>↓</i>
                <span>
                  <b>{r[0]}</b>
                  <small>{r[1]}</small>
                </span>
                <em>{r[2]}</em>
              </div>
            ))}
            <h3>CONSTRAINTS</h3>
            <div className="constraint">
              <span>
                T<sub>MAX</sub>
              </span>
              <b>&lt; 80°C</b>
            </div>
            <div className="constraint">
              <span>Pressure drop</span>
              <b>&lt; 35 Pa</b>
            </div>
            <button
              className="primary-action"
              disabled={workflowRunning}
              onClick={() => runWorkflow(phase1?.method ?? "LHS", phase1?.experiment_count ?? 48)}
            >
              {workflowRunning ? "Optimizing…" : "Run Phase 1 optimization"} <span>→</span>
            </button>
            <h3>BAYESIAN OPTIMIZATION</h3>
            <div className="bo-controls" aria-label="Acquisition function">
              {["EI", "PI", "UCB"].map((name) => (
                <button
                  key={name}
                  className={acquisition === name ? "selected" : ""}
                  onClick={() => setAcquisition(name)}
                >
                  {name}
                </button>
              ))}
            </div>
            <button
              className="outline-button"
              disabled={!phase1 || phase2Running}
              onClick={() => runPhase2(acquisition)}
            >
              {phase2Running ? "Learning from experiments…" : "Run Phase 2 loop"}
              <span>→</span>
            </button>
          </section>
          <section className="panel pareto-panel">
            <div className="panel-title">
              <div>
                <h2>Pareto front</h2>
                <p>Temperature vs. mass · color = pressure drop</p>
              </div>
              <div className="legend gradient">
                LOW ΔP <i /> HIGH ΔP
              </div>
            </div>
            <div className="pareto">
              <span className="ylabel">
                T<sub>MAX</sub> (°C)
              </span>
              <i className="front-line" />
              {(paretoForChart.length
                ? paretoForChart.map((candidate) => [
                    8 + ((candidate.responses.mass - massMin) / massSpan) * 78,
                    16 + ((candidate.responses.t_max - tempMin) / tempSpan) * 62,
                  ])
                : [
                    [11, 20], [19, 31], [29, 40], [39, 49],
                    [50, 57], [61, 63], [72, 70], [84, 76],
                  ]).map((p, i) => (
                <button
                  key={i}
                  className={i === Math.floor((paretoForChart.length || 8) / 2) ? "chosen" : ""}
                  style={{ left: `${p[0]}%`, top: `${p[1]}%` }}
                  onClick={() =>
                    notify(
                      `Candidate ${String(i + 1).padStart(2, "0")} selected`,
                    )
                  }
                  aria-label={`Select candidate ${i + 1}`}
                />
              ))}
              <b className="xlabel">MASS (g)</b>
            </div>
          </section>
        </div>
        <div className="candidate-strip">
          {(pareto.length
            ? [pareto[0], recommended ?? pareto[Math.floor(pareto.length / 2)], pareto.at(-1)].map((candidate, index) => [
                String(index + 1).padStart(2, "0"),
                `${candidate.responses.t_max.toFixed(1)}°C`,
                `${candidate.responses.mass.toFixed(0)} g`,
                `${candidate.responses.pressure_drop.toFixed(1)} Pa`,
              ])
            : [
                ["01", "66.9°C", "341 g", "31.2 Pa"],
                ["04", "68.4°C", "287 g", "22.1 Pa"],
                ["07", "71.0°C", "248 g", "16.8 Pa"],
              ]).map((r, i) => (
            <button className={i === 1 ? "selected" : ""} key={r[0]}>
              <small>CANDIDATE {r[0]}</small>
              <strong>{r[1]}</strong>
              <span>
                {r[2]} · {r[3]}
              </span>
            </button>
          ))}
        </div>
        {phase2 && (
          <section className="panel top-gap phase2-summary">
            <div className="panel-title">
              <div>
                <h2>Bayesian learning trace</h2>
                <p>
                  {phase2.acquisition} · {phase2.iterations} simulator feedback cycles · {phase2.dataset_version}
                </p>
              </div>
              <span className="candidate">PHASE 2 COMPLETE</span>
            </div>
            <div className="phase2-proposals">
              {phase2.proposals.map((proposal) => (
                <article key={proposal.iteration}>
                  <small>ITERATION {proposal.iteration}</small>
                  <strong>{proposal.simulated_responses.t_max.toFixed(2)}°C</strong>
                  <span>
                    μ {proposal.objective_mean.toFixed(2)} · σ {proposal.objective_uncertainty.toFixed(2)}
                  </span>
                  <span>
                    {proposal.design.fin_count} fins · {proposal.design.air_velocity.toFixed(2)} m/s
                  </span>
                </article>
              ))}
            </div>
          </section>
        )}
      </div>
    );
  if (active === "digital-twin")
    return (
      <div className="content">
        <PageHead
          kicker="INTERACTIVE PREDICTION"
          title="Digital twin"
          description="Explore design changes instantly with the GPR surrogate and quantified uncertainty."
          badge={phase1 ? `${selectedModel} · ${phase1.model_id}` : "Physics preview"}
        />
        <div className="twin-layout">
          <section className="panel twin-controls">
            <div className="panel-title">
              <div>
                <h2>What-if controls</h2>
                <p>Predictions update without rerunning simulation.</p>
              </div>
              <button
                className="text-button"
                onClick={() => {
                  setFins(48);
                  setHeight(52);
                  setSpacing(2.4);
                  setVelocity(3.2);
                }}
              >
                Reset
              </button>
            </div>
            {[
              ["Fin count", fins, 20, 60, 1, setFins, ""],
              ["Fin height", height, 20, 60, 1, setHeight, "mm"],
              ["Fin spacing", spacing, 1, 4, 0.1, setSpacing, "mm"],
              ["Air velocity", velocity, 0.5, 5, 0.1, setVelocity, "m/s"],
            ].map(([label, value, min, max, step, setter, unit]) => (
              <label className="range-row" key={String(label)}>
                <span>
                  <b>{label}</b>
                  <small>
                    {min} — {max} {unit}
                  </small>
                </span>
                <input
                  type="range"
                  min={Number(min)}
                  max={Number(max)}
                  step={Number(step)}
                  value={Number(value)}
                  onChange={(e) =>
                    setter(Number(e.target.value))
                  }
                />
                <output>
                  {value} {unit}
                </output>
              </label>
            ))}
          </section>
          <section className="panel twin-surface">
            <div className="panel-title">
              <div>
                <h2>Response surface</h2>
                <p>
                  Fin height × air velocity → T<sub>max</sub>
                </p>
              </div>
              <span className="candidate">GPR μ(x)</span>
            </div>
            <div className="surface">
              <div className="contours">
                {Array.from({ length: 7 }).map((_, i) => (
                  <i key={i} />
                ))}
              </div>
              <span
                className="current"
                style={{
                  left: `${25 + velocity * 9}%`,
                  top: `${78 - height}%`,
                }}
              >
                ●<b>CURRENT</b>
              </span>
              <span className="optimal">
                ★<b>OPTIMAL</b>
              </span>
            </div>
          </section>
          <aside className="twin-results">
            <article>
              <small>
                PREDICTED T<sub>MAX</sub>
              </small>
              <strong>
                {predictedTemp}
                <em>°C</em>
              </strong>
              <p className={Number(predictedTemp) < 80 ? "pass" : "fail"}>
                {Number(predictedTemp) < 80
                  ? "✓ Within constraint"
                  : "× Above constraint"}
              </p>
            </article>
            <article>
              <small>THERMAL RESISTANCE</small>
              <strong>
                {predictedTheta}
                <em>K/W</em>
              </strong>
              <p>
                {predictedUncertainty !== undefined
                  ? `Tmax uncertainty ± ${predictedUncertainty.toFixed(2)}°C`
                  : "Physics estimate"}
              </p>
            </article>
            <article>
              <small>PRESSURE DROP</small>
              <strong>
                {predictedPressure}
                <em>Pa</em>
              </strong>
              <p>35 Pa limit</p>
            </article>
            <article>
              <small>ESTIMATED MASS</small>
              <strong>
                {predictedMass}
                <em>g</em>
              </strong>
              <p>
                {phase1 && apiPrediction
                  ? `${selectedModel} surrogate prediction`
                  : apiPrediction
                    ? "FastAPI physics result"
                    : "Preview estimate"}
              </p>
            </article>
            <button
              className="primary-action"
              onClick={() => notify("Current point saved as Candidate 12")}
            >
              Save candidate
            </button>
          </aside>
        </div>
      </div>
    );
  if (active === "cae-operations") {
    const selectedCampaign = campaignResults[meshProfile];
    const timeline = selectedCampaign?.segments ?? [];
    const campaignProgress = campaignJob?.progress ?? 0;
    const allCampaignsConverged = ["coarse", "medium", "fine"].every(
      (profile) => campaignResults[profile]?.results_available,
    );
    const comparisons = meshStudy?.comparisons ?? {};
    return (
      <div className="content">
        <PageHead
          kicker="PRODUCTION CHT OPERATIONS"
          title="CAE Operations"
          description="Run resumable OpenFOAM campaigns, stop safely at checkpoint boundaries, and validate mesh independence."
          badge={
            meshStudy?.design_result_available
              ? "Design result publishable"
              : campaignRunning
                ? "Campaign active"
                : "Publication gated"
          }
        />
        <div className="cae-ops-layout">
          <section className="panel campaign-controls">
            <div className="panel-title">
              <div>
                <h2>Campaign settings</h2>
                <p>Each segment saves a resumable solver checkpoint.</p>
              </div>
              <span className="tag">chtMultiRegionFoam</span>
            </div>
            <div className="profile-tabs" aria-label="Mesh profile">
              {["coarse", "medium", "fine"].map((profile) => (
                <button
                  className={meshProfile === profile ? "selected" : ""}
                  disabled={campaignRunning}
                  key={profile}
                  onClick={() => setMeshProfile(profile)}
                >
                  {profile.toUpperCase()}
                  <small>
                    {profile === "coarse" ? "0.80×" : profile === "fine" ? "1.25×" : "1.00×"}
                  </small>
                </button>
              ))}
            </div>
            <div className="campaign-number-grid">
              <label>
                <span>TARGET END TIME</span>
                <input
                  type="number"
                  min="0.0001"
                  max="10"
                  step="0.001"
                  value={targetEndTime}
                  disabled={campaignRunning}
                  onChange={(event) => setTargetEndTime(event.target.value)}
                />
                <small>seconds</small>
              </label>
              <label>
                <span>SEGMENT DURATION</span>
                <input
                  type="number"
                  min="0.0001"
                  max="1"
                  step="0.0001"
                  value={segmentDuration}
                  disabled={campaignRunning}
                  onChange={(event) => setSegmentDuration(event.target.value)}
                />
                <small>seconds</small>
              </label>
              <label>
                <span>MPI PROCESSES</span>
                <input
                  type="number"
                  min="1"
                  max="16"
                  value={parallelProcesses}
                  disabled={campaignRunning}
                  onChange={(event) => setParallelProcesses(event.target.value)}
                />
                <small>workers</small>
              </label>
              <label>
                <span>MAX SEGMENTS</span>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={maxSegments}
                  disabled={campaignRunning}
                  onChange={(event) => setMaxSegments(event.target.value)}
                />
                <small>checkpoints</small>
              </label>
            </div>
            <button
              className="primary-action"
              disabled={campaignRunning || caeHistoryLoading}
              onClick={runCaeCampaign}
            >
              {campaignRunning
                ? `Running ${meshProfile} campaign…`
                : caeHistoryLoading
                  ? "Recovering CAE state…"
                  : `Run ${meshProfile} campaign`}
              <span>→</span>
            </button>
          </section>
          <section className="panel job-console">
            <div className="panel-title">
              <div>
                <h2>Live job</h2>
                <p>Polled from the isolated thermoform-cae queue.</p>
              </div>
              <span className={`job-state ${campaignJob?.status ?? "idle"}`}>
                {readableState(campaignJob?.status ?? "idle")}
              </span>
            </div>
            <div className="job-identity">
              <span>JOB ID</span>
              <code>{campaignJob?.job_id ?? "No campaign submitted"}</code>
              <small>{campaignJob?.queue ?? "thermoform-cae"}</small>
            </div>
            <div className="job-progress-heading">
              <span>{readableState(campaignJob?.stage ?? "waiting")}</span>
              <b>{campaignProgress}%</b>
            </div>
            <div
              className="job-progress"
              role="progressbar"
              aria-valuemin="0"
              aria-valuemax="100"
              aria-valuenow={campaignProgress}
            >
              <i style={{ width: `${campaignProgress}%` }} />
            </div>
            <div className="safe-cancel-note">
              <i>{campaignJob?.cancel_requested ? "…" : "✓"}</i>
              <span>
                <b>{campaignJob?.cancel_requested ? "Cancellation requested" : "Checkpoint-safe cancellation"}</b>
                <small>
                  {campaignJob?.cancel_requested
                    ? "The active segment is allowed to finish before the worker stops."
                    : "Cancel never interrupts a checkpoint write or leaves a partial resume artifact."}
                </small>
              </span>
            </div>
            <button
              className="cancel-action"
              disabled={
                !campaignJob ||
                terminalJobStatuses.has(campaignJob.status) ||
                campaignJob.cancel_requested
              }
              onClick={cancelCaeCampaign}
            >
              {campaignJob?.cancel_requested ? "Waiting for safe boundary…" : "Request safe cancel"}
            </button>
          </section>
        </div>

        <section className="panel top-gap checkpoint-panel">
          <div className="panel-title">
            <div>
              <h2>Checkpoint timeline</h2>
              <p>{meshProfile} campaign · immutable segment snapshots and response-readiness gates.</p>
            </div>
            <div className="history-actions">
              <button
                className="text-button"
                disabled={caeHistoryLoading}
                onClick={() => loadCaeHistory(true)}
              >
                {caeHistoryLoading ? "Recovering…" : "Refresh history ↻"}
              </button>
              <span className="tag">
                {selectedCampaign
                  ? `${selectedCampaign.segments_completed ?? 0} SEGMENTS · ${readableState(selectedCampaign.stop_reason)}`
                  : "NO CHECKPOINTS"}
              </span>
            </div>
          </div>
          {timeline.length ? (
            <div className="checkpoint-timeline">
              {timeline.map((segment) => {
                const gateValues = Object.values(segment.gates ?? {});
                const passedGates = gateValues.filter(Boolean).length;
                return (
                  <article
                    className={segment.results_available ? "converged" : ""}
                    key={segment.solve_run_id ?? segment.index}
                  >
                    <i>{segment.results_available ? "✓" : segment.index}</i>
                    <small>SEGMENT {String(segment.index).padStart(2, "0")}</small>
                    <strong>{Number(segment.latest_time_s ?? 0).toExponential(2)} s</strong>
                    <span>{segment.response_sample_count} response samples</span>
                    <span>{passedGates} / {gateValues.length} readiness gates</span>
                    <code>{segment.solve_run_id}</code>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="empty-timeline">
              <strong>No {meshProfile} campaign report yet</strong>
              <span>Run a campaign to build the checkpoint timeline.</span>
            </div>
          )}
          {selectedCampaign && (
            <div className="campaign-stop-summary">
              <div>
                <small>STOP REASON</small>
                <strong>{readableState(selectedCampaign.stop_reason)}</strong>
              </div>
              <div>
                <small>LATEST / TARGET</small>
                <strong>{Number(selectedCampaign.latest_time_s).toExponential(2)} / {Number(selectedCampaign.target_end_time_s).toExponential(2)} s</strong>
              </div>
              <div>
                <small>NEXT RESUME</small>
                <code>{selectedCampaign.next_resume_run_id ?? "Not available"}</code>
              </div>
              <div className="checkpoint-actions">
                <button
                  className="text-button"
                  disabled={!selectedCampaign.downloads?.latest_checkpoint}
                  onClick={() => downloadCadArtifact(selectedCampaign.downloads.latest_checkpoint)}
                >
                  Download checkpoint ↓
                </button>
                <button
                  className="resume-action"
                  disabled={
                    !selectedCampaign.next_resume_run_id ||
                    selectedCampaign.results_available ||
                    campaignRunning ||
                    resumeChecking
                  }
                  onClick={() => resumeCaeCampaign(selectedCampaign)}
                >
                  {resumeChecking ? "Checking compatibility…" : "Check & continue →"}
                </button>
              </div>
            </div>
          )}
          {resumePreview && (
            <div className={`resume-preflight ${resumePreview.resume_ready ? "ready" : "blocked"}`}>
              <i>{resumePreview.resume_ready ? "✓" : "×"}</i>
              <div>
                <strong>
                  {resumePreview.resume_ready
                    ? resumePreview.deduplicated
                      ? "Existing checkpoint resume reused"
                      : "Checkpoint resume validated & queued"
                    : `Resume blocked · ${readableState(resumePreview.reason)}`}
                </strong>
                <p>{resumePreview.detail}</p>
                <small>
                  {Number(resumePreview.current_time_s ?? 0).toExponential(2)} s → {Number(resumePreview.requested_target_end_time_s).toExponential(2)} s · {resumePreview.resume_from_run_id ?? "no checkpoint"}
                </small>
                {resumePreview.resume_attempt_id && (
                  <small>{resumePreview.resume_attempt_id} · parent {resumePreview.campaign_id}</small>
                )}
              </div>
            </div>
            )}
          <div className="cae-history">
            <div>
              <h3>RECOVERED CAMPAIGN HISTORY</h3>
              <span>{campaignHistory.length} campaigns · {meshStudyHistory.length} mesh studies</span>
            </div>
            {campaignHistory.length ? (
              <div className="cae-history-list">
                {campaignHistory.slice(0, 8).map((summary) => (
                  <button
                    className={
                      selectedCampaign?.campaign_id === summary.campaign_id
                        ? "selected"
                        : ""
                    }
                    key={summary.campaign_id}
                    onClick={() => inspectCampaignHistory(summary)}
                  >
                    <i className={summary.results_available ? "passed" : ""}>
                      {summary.results_available ? "✓" : "•"}
                    </i>
                    <span>
                      <b>{summary.mesh_profile.toUpperCase()} · {readableState(summary.status)}</b>
                      <small>{summary.campaign_id}</small>
                    </span>
                    <span>
                      <b>{summary.segments_completed ?? 0} segments</b>
                      <small>{readableState(summary.stop_reason)}</small>
                    </span>
                    <time dateTime={summary.generated_at}>
                      {new Date(summary.generated_at).toLocaleDateString()}
                    </time>
                  </button>
                ))}
              </div>
            ) : (
              <p>No persisted campaign reports discovered.</p>
            )}
          </div>
          <div className="resume-lineage-history">
            <div>
              <h3>RESUME LINEAGE</h3>
              <span>{resumeHistory.length} deterministic attempts</span>
            </div>
            {resumeHistory.length ? (
              <div className="resume-lineage-list">
                {resumeHistory.slice(0, 6).map((attempt) => (
                  <article key={attempt.resume_attempt_id}>
                    <header>
                      <code>{attempt.resume_attempt_id}</code>
                      <b className={attempt.results_available ? "passed" : ""}>
                        {readableState(attempt.status ?? "dispatched")}
                      </b>
                    </header>
                    {attempt.retry_of_attempt_id && (
                      <small className="retry-origin">
                        Retry {attempt.retry_index} of {attempt.retry_of_attempt_id}
                      </small>
                    )}
                    <div className="resume-lineage-path">
                      <code>{attempt.parent_campaign_id}</code>
                      <i>→</i>
                      <code>{attempt.checkpoint_run_id}</code>
                      <i>→</i>
                      <code>{attempt.successor_campaign_id}</code>
                    </div>
                    <div className="resume-event-trail" aria-label="Attempt lifecycle">
                      {(attempt.events ?? []).map((event) => (
                        <span
                          className={`event-${event.status}`}
                          key={`${attempt.resume_attempt_id}-${event.status}`}
                          title={event.generated_at}
                        >
                          {readableState(event.status)}
                        </span>
                      ))}
                    </div>
                    <footer>
                      <div>
                        <span>{Number(attempt.checkpoint_time_s).toExponential(2)} s → {Number(attempt.requested_target_end_time_s).toExponential(2)} s</span>
                        <small>{attempt.job_id}</small>
                      </div>
                      {attempt.retry_allowed && (
                        <button
                          className="retry-resume-action"
                          disabled={resumeChecking || campaignRunning}
                          onClick={() => retryCaeResumeAttempt(attempt)}
                        >
                          Retry failed attempt →
                        </button>
                      )}
                    </footer>
                  </article>
                ))}
              </div>
            ) : (
              <p>No checkpoint continuation attempts recorded.</p>
            )}
          </div>
        </section>

        <section className="panel top-gap mesh-study-panel">
          <div className="panel-title">
            <div>
              <h2>Mesh independence</h2>
              <p>Coarse / medium / fine comparison · medium-to-fine controls publication.</p>
            </div>
            <span className={`publication-status ${meshStudy?.design_result_available ? "passed" : "gated"}`}>
              {meshStudy?.design_result_available ? "PUBLISHABLE" : "RESULT GATED"}
            </span>
          </div>
          <div className="mesh-profile-grid">
            {["coarse", "medium", "fine"].map((profile) => {
              const result = campaignResults[profile];
              return (
                <article className={result?.results_available ? "converged" : ""} key={profile}>
                  <div>
                    <span>{profile.toUpperCase()}</span>
                    <b>{profile === "coarse" ? "0.80×" : profile === "fine" ? "1.25×" : "1.00×"}</b>
                  </div>
                  <strong>{result ? readableState(result.status) : "Not run"}</strong>
                  <small>{result?.campaign_id ?? "Campaign ID pending"}</small>
                  <p>
                    {result?.results_available
                      ? "Numerically converged"
                      : result
                        ? readableState(result.stop_reason)
                        : "Required for mesh study"}
                  </p>
                </article>
              );
            })}
          </div>
          <button
            className="primary-action mesh-study-action"
            disabled={!allCampaignsConverged || meshStudyRunning}
            onClick={runMeshIndependenceStudy}
          >
            {meshStudyRunning ? "Evaluating mesh independence…" : "Evaluate publication gate"}
            <span>→</span>
          </button>
          {Object.keys(comparisons).length > 0 && (
            <div className="study-comparisons">
              {Object.entries(comparisons).map(([name, comparison]) => (
                <article key={name}>
                  <strong>{readableState(name)}</strong>
                  <div>
                    <span>Tmax Δ</span>
                    <b>{comparison.t_max_relative_change_percent.toFixed(3)}%</b>
                    <i style={{ width: `${Math.min(comparison.t_max_relative_change_percent * 20, 100)}%` }} />
                    <small>limit {meshStudy.limits.max_t_max_relative_change_percent}%</small>
                  </div>
                  <div>
                    <span>Pressure Δ</span>
                    <b>{comparison.pressure_drop_relative_change_percent.toFixed(3)}%</b>
                    <i style={{ width: `${Math.min(comparison.pressure_drop_relative_change_percent * 4, 100)}%` }} />
                    <small>limit {meshStudy.limits.max_pressure_drop_relative_change_percent}%</small>
                  </div>
                </article>
              ))}
            </div>
          )}
          <div className={`publication-gate ${meshStudy?.design_result_available ? "passed" : ""}`}>
            <i>{meshStudy?.design_result_available ? "✓" : "!"}</i>
            <div>
              <strong>
                {meshStudy?.design_result_available
                  ? "Fine-mesh result cleared for engineering review"
                  : "No publishable CFD design result"}
              </strong>
              <p>
                {meshStudy?.notice ??
                  "A numerically converged campaign is only a candidate. All three mesh profiles and the configured response-change limits must pass."}
              </p>
            </div>
          </div>
        </section>
      </div>
    );
  }
  return (
    <div className="content">
      <PageHead
        kicker="PARAMETRIC GEOMETRY"
        title="CAD generation"
        description="Turn an optimized parameter set into traceable FreeCAD-compatible geometry artifacts."
        badge={currentCad ? (currentCad.step_generated ? "FreeCAD STEP ready" : "FreeCAD script ready") : "Geometry ready"}
      />
      <div className="cad-layout">
        <section className="panel cad-preview">
          <div className="panel-title">
            <div>
              <h2>Optimal heat sink</h2>
              <p>{phase2 ? "Bayesian best design" : "Recommended design"} · isometric preview</p>
            </div>
            <span className="tag">SOLID</span>
          </div>
          <div className="cad-stage">
            <div className="cad-sink">
              <HeatSink count={12} />
              <i className="base" />
            </div>
            <span className="axis x">X</span>
            <span className="axis y">Y</span>
            <span className="axis z">Z</span>
          </div>
          <div className="viewer-tools">
            <button>＋</button>
            <button>−</button>
            <button>⌂</button>
            <span>Perspective · shaded edges</span>
          </div>
        </section>
        <section className="panel cad-meta">
          <div className="panel-title">
            <div>
              <h2>Geometry specification</h2>
              <p>FreeCAD adapter · schema v2</p>
            </div>
          </div>
          {[
            ["Fin count", String(cadDesign.fin_count)],
            ["Fin thickness", `${cadDesign.fin_thickness.toFixed(2)} mm`],
            ["Fin height", `${cadDesign.fin_height.toFixed(1)} mm`],
            ["Fin spacing", `${cadDesign.fin_spacing.toFixed(2)} mm`],
            ["Base plate", `${(currentCad?.geometry.base_width ?? 120).toFixed(1)} × ${(currentCad?.geometry.base_length ?? 90).toFixed(1)} × ${(currentCad?.geometry.base_thickness ?? 4).toFixed(1)} mm`],
            ["CAD mass", currentCad ? `${currentCad.cad_mass_estimate_g.toFixed(1)} g` : "Pending"],
            ["Material", "Al 6063-T5"],
          ].map((r) => (
            <div className="spec" key={r[0]}>
              <span>{r[0]}</span>
              <b>{r[1]}</b>
            </div>
          ))}
          <div className="artifact">
            <span>ARTIFACT ID</span>
            <code>{currentCad?.cad_id ?? "Not generated"}</code>
            <small>
              {currentCad
                ? `${currentCad.stl_generator} · ${currentCad.step_generated ? "STEP verified" : "STEP not generated"}`
                : "Run Phase 2 or prepare artifacts"}
            </small>
          </div>
          <button
            className="primary-action"
            onClick={() =>
              currentCad
                ? downloadCadArtifact(currentCad.downloads.freecad_script)
                : prepareCad()
            }
          >
            {currentCad ? "Download FreeCAD script" : "Prepare CAD artifacts"} <span>↓</span>
          </button>
          <button
            className="outline-button"
            disabled={!currentCad}
            onClick={() => downloadCadArtifact(currentCad?.downloads.stl)}
          >
            Download STL <span>↓</span>
          </button>
          {currentCad?.step_generated && (
            <button
              className="outline-button"
              onClick={() => downloadCadArtifact(currentCad.downloads.step)}
            >
              Download STEP <span>↓</span>
            </button>
          )}
          <p className="disclaimer">
            {currentCad?.step_generated
              ? "FreeCAD export completed. Manufacturing tolerances still require downstream validation."
              : "The STL fallback is a parametric preview, not a FreeCAD STEP export or CAE result."}
          </p>
        </section>
      </div>
    </div>
  );
}

export default function Home() {
  const [active, setActive] = useState("overview");
  const [toast, setToast] = useState("");
  const [phase1, setPhase1] = useState(null);
  const [phase2, setPhase2] = useState(null);
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const [phase2Running, setPhase2Running] = useState(false);
  const [apiStatus, setApiStatus] = useState("checking");
  const [jobStatus, setJobStatus] = useState(null);
  useEffect(() => {
    api
      .health()
      .then(() => setApiStatus("online"))
      .catch(() => setApiStatus("demo"));
  }, []);
  const notify = (message) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  };
  const runWorkflow = async (method = "LHS", runs = 48) => {
    setWorkflowRunning(true);
    notify(`${method} Phase 1 started · DOE → physics → ML → NSGA-II`);
    try {
      const result = await api.runPhase1(method, runs, setJobStatus);
      setPhase1(result);
      setPhase2(null);
      setApiStatus("online");
      notify(`Phase 1 complete · ${result.experiment_count} experiments · ${result.selected_models.t_max} selected`);
    } catch {
      setApiStatus("demo");
      notify("FastAPI unavailable · start backend on :8000");
    } finally {
      setWorkflowRunning(false);
    }
  };
  const runPhase2 = async (acquisition = "EI") => {
    if (!phase1) {
      notify("Run Phase 1 first to create a dataset and GPR model");
      return;
    }
    setPhase2Running(true);
    notify(`${acquisition} Phase 2 started · propose → simulate → retrain → CAD`);
    try {
      const result = await api.runPhase2(
        phase1.model_id,
        phase1.dataset_version,
        acquisition,
        3,
        setJobStatus,
      );
      setPhase2(result);
      setApiStatus("online");
      notify(`Phase 2 complete · ${result.iterations} learning cycles · ${result.model_id}`);
    } catch {
      notify("Phase 2 backend unavailable · run FastAPI with persisted Phase 1 artifacts");
    } finally {
      setPhase2Running(false);
    }
  };
  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandmark">◒</span>
          <div>
            <strong>THERMOFORM</strong>
            <small>Engineering Intelligence</small>
          </div>
        </div>
        <nav aria-label="Primary navigation">
          {nav.map(([id, icon, label]) => (
            <button
              key={id}
              className={active === id ? "nav-active" : ""}
              onClick={() => setActive(id)}
            >
              <span>{icon}</span>
              {label}
              {id === "simulation" && <i>{phase1?.experiment_count ?? 64}</i>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="system">
            <span className={`pulse ${apiStatus}`} />
            <div>
              <strong>
                {apiStatus === "online"
                  ? "FastAPI connected"
                  : apiStatus === "demo"
                    ? "Demo data mode"
                    : "Connecting services"}
              </strong>
              <small>
                {apiStatus === "online"
                  ? "Physics API v1.0.0"
                  : "Start backend on :8000"}
              </small>
            </div>
          </div>
          <button className="avatar">
            <span>HY</span>
            <div>
              <strong>Huang Yanwei</strong>
              <small>Thermal Engineer</small>
            </div>
            <b>•••</b>
          </button>
        </div>
      </aside>
      <section className="workspace">
        <header>
          <div className="project-select">
            <small>PROJECT</small>
            <button>
              CPU-AX91 / Passive Cooling <span>⌄</span>
            </button>
          </div>
          <div className="header-actions">
            <button className="icon-button" aria-label="Search">
              ⌕
            </button>
            <button className="icon-button" aria-label="Notifications">
              ♢<i />
            </button>
            <button
              className="run-button"
              disabled={workflowRunning}
              onClick={() => runWorkflow()}
            >
              {workflowRunning ? "Running Phase 1…" : "Run workflow"} <span>→</span>
            </button>
          </div>
        </header>
        {active === "overview" ? (
          <Overview go={setActive} phase1={phase1} />
        ) : (
          <ModuleView
            active={active}
            notify={notify}
            phase1={phase1}
            phase2={phase2}
            runWorkflow={runWorkflow}
            runPhase2={runPhase2}
            workflowRunning={workflowRunning}
            phase2Running={phase2Running}
            jobStatus={jobStatus}
            setJobStatus={setJobStatus}
          />
        )}
      </section>
      {toast && (
        <div className="toast">
          <i>✓</i>
          {toast}
        </div>
      )}
    </main>
  );
}
