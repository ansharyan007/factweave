const $ = (selector) => document.querySelector(selector);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
let state = {
  documents: [],
  facts: [],
  relationships: [],
  issues: [],
  predicates: [],
};
let view = "overview",
  kind = "all",
  limit = 24,
  busy = false,
  signature = "";
let replacementId = null,
  refreshVersion = 0,
  evidenceDocumentId = null;
const labels = {
  corroborates: "Corroboration",
  contradicts: "Likely contradiction",
  reconciled: "Explained by context",
  uncertain: "Needs context",
};
function notice(message, error = false) {
  const el = $("#notice");
  el.hidden = false;
  el.className = error ? "error" : "";
  el.textContent = message;
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let error;
    try {
      error = await response.json();
    } catch {
      error = { detail: response.statusText };
    }
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
async function refresh() {
  const version = ++refreshVersion;
  try {
    const next = await request("/api/knowledge");
    if (version !== refreshVersion) return;
    const nextSignature = JSON.stringify(next);
    if (nextSignature !== signature) {
      state = next;
      signature = nextSignature;
      if (
        evidenceDocumentId &&
        !state.documents.some((d) => d.id === evidenceDocumentId)
      ) {
        $("#evidence-dialog").close();
        evidenceDocumentId = null;
      }
      render();
    }
  } catch (error) {
    notice("Cannot reach the server: " + error.message, true);
  }
}
function setView(next) {
  view = next;
  limit = 24;
  document
    .querySelectorAll(".nav-item")
    .forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  render();
}
function evidenceButton(fact) {
  return `<button data-evidence="${esc(fact.id)}">${esc(fact.document_name)} · p. ${fact.page} ↗</button>`;
}
function claim(fact) {
  return `<div class="claim"><div class="context-tag">${esc(fact.context.period || "Period unspecified")} · ${esc(fact.context.scope || "Scope unspecified")} &middot; ${esc(fact.context.assertion_type || "reported")}${fact.context.subject_inferred ? " &middot; inferred subject" : ""}</div><strong>${esc(fact.raw_value)}</strong><div class="quote">“${esc(fact.quote)}”</div><div class="source">${evidenceButton(fact)}</div></div>`;
}
function relationCard(relation) {
  const left = state.facts.find((f) => f.id === relation.left_id),
    right = state.facts.find((f) => f.id === relation.right_id);
  return `<article class="relation-card"><div class="card-top"><span class="badge ${relation.kind}">${labels[relation.kind]}</span><span class="muted">2 source documents</span></div><h3>${esc(left.subject)} <span class="muted">/</span> ${esc(left.predicate)}</h3><p class="reason">${esc(relation.reason)}</p><div class="pair">${claim(left)}<span class="pair-symbol">${relation.kind === "corroborates" ? "≈" : "↔"}</span>${claim(right)}</div><div class="card-bottom"><details><summary>How this connection was made</summary><ol>${relation.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol><p>${esc(relation.caveat)}</p></details><small>Heuristic confidence ${Math.round(relation.confidence * 100)}%</small></div></article>`;
}
function factCard(fact) {
  return `<article class="fact-card"><div class="card-top"><span class="badge">${esc(fact.predicate)}</span><span class="muted">${esc(fact.method)} extraction</span></div><h3>${esc(fact.subject)}</h3>${claim(fact)}<div class="card-bottom"><details><summary>Normalization & grounding</summary><p>${esc(fact.normalized.normalization)}</p><p>Evidence characters ${fact.evidence_start}–${fact.evidence_end} in the normalized source block. ${esc(fact.confidence_note)}</p></details><small>Heuristic confidence ${Math.round(fact.confidence * 100)}%</small></div></article>`;
}
function issueCard(issue) {
  return `<article class="issue-card"><span class="badge issue">Extraction limitation</span><h3>${esc(issue.kind.replaceAll("_", " "))}</h3><p class="reason">${esc(issue.reason)}</p>${issue.quote ? `<div class="claim"><div class="quote">“${esc(issue.quote)}”</div></div>` : '<div class="claim">No readable text was recovered from this page. Open the source image to inspect the missed content.</div>'}<div class="card-bottom"><div class="source">${evidenceButton(issue)}</div><small>No unsupported claim asserted</small></div></article>`;
}
function render() {
  $("#stat-documents").textContent = state.documents.length;
  $("#stat-facts").textContent = state.facts.length;
  $("#stat-relations").textContent = state.relationships.length;
  $("#stat-issues").textContent = state.issues.length;
  $("#issue-count").textContent = state.issues.length;
  $("#library-count").textContent = state.documents.length;
  const titles = {
    overview: "Overview",
    facts: "Fact explorer",
    relations: "Relationships",
    issues: "Review queue",
  };
  $("#view-label").textContent = titles[view];
  $("#results-title").textContent = {
    overview: "Across your documents",
    facts: "Every claim, grounded",
    relations: "Where the evidence connects",
    issues: "What the system could not resolve",
  }[view];
  $("#documents-section").hidden = view !== "overview";
  $("#demo-banner").hidden = view !== "overview";
  $("#filters").hidden = view === "facts" || view === "issues";
  $("#predicate-filter").hidden = view === "issues";
  $("#document-list").innerHTML = state.documents.length
    ? state.documents
        .map(
          (doc) =>
            `<div class="document-row"><span class="pdf-icon">PDF</span><div class="doc-info"><div class="doc-name">${esc(doc.name)}</div><div class="doc-meta">${doc.pages} page${doc.pages === 1 ? "" : "s"} · ${esc(doc.mode)} · ${doc.processed_pages}/${doc.pages} processed &middot; ${state.facts.filter(f => f.document_id === doc.id).length} facts${doc.error ? " · " + esc(doc.error) : ""}</div></div><span class="doc-state ${doc.status}">${esc(doc.status.replaceAll("_", " "))}</span><div class="document-actions">${doc.status === "failed" ? `<button class="secondary" data-retry="${doc.id}">Retry</button>` : ""}<button class="secondary" data-reprocess="${doc.id}">Reprocess</button><button class="secondary" data-replace="${doc.id}" aria-label="Replace ${esc(doc.name)}" ${busy || ["queued", "processing"].includes(doc.status) ? 'disabled title="Wait for processing to finish"' : ""}>Replace</button><button class="secondary danger" data-delete="${doc.id}" aria-label="Delete ${esc(doc.name)}" ${busy || ["queued", "processing"].includes(doc.status) ? 'disabled title="Wait for processing to finish"' : ""}>Delete</button></div></div>`,
        )
        .join("")
    : '<div class="empty"><strong>Your source library starts here</strong>Upload PDFs or load the synthetic demo to follow a claim back to its evidence.</div>';
  const previous = $("#predicate-filter").value;
  $("#predicate-filter").innerHTML =
    '<option value="">All fact types</option>' +
    state.predicates
      .map((p) => `<option value="${esc(p)}">${esc(p)}</option>`)
      .join("");
  $("#predicate-filter").value = previous;
  syncControls();
  renderResults();
}
function syncControls() {
  $("#upload-button").disabled = busy;
  $("#demo-button").disabled = busy;
  const active = state.documents.some((d) =>
    ["queued", "processing"].includes(d.status),
  );
  $("#reset-collection").disabled = busy || active || !state.documents.length;
  $("#reset-collection").title = active
    ? "Wait for all PDFs to finish processing"
    : "";
  document
    .querySelectorAll("[data-delete], [data-replace], [data-retry], [data-reprocess]")
    .forEach((button) => {
      const id =
        button.dataset.delete || button.dataset.replace || button.dataset.retry || button.dataset.reprocess;
      const doc = state.documents.find((d) => d.id === id);
      button.disabled =
        busy || !doc || ["queued", "processing"].includes(doc.status);
    });
}
async function changeCollection(action) {
  if (busy) return;
  busy = true;
  syncControls();
  try {
    await action();
    await refresh();
  } catch (error) {
    notice(error.message, true);
    await refresh();
  } finally {
    busy = false;
    syncControls();
  }
}
function renderResults() {
  const search = $("#search").value.toLowerCase(),
    predicate = $("#predicate-filter").value;
  let items;
  if (view === "facts")
    items = state.facts.filter(
      (f) =>
        (!predicate || f.predicate === predicate) &&
        JSON.stringify(f).toLowerCase().includes(search),
    );
  else if (view === "issues")
    items = state.issues.filter((i) =>
      JSON.stringify(i).toLowerCase().includes(search),
    );
  else
    items = state.relationships.filter((r) => {
      const f = state.facts.find((f) => f.id === r.left_id),
        g = state.facts.find((f) => f.id === r.right_id);
      return (
        (kind === "all" || r.kind === kind) &&
        (!predicate || f.predicate === predicate) &&
        JSON.stringify([r, f, g]).toLowerCase().includes(search)
      );
    });
  const renderer =
    view === "facts" ? factCard : view === "issues" ? issueCard : relationCard;
  $("#results").innerHTML = items.length
    ? items.slice(0, limit).map(renderer).join("")
    : `<div class="empty"><strong>${state.documents.length ? "No matching results yet" : "The interesting part is between the documents"}</strong>${state.documents.some((d) => ["queued", "processing"].includes(d.status)) ? "Processing is in progress. Results will appear automatically." : state.facts.length ? "Facts were extracted. Open Fact explorer to inspect them; a relationship also requires comparable claims in different documents." : "No facts extracted yet. Open Review queue for the skipped evidence, or use Reprocess after updating the extractor. Scanned PDFs require OCR."}</div>`;
  $("#more").hidden = items.length <= limit;
}
async function uploadFiles(files) {
  if (busy) return;
  busy = true;
  syncControls();
  try {
    for (const file of files) {
      notice(`Uploading ${file.name}…`);
      const body = new FormData();
      body.append("file", file);
      body.append("mode", $("#mode").value);
      const result = await request("/api/documents", { method: "POST", body });
      notice(
        result.duplicate
          ? `${file.name} already exists; its facts were preserved.`
          : `${file.name} queued. Facts and evidence will appear as processing completes.`,
      );
      await refresh();
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy = false;
    syncControls();
    $("#file-input").value = "";
  }
}
async function showEvidence(id) {
  const fact =
    state.facts.find((f) => f.id === id) ||
    state.issues.find((i) => i.id === id);
  if (!fact) return;
  evidenceDocumentId = fact.document_id;
  $("#evidence-title").textContent =
    `${fact.document_name} · page ${fact.page}`;
  $("#evidence-body").textContent = "Loading source page…";
  $("#evidence-dialog").showModal();
  try {
    const page = await request(
      `/api/documents/${fact.document_id}/pages/${fact.page}`,
    );
    const b = fact.bbox;
    $("#evidence-body").innerHTML =
      `<div class="evidence-grid"><div><h3>${fact.predicate ? "Original quotation" : "Extraction finding"}</h3><blockquote>${esc(fact.quote || "No extractable text on this page.")}</blockquote><p>${esc(fact.normalized?.normalization || fact.reason)}</p><a class="secondary" href="/api/documents/${fact.document_id}/pdf#page=${fact.page}" target="_blank" rel="noreferrer">Open original PDF ↗</a>${fact.evidence_parts ? `<h3>Separate grounding spans</h3>${fact.evidence_parts.map((part) => `<p><strong>${esc(part.role)}</strong> · <a href="/api/documents/${fact.document_id}/pdf#page=${part.page}" target="_blank" rel="noreferrer">p. ${part.page}</a><br>“${esc(part.quote)}”</p>`).join("")}<p>Document subject and layout context are inferred; inspect these spans before relying on the claim.</p>` : ""}<h3>Extracted page text</h3><pre>${esc(page.text || "[Image-only page: OCR required]")}</pre><p>The gold rectangle marks the enclosing source block. Quotes preserve the text after whitespace normalization.</p></div><div class="page-wrap"><img alt="Source PDF page ${fact.page}" src="/api/documents/${fact.document_id}/pages/${fact.page}/image">${b ? `<div class="highlight" style="left:${(b[0] / page.width) * 100}%;top:${(b[1] / page.height) * 100}%;width:${((b[2] - b[0]) / page.width) * 100}%;height:${((b[3] - b[1]) / page.height) * 100}%"></div>` : ""}</div></div>`;
  } catch (error) {
    $("#evidence-body").textContent = error.message;
  }
}
document
  .querySelectorAll("[data-view]")
  .forEach((el) =>
    el.addEventListener("click", () => setView(el.dataset.view)),
  );
document.querySelectorAll("[data-kind]").forEach((el) =>
  el.addEventListener("click", () => {
    kind = el.dataset.kind;
    limit = 24;
    document
      .querySelectorAll("[data-kind]")
      .forEach((b) => b.classList.toggle("active", b === el));
    renderResults();
  }),
);
$("#search").addEventListener("input", () => {
  limit = 24;
  renderResults();
});
$("#predicate-filter").addEventListener("change", () => {
  limit = 24;
  renderResults();
});
$("#more").addEventListener("click", () => {
  limit += 24;
  renderResults();
});
$("#upload-button").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", (event) =>
  uploadFiles(event.target.files),
);
$("#demo-button").addEventListener("click", async () => {
  await changeCollection(async () => {
    await request("/api/demo", { method: "POST" });
    notice(
      "Synthetic demo PDFs queued. These are fictional examples, not the assignment starter documents.",
    );
  });
});
$("#results").addEventListener("click", (event) => {
  const button = event.target.closest("[data-evidence]");
  if (button) showEvidence(button.dataset.evidence);
});
$("#document-list").addEventListener("click", async (event) => {
  if (busy) return;
  const reprocess = event.target.closest("[data-reprocess]");
  if (reprocess) {
    await changeCollection(async () => {
      await request(`/api/documents/${reprocess.dataset.reprocess}/reprocess?mode=${encodeURIComponent($("#mode").value)}`, {method: "POST"});
      notice("Reprocessing the saved PDF with the selected extractor. Facts and links will refresh automatically.");
    });
    return;
  }
  const remove = event.target.closest("[data-delete]");
  if (remove) {
    const doc = state.documents.find((d) => d.id === remove.dataset.delete);
    if (
      !doc ||
      !window.confirm(
        `Delete "${doc.name}"? Its uploaded copy, facts, evidence, review findings and links will be removed. You can upload it again later.`,
      )
    )
      return;
    await changeCollection(async () => {
      await request(`/api/documents/${doc.id}`, { method: "DELETE" });
      notice(`Deleted ${doc.name} and its facts and links.`);
    });
    return;
  }
  const replace = event.target.closest("[data-replace]");
  if (replace) {
    replacementId = replace.dataset.replace;
    $("#replacement-input").value = "";
    $("#replacement-input").click();
    return;
  }
  const button = event.target.closest("[data-retry]");
  if (button) {
    await changeCollection(async () => {
      await request(`/api/documents/${button.dataset.retry}/retry`, {
        method: "POST",
      });
    });
  }
});
$("#replacement-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  const doc = state.documents.find((d) => d.id === replacementId);
  replacementId = null;
  if (
    !file ||
    !doc ||
    !window.confirm(
      `Replace "${doc.name}" with "${file.name}"? Its old facts and links will be removed and rebuilt using the selected extraction mode. Invalid files leave the original intact.`,
    )
  )
    return;
  await changeCollection(async () => {
    const body = new FormData();
    body.append("file", file);
    body.append("mode", $("#mode").value);
    const result = await request(`/api/documents/${doc.id}`, {
      method: "PUT",
      body,
    });
    notice(
      result.duplicate
        ? "This PDF and extraction mode are unchanged; existing facts were kept."
        : `Replaced ${doc.name} with ${file.name}. Processing new facts and links…`,
    );
  });
  event.target.value = "";
});
$("#reset-collection").addEventListener("click", async () => {
  if (
    !window.confirm(
      `Clear all ${state.documents.length} uploaded PDFs and their facts, evidence, review findings and links? Original files in samples/ and starter-datasets/ are kept.`,
    )
  )
    return;
  await changeCollection(async () => {
    await request("/api/collection/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    $("#search").value = "";
    $("#predicate-filter").value = "";
    kind = "all";
    document
      .querySelectorAll("[data-kind]")
      .forEach((button) =>
        button.classList.toggle("active", button.dataset.kind === "all"),
      );
    limit = 24;
    notice(
      "Collection cleared. Upload your own PDFs to build a new knowledge layer.",
    );
  });
});
$("#close-evidence").addEventListener("click", () =>
  $("#evidence-dialog").close(),
);
const drop = $("#upload-panel");
drop.addEventListener("dragover", (event) => {
  event.preventDefault();
  drop.classList.add("dragover");
});
drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  drop.classList.remove("dragover");
  uploadFiles(event.dataTransfer.files);
});
refresh();
setInterval(refresh, 1800);
