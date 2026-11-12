const state = { mode: "login", recipeId: null, versionId: null, buildId: null, previousBuildId: null, poll: null };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;",
})[character]);

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : body.detail?.message || detail;
    } catch (_) { /* Keep the status message. */ }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function showError(message, target = "workspace-error") { $(target).textContent = message || ""; }
function setView(authenticated) {
  $("auth-view").hidden = authenticated;
  $("workspace-view").hidden = !authenticated;
  $("logout-button").hidden = !authenticated;
}

function addVariable(provider = "world_bank", indicator = "NY.GDP.MKTP.KD.ZG", output = "gdp_growth") {
  const row = document.createElement("div");
  row.className = "variable-row";
  row.innerHTML = `
    <select class="provider" aria-label="Provider"><option value="world_bank">World Bank</option><option value="fred">FRED</option></select>
    <input class="indicator" aria-label="Indicator ID" required value="${escapeHtml(indicator)}">
    <input class="output" aria-label="Output column" required pattern="[a-z][a-z0-9_]*" value="${escapeHtml(output)}">
    <button class="remove-variable" type="button" aria-label="Remove variable">×</button>`;
  row.querySelector(".provider").value = provider;
  row.querySelector(".remove-variable").addEventListener("click", () => {
    if ($("variables").children.length > 1) row.remove();
  });
  $("variables").appendChild(row);
}

function recipePayload() {
  const variables = [...document.querySelectorAll(".variable-row")].map((row) => ({
    provider: row.querySelector(".provider").value,
    indicator_id: row.querySelector(".indicator").value.trim(),
    output_name: row.querySelector(".output").value.trim(),
  }));
  const hasFred = variables.some((item) => item.provider === "fred");
  const formats = [];
  if ($("format-csv").checked) formats.push("csv");
  if ($("format-parquet").checked) formats.push("parquet");
  return {
    name: $("recipe-name").value.trim(),
    description: $("recipe-description").value.trim() || null,
    entities: $("entities").value.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean),
    start_date: $("start-date").value,
    end_date: $("end-date").value,
    variables,
    output_frequency: $("frequency").value,
    transformations: [],
    join: { type: $("join-type").value, keys: hasFred ? ["period"] : ["entity", "period"] },
    missing_values: $("missing-values").value,
    formats,
    validations: [],
  };
}

async function loadRecipes() {
  const recipes = await api("/api/v1/recipes");
  $("recipe-list").replaceChildren(...recipes.map((recipe) => {
    const button = document.createElement("button");
    button.className = `recipe-item${recipe.id === state.recipeId ? " active" : ""}`;
    button.type = "button";
    button.innerHTML = `<strong>${escapeHtml(recipe.name)}</strong><span>Saved draft</span>`;
    button.addEventListener("click", () => loadRecipe(recipe));
    return button;
  }));
}

function loadRecipe(recipe) {
  state.recipeId = recipe.id;
  const value = recipe.draft;
  $("recipe-name").value = value.name;
  $("recipe-description").value = value.description || "";
  $("start-date").value = value.start_date;
  $("end-date").value = value.end_date;
  $("entities").value = value.entities.join(", ");
  $("frequency").value = value.output_frequency;
  $("join-type").value = value.join.type;
  $("missing-values").value = value.missing_values;
  $("format-csv").checked = value.formats.includes("csv");
  $("format-parquet").checked = value.formats.includes("parquet");
  $("variables").replaceChildren();
  value.variables.forEach((item) => addVariable(item.provider, item.indicator_id, item.output_name));
  $("save-status").textContent = "Saved draft";
  loadRecipes().catch((error) => showError(error.message));
}

async function saveAndBuild(event) {
  event.preventDefault();
  showError("");
  $("build-button").disabled = true;
  try {
    const payload = recipePayload();
    const recipe = state.recipeId
      ? await api(`/api/v1/recipes/${state.recipeId}/draft`, { method: "PUT", body: JSON.stringify(payload) })
      : await api("/api/v1/recipes", { method: "POST", body: JSON.stringify(payload) });
    state.recipeId = recipe.id;
    const version = await api(`/api/v1/recipes/${recipe.id}/versions`, { method: "POST" });
    state.versionId = version.id;
    const build = await api(`/api/v1/recipe-versions/${version.id}/builds`, { method: "POST" });
    state.buildId = build.id;
    state.previousBuildId = null;
    if (build.status === "succeeded" && $("force-refresh").checked) {
      await rerunBuild("refresh");
      return;
    }
    if (build.status === "planned" || build.status === "queued") {
      const refresh = $("force-refresh").checked ? "?refresh_provider_inputs=true" : "";
      await api(`/api/v1/builds/${build.id}/execute${refresh}`, { method: "POST" });
    }
    $("build-panel").hidden = false;
    $("results-panel").hidden = true;
    $("build-status").textContent = "queued";
    $("build-title").textContent = "Dataset build started";
    $("cancel-build").hidden = false;
    $("retry-build").hidden = true;
    await loadRecipes();
    startPolling();
  } catch (error) { showError(error.message); }
  finally { $("build-button").disabled = false; }
}

const progress = { queued: 10, retrieving: 32, validating: 58, exporting: 76, finalizing: 90, cancelling: 55, succeeded: 100, failed: 100, cancelled: 100 };
async function pollBuild() {
  if (!state.buildId) return;
  try {
    const job = await api(`/api/v1/builds/${state.buildId}/job`);
    $("build-status").textContent = job.status;
    $("build-message").textContent = job.error_message || `Current step: ${job.progress}.`;
    $("progress-fill").style.width = `${progress[job.progress] || 15}%`;
    if (["succeeded", "failed", "cancelled"].includes(job.status)) {
      clearInterval(state.poll); state.poll = null;
      $("cancel-build").hidden = true;
      $("retry-build").hidden = job.status === "succeeded";
      if (job.status === "succeeded") await loadResults();
    }
  } catch (error) { showError(error.message); }
}
function startPolling() { clearInterval(state.poll); pollBuild(); state.poll = setInterval(pollBuild, 1500); }

async function loadResults() {
  const [build, preview, validation, exports] = await Promise.all([
    api(`/api/v1/builds/${state.buildId}`),
    api(`/api/v1/builds/${state.buildId}/preview`),
    api(`/api/v1/builds/${state.buildId}/validation`),
    api(`/api/v1/builds/${state.buildId}/exports`),
  ]);
  $("results-panel").hidden = false;
  $("replay-build").disabled = !build.can_replay;
  $("return-build").hidden = !state.previousBuildId;
  const checksum = `Dataset SHA-256: ${build.dataset_checksum || "unavailable"}`;
  const replay = build.replay_matches === null ? "" : (
    `${build.replay_matches ? "Replay matches" : "Replay differs from"} the original. ` +
    `Original SHA-256: ${build.original_dataset_checksum}. `
  );
  const availability = build.can_replay ? "" : " Replay requires a complete set of saved inputs.";
  const warning = build.replay_version_warning ? ` ${build.replay_version_warning}` : "";
  $("replay-result").textContent = replay + checksum + availability + warning;
  const header = preview.columns.map((item) => `<th>${escapeHtml(item)}</th>`).join("");
  const rows = preview.rows.map((row) => `<tr>${preview.columns.map((key) => `<td>${escapeHtml(row[key])}</td>`).join("")}</tr>`).join("");
  $("preview-result").innerHTML = `<h2>Dataset preview</h2><p>${preview.preview_row_count} of ${preview.total_row_count} rows</p><table><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table>`;
  $("validation-result").innerHTML = `<h2>Validation results</h2>${validation.length ? validation.map((item) => `<div class="finding"><strong>${escapeHtml(item.severity)}: ${escapeHtml(item.code)}</strong><p>${escapeHtml(item.message)}</p></div>`).join("") : "<p>No validation findings.</p>"}`;
  $("exports-result").innerHTML = `<h2>Research bundle</h2><div class="download-list">${exports.map((item) => `<a class="download-link" href="/api/v1/exports/${encodeURIComponent(item.id)}/download"><span>${escapeHtml(item.name)}</span><span>${Math.ceil(item.size_bytes / 1024)} KB ↓</span></a>`).join("")}</div>`;
}

async function rerunBuild(mode) {
  const button = $(mode === "replay" ? "replay-build" : "refresh-build");
  button.disabled = true;
  try {
    const job = await api(`/api/v1/builds/${state.buildId}/rerun?mode=${mode}`, { method: "POST" });
    state.previousBuildId = state.buildId;
    state.buildId = job.build_id;
    $("build-panel").hidden = false;
    $("results-panel").hidden = true;
    $("build-title").textContent = mode === "replay" ? "Replaying saved inputs" : "Building with fresh data";
    $("cancel-build").hidden = false;
    $("retry-build").hidden = true;
    startPolling();
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
}

async function cancelBuild() { try { await api(`/api/v1/builds/${state.buildId}/cancel`, { method: "POST" }); await pollBuild(); } catch (error) { showError(error.message); } }
async function retryBuild() {
  try {
    const retry = await api(`/api/v1/builds/${state.buildId}/retry`, { method: "POST" });
    state.buildId = retry.id;
    await api(`/api/v1/builds/${retry.id}/execute`, { method: "POST" });
    $("cancel-build").hidden = false; $("retry-build").hidden = true; startPolling();
  } catch (error) { showError(error.message); }
}

async function loadAudit() {
  try {
    const events = await api("/api/v1/audit-events?limit=100");
    $("audit-list").innerHTML = events.map((item) => `<div class="audit-row"><time>${escapeHtml(new Date(item.created_at).toLocaleString())}</time><div><strong>${escapeHtml(item.action.replaceAll(".", " "))}</strong><p>${escapeHtml(item.resource_type)}${item.resource_id ? ` · ${escapeHtml(item.resource_id)}` : ""}</p></div></div>`).join("") || "<p>No activity yet.</p>";
    $("audit-panel").hidden = false;
    $("recipe-form").hidden = true;
  } catch (error) { showError(error.message); }
}

async function authenticate(event) {
  event.preventDefault(); showError("", "auth-error");
  try {
    const user = await api(`/api/v1/auth/${state.mode}`, { method: "POST", body: JSON.stringify({ email: $("auth-email").value, password: $("auth-password").value }) });
    enterWorkspace(user);
  } catch (error) { showError(error.message, "auth-error"); }
}
function enterWorkspace(user) { setView(true); $("account-email").textContent = user.email; loadRecipes().catch((error) => showError(error.message)); }
function resetDraft() { state.recipeId = null; state.versionId = null; state.buildId = null; state.previousBuildId = null; $("recipe-form").reset(); $("variables").replaceChildren(); addVariable(); $("save-status").textContent = "New draft"; $("build-panel").hidden = true; $("results-panel").hidden = true; }

document.addEventListener("DOMContentLoaded", async () => {
  addVariable();
  $("add-variable").addEventListener("click", () => addVariable("world_bank", "FP.CPI.TOTL.ZG", "inflation"));
  $("recipe-form").addEventListener("submit", saveAndBuild);
  $("auth-form").addEventListener("submit", authenticate);
  $("auth-mode").addEventListener("click", () => { state.mode = state.mode === "login" ? "register" : "login"; $("auth-title").textContent = state.mode === "login" ? "Sign in" : "Create account"; $("auth-submit").textContent = $("auth-title").textContent; $("auth-mode").textContent = state.mode === "login" ? "Create a new account" : "Use an existing account"; });
  $("logout-button").addEventListener("click", async () => { await api("/api/v1/auth/logout", { method: "POST" }); location.reload(); });
  $("new-recipe").addEventListener("click", resetDraft);
  $("cancel-build").addEventListener("click", cancelBuild);
  $("retry-build").addEventListener("click", retryBuild);
  $("replay-build").addEventListener("click", () => rerunBuild("replay"));
  $("refresh-build").addEventListener("click", () => rerunBuild("refresh"));
  $("return-build").addEventListener("click", async () => {
    state.buildId = state.previousBuildId;
    state.previousBuildId = null;
    $("build-title").textContent = "Previous dataset build";
    await pollBuild();
  });
  $("show-audit").addEventListener("click", loadAudit);
  $("close-audit").addEventListener("click", () => { $("audit-panel").hidden = true; $("recipe-form").hidden = false; });
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => { document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === tab)); document.querySelectorAll(".result-panel").forEach((panel) => panel.hidden = panel.id !== tab.dataset.panel); }));
  try { enterWorkspace(await api("/api/v1/auth/me")); } catch (_) { setView(false); }
});
