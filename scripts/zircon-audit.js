(() => {
  "use strict";

  const DATA_URL = "data/zircon_name_audit.json";
  const REVIEW_PREFIX = "zircon-name-reviews:";
  const REVIEW_FORMAT = "mir2ei-zircon-name-reviews";
  const CATEGORIES = [
    ["items", "装备 / 道具"], ["monsters", "怪物"], ["npcs", "NPC"],
    ["magics", "技能"], ["maps", "地图"],
  ];
  const KINDS = {
    system_entity: "System.db 实体",
    mapping_key: "未链接汉化键",
    wiki_entity: "百科实体",
    wiki_supplemental: "地图补充记录",
  };
  const REVIEW_LABELS = {
    not_reviewed: "尚未审校",
    confirmed_correct: "人工确认一致",
    needs_correction: "人工确认需修正",
    insufficient_evidence: "证据不足",
  };
  const FLAG_LABELS = {
    agrees_with_encyclopedia: "与百科译名相同",
    differs_from_encyclopedia: "与百科译名不同·待核",
    suspected_untranslated: "译名与英文键相同·待核",
    missing: "缺少中文译名",
    unverified: "无可比较的百科译名",
  };
  const CATEGORY_LABELS = Object.fromEntries(CATEGORIES);
  const state = { audit: null, records: [], searchable: new Map(), reviews: {}, reviewKey: "", filtered: [], page: 0 };
  const byId = (id) => document.getElementById(id);
  const basePath = "./";

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null && text !== "") node.textContent = String(text);
    return node;
  }

  function valueText(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (Array.isArray(value)) return value.map(valueText).join(" · ");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function localPage(path) {
    if (!path) return null;
    const clean = String(path).replace(/^\/+/, "");
    return new URL(basePath + clean, window.location.href).href;
  }

  function appendLink(parent, path, label, className) {
    if (!path) return;
    const link = element("a", className, label);
    link.href = localPage(path);
    parent.append(link);
  }

  function flash(message, type) {
    const target = byId("review-message");
    target.textContent = message;
    target.classList.toggle("error", type === "error");
    target.classList.toggle("saved", type === "saved");
  }

  function loadReviews() {
    state.reviewKey = REVIEW_PREFIX + state.audit.build_fingerprint;
    try {
      const saved = window.localStorage.getItem(state.reviewKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) state.reviews = parsed;
      }
    } catch (error) {
      flash("浏览器存储不可用；当前页仍可审校并导出记录。", "error");
    }
  }

  function reviewFor(recordId) {
    const review = state.reviews[recordId];
    return review && typeof review === "object"
      ? { status: REVIEW_LABELS[review.status] ? review.status : "not_reviewed", note: String(review.note || "") }
      : { status: "not_reviewed", note: "" };
  }

  function storeReview(recordId, status, note) {
    const cleanNote = String(note || "").trim();
    if (status === "not_reviewed" && !cleanNote) delete state.reviews[recordId];
    else state.reviews[recordId] = { status, note: cleanNote, updated_at: new Date().toISOString() };
    try {
      window.localStorage.setItem(state.reviewKey, JSON.stringify(state.reviews));
      flash(`本地已保存 · ${Object.keys(state.reviews).length} 条审校记录`, "saved");
      return true;
    } catch (error) {
      flash("本地存储写入失败；请立即导出审校 JSON。", "error");
      return false;
    }
  }

  function renderProvenance() {
    const provenance = state.audit.provenance || {};
    const zircon = provenance.zircon || {};
    const wiki = provenance.wiki || {};
    const receipt = byId("provenance");
    receipt.replaceChildren();
    const stateLabel = element("span", "receipt-state");
    stateLabel.append(element("i"), document.createTextNode(" 证据快照已载入"));
    receipt.append(stateLabel);
    const facts = [
      ["来源", `${zircon.file || "db_names.json"} · ${zircon.source_branch || "分支未记录"}`],
      ["来源提交", String(zircon.file_commit || "未记录").slice(0, 12)],
      ["文件 SHA-256", String(zircon.sha256 || "未记录").slice(0, 16) + "…"],
      ["百科数据", wiki.wiki_data_generated_at || "生成时间未记录"],
      ["构建指纹", String(state.audit.build_fingerprint || "").slice(0, 12)],
    ];
    for (const [label, value] of facts) {
      const item = element("span", "receipt-item");
      item.append(element("span", "", `${label}:`), element("b", label.includes("SHA") || label.includes("指纹") ? "receipt-mono" : "", value));
      receipt.append(item);
    }
    const note = zircon.timestamp_note;
    if (note) {
      const disclaimer = element("span", "receipt-item receipt-note", note);
      receipt.append(disclaimer);
    }
  }

  function renderCategoryStats() {
    const host = byId("category-stats");
    host.replaceChildren();
    const confirmedByCategory = new Map(CATEGORIES.map(([key]) => [key, 0]));
    for (const record of state.records) {
      if (reviewFor(record.record_id).status !== "confirmed_correct") continue;
      const count = confirmedByCategory.get(record.category);
      if (count !== undefined) confirmedByCategory.set(record.category, count + 1);
    }
    for (const [key, label] of CATEGORIES) {
      const summary = state.audit.summary[key] || {};
      const card = element("article", "category-card");
      const heading = element("div", "category-name");
      const choose = element("button", "", label);
      choose.type = "button";
      choose.dataset.categoryChoice = key;
      heading.append(choose, element("span", "", "对照"));
      card.append(heading, element("strong", "category-match", `${summary.identity_matches || 0}/${summary.system_entities || 0}`));
      const details = element("div", "category-sub");
      details.append(metric("差异", summary.suspected_mismatches || 0, ""));
      details.append(metric("缺译", summary.missing_zh || 0, ""));
      details.append(metric("未链接键", summary.unlinked_translation_keys || 0, ""));
      if (key === "maps") details.append(metric("补充未链接", summary.unlinked_supplemental_website_records || 0, ""));
      card.append(details, element("div", "category-sub", `百科页 ${summary.website_entities || 0} · 人工确认正确 ${confirmedByCategory.get(key)}`));
      host.append(card);
    }
  }

  function metric(label, count, suffix) {
    const item = element("span");
    item.append(document.createTextNode(`${label} `), element("b", "", `${count}${suffix}`));
    return item;
  }

  function fillStatusFilter() {
    const select = byId("status");
    const labels = state.audit.status_labels || {};
    for (const [status, label] of Object.entries(labels)) {
      const option = element("option", "", label);
      option.value = status;
      select.append(option);
    }
  }

  function buildSearchCache() {
    for (const record of state.records) {
      const material = [
        record.record_id, record.category, record.kind, record.status,
        record.source && record.source.index,
        record.source && record.source.english_key,
        record.source && record.source.attributes,
        record.translation && record.translation.english_key,
        record.translation && record.translation.zh_raw,
        record.translation && record.translation.ja_raw,
        record.translation && record.translation.alternate_mapping_keys,
        record.wiki && record.wiki.name, record.wiki && record.wiki.zh,
        record.wiki && record.wiki.attributes, record.wiki && record.wiki.page_url_candidate,
        record.candidate_wiki, record.candidate_mapping_keys,
      ];
      state.searchable.set(record.record_id, JSON.stringify(material).toLocaleLowerCase());
    }
  }

  function currentFilter() {
    const query = byId("search").value.trim().toLocaleLowerCase();
    const exactRecord = query ? state.records.find((record) => record.record_id.toLocaleLowerCase() === query) : null;
    const category = byId("category").value;
    const status = byId("status").value;
    const kind = byId("kind").value;
    const review = byId("review").value;
    state.filtered = state.records.filter((record) => {
      if (category !== "all" && record.category !== category) return false;
      if (status !== "all" && record.status !== status) return false;
      if (kind !== "all" && record.kind !== kind) return false;
      if (review !== "all" && reviewFor(record.record_id).status !== review) return false;
      return !query || (exactRecord ? record.record_id === exactRecord.record_id : state.searchable.get(record.record_id).includes(query));
    });
    state.page = Math.min(state.page, Math.max(0, Math.ceil(state.filtered.length / pageSize()) - 1));
  }

  function pageSize() { return Number(byId("page-size").value) || 50; }

  function render() {
    currentFilter();
    const count = state.filtered.length;
    const size = pageSize();
    const pageCount = Math.max(1, Math.ceil(count / size));
    const from = count ? state.page * size + 1 : 0;
    const to = Math.min(count, (state.page + 1) * size);
    byId("result-count").textContent = `${count.toLocaleString()} 条 · ${from}–${to}`;
    const host = byId("results");
    host.setAttribute("aria-busy", "false");
    host.replaceChildren();
    if (!count) {
      const empty = element("div", "empty-state");
      empty.append(element("strong", "", "没有符合条件的记录"), element("p", "", "改用英文键、编号、中文名或清除部分筛选。"));
      host.append(empty);
    } else {
      for (const record of state.filtered.slice(state.page * size, (state.page + 1) * size)) host.append(renderRecord(record));
    }
    renderPagination(pageCount);
  }

  function renderPagination(pageCount) {
    const host = byId("pagination");
    host.replaceChildren();
    if (state.filtered.length <= pageSize()) return;
    host.append(pageButton("‹", state.page - 1, state.page === 0, "上一页"));
    const first = Math.max(0, state.page - 2);
    const last = Math.min(pageCount - 1, state.page + 2);
    if (first > 0) {
      host.append(pageButton("1", 0, false, "第 1 页"));
      if (first > 1) host.append(element("span", "pagination-gap", "…"));
    }
    for (let page = first; page <= last; page += 1) host.append(pageButton(String(page + 1), page, false, `第 ${page + 1} 页`, page === state.page));
    if (last < pageCount - 1) {
      if (last < pageCount - 2) host.append(element("span", "pagination-gap", "…"));
      host.append(pageButton(String(pageCount), pageCount - 1, false, `第 ${pageCount} 页`));
    }
    host.append(pageButton("›", state.page + 1, state.page >= pageCount - 1, "下一页"));
  }

  function pageButton(label, page, disabled, title, current) {
    const button = element("button", "", label);
    button.type = "button";
    button.disabled = disabled;
    button.title = title;
    if (current) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => { state.page = page; render(); byId("results").scrollIntoView({ block: "start" }); });
    return button;
  }

  function renderRecord(record) {
    const card = element("article", "record-card");
    card.dataset.recordId = record.record_id;
    const source = record.source || {};
    const translation = record.translation || {};
    const wiki = record.wiki || {};
    const header = element("header", "record-header");
    const heading = element("div", "record-heading");
    const kicker = element("div", "record-kicker");
    kicker.append(element("span", "", CATEGORY_LABELS[record.category] || record.category));
    kicker.append(element("span", "", "·"), element("span", "", KINDS[record.kind] || record.kind));
    if (source.index !== undefined && source.index !== null) kicker.append(element("span", "", `· Index ${source.index}`));
    heading.append(kicker);
    const title = element("h3", "record-title");
    const english = source.english_key || translation.english_key || wiki.name || "未命名记录";
    title.append(document.createTextNode(english));
    if (translation.zh_raw) title.append(element("span", "record-zh", translation.zh_raw));
    heading.append(title, element("div", "record-id", record.record_id));
    const badges = element("div", "record-badges");
    const statusBadge = element("span", `audit-badge status-${record.status}`, record.status_label || record.status);
    badges.append(statusBadge);
    badges.append(element("span", "audit-badge", `身份：${record.identity && record.identity.status || "unmatched"}`));
    const review = reviewFor(record.record_id);
    if (review.status !== "not_reviewed") badges.append(element("span", "audit-badge", REVIEW_LABELS[review.status]));
    header.append(heading, badges);
    card.append(header);

    const body = element("div", "record-body");
    body.append(renderSourceSide(record, source, translation));
    body.append(renderWikiSide(record, wiki));
    card.append(body);
    card.append(renderRecordFooter(record, review));
    return card;
  }

  function renderSourceSide(record, source, translation) {
    const side = element("section", "evidence-side source-side");
    const label = element("div", "side-label");
    label.append(document.createTextNode("ZIRCON · 源数据"));
    if (source.table) label.append(element("span", "side-hint", `${source.table}[${source.index}]`));
    side.append(label);
    const pairs = element("dl", "translation-pair");
    appendPair(pairs, "英文键", source.english_key || translation.english_key, "");
    appendPair(pairs, "中文 zh", translation.zh_raw, "translation-value");
    appendPair(pairs, "日文 ja", translation.ja_raw, "");
    appendPair(pairs, "关联条目", translation.english_key_entity_count, "");
    side.append(pairs);
    const flags = record.translation_flags || [];
    if (flags.length) {
      const flagList = element("div", "translation-flags");
      for (const flag of flags) flagList.append(element("span", `flag flag-${flag}`, FLAG_LABELS[flag] || flag));
      side.append(flagList);
    }
    side.append(renderAttributes("System.db 关键字段", source.attributes || {}));
    if (record.candidate_mapping_keys && record.candidate_mapping_keys.length) {
      side.append(renderCandidates("近似汉化键（候选，不自动采用）", record.candidate_mapping_keys, "english_key", "zh_raw"));
    }
    return side;
  }

  function renderWikiSide(record, wiki) {
    const side = element("section", "evidence-side wiki-side");
    const label = element("div", "side-label");
    label.append(document.createTextNode("百科 · 当前快照"));
    label.append(element("span", "side-hint", record.identity && record.identity.method || "无对应"));
    side.append(label);
    const pairs = element("dl", "translation-pair");
    appendPair(pairs, "百科名称", wiki.name, "");
    appendPair(pairs, "百科中文", wiki.zh, "site-value");
    appendPair(pairs, "关系", pageRelationLabel(record), "");
    side.append(pairs);
    if (wiki.image_url) {
      const imageEvidence = element("div", "image-evidence");
      const frame = element("div", "image-frame");
      if (wiki.image_exists) {
        const image = document.createElement("img");
        image.src = localPage(wiki.image_url);
        image.alt = `${wiki.name || "百科实体"} 图片线索`;
        image.loading = "lazy";
        image.decoding = "async";
        frame.append(image);
      } else {
        frame.textContent = "图片缺失";
      }
      const meta = element("div", "image-meta", wiki.visual_status === "image_available_not_reviewed" ? "图片可用 · 尚未人工查看" : "没有可用图片");
      if (wiki.image_exists) appendLink(meta, wiki.image_url, "打开原图");
      else meta.append(element("span", "", `资源路径：${wiki.image_url}`));
      imageEvidence.append(frame, meta);
      side.append(imageEvidence);
    }
    side.append(renderAttributes("百科关键字段", wiki.attributes || {}));
    if (record.candidate_wiki && record.candidate_wiki.length) {
      side.append(renderCandidates("可能的百科页面（待核）", record.candidate_wiki, "name", "zh"));
    }
    if (record.candidate_system_rows && record.candidate_system_rows.length) {
      side.append(renderCandidates("近似 System.db 行（待核）", record.candidate_system_rows, "english_key", "index"));
    }
    return side;
  }

  function appendPair(list, key, value, className) {
    const dt = element("dt", "", key);
    const dd = element("dd", className, valueText(value));
    list.append(dt, dd);
  }

  function renderAttributes(title, attributes) {
    const section = element("div", "attribute-section");
    const heading = element("p", "attribute-title", title);
    section.append(heading);
    const grid = element("dl", "attr-grid");
    const entries = Object.entries(attributes);
    if (!entries.length) grid.append(element("dd", "attribute-empty", "无额外字段"));
    for (const [key, value] of entries) {
      const pair = element("div", "attr-pair");
      pair.append(element("dt", "", key), element("dd", "", valueText(value)));
      grid.append(pair);
    }
    section.append(grid);
    return section;
  }

  function renderCandidates(title, candidates, nameField, valueField) {
    const section = element("div", "candidate-section");
    section.append(element("p", "attribute-title", title));
    const list = element("ul", "candidate-list");
    for (const candidate of candidates) {
      const item = element("li");
      const left = candidate[nameField] ?? candidate.english_key ?? candidate.name ?? "候选";
      const right = candidate[valueField] ?? "";
      item.append(document.createTextNode(valueText(left)));
      if (right !== "") item.append(document.createTextNode(` · ${valueText(right)}`));
      const page = candidate.page_url || candidate.page_url_candidate;
      if (page) appendLink(item, page, candidate.page_exists ? "打开页面" : page, "candidate-link");
      list.append(item);
    }
    section.append(list);
    return section;
  }

  function renderRecordFooter(record, review) {
    const footer = element("footer", "record-footer");
    const links = element("div", "record-links");
    const wiki = record.wiki || {};
    if (wiki.page_url) appendLink(links, wiki.page_url, "打开百科详情");
    else if (wiki.page_url_candidate) links.append(element("span", "link-muted", `候选路径：${wiki.page_url_candidate}${wiki.page_exists ? "" : "（静态页缺失）"}`));
    for (const path of wiki.candidate_page_urls || []) appendLink(links, path, `候选页 ${path}`);
    const auditUrl = new URL("zircon-audit.html", window.location.href);
    auditUrl.searchParams.set("record", record.record_id);
    const auditLink = element("a", "", "定位此记录");
    auditLink.href = auditUrl.href;
    links.append(auditLink);
    if (record.identity && record.identity.confidence) links.append(element("span", "method-note", `匹配置信度：${record.identity.confidence}`));
    footer.append(links);

    const controls = element("div", "review-controls");
    const select = element("select", "review-select");
    select.setAttribute("aria-label", `人工审校状态：${record.record_id}`);
    select.dataset.reviewStatus = "";
    select.dataset.recordId = record.record_id;
    for (const [value, label] of Object.entries(REVIEW_LABELS)) {
      const option = element("option", "", label);
      option.value = value;
      select.append(option);
    }
    select.value = review.status;
    const note = document.createElement("textarea");
    note.className = "review-note";
    note.rows = 1;
    note.maxLength = 500;
    note.placeholder = "人工依据 / 问题说明（最多 500 字）";
    note.setAttribute("aria-label", `人工审校依据：${record.record_id}`);
    note.dataset.reviewNote = "";
    note.dataset.recordId = record.record_id;
    note.value = review.note;
    const feedback = element("span", "review-feedback", review.status === "not_reviewed" ? "仅本浏览器保存" : "本地审校记录");
    feedback.dataset.reviewFeedback = record.record_id;
    controls.append(select, note, feedback);
    footer.append(controls);
    return footer;
  }

  function pageRelationLabel(record) {
    const wiki = record.wiki || {};
    if (record.kind === "wiki_entity") return "百科记录未链接";
    if (record.kind === "wiki_supplemental") return "地图补充记录未链接";
    if (record.identity && record.identity.status === "matched") return wiki.page_exists ? "页面路径已匹配" : "身份匹配，静态页缺失";
    if (wiki.page_route_ambiguous) return "页面路径重名";
    return "候选或尚未对应";
  }

  function renderPaginationMessage() {
    const message = byId("review-message");
    if (!message.textContent) flash(`本地审校：${Object.keys(state.reviews).length} 条 · 未有服务器端共享存储`, "");
  }

  function bindFilters() {
    ["search", "category", "status", "kind", "review", "page-size"].forEach((id) => {
      byId(id).addEventListener(id === "search" ? "input" : "change", () => { state.page = 0; render(); });
    });
    byId("clear-filters").addEventListener("click", () => {
      byId("search").value = "";
      byId("category").value = "all";
      byId("status").value = "all";
      byId("kind").value = "all";
      byId("review").value = "all";
      state.page = 0;
      render();
    });
    byId("category-stats").addEventListener("click", (event) => {
      const button = event.target.closest("[data-category-choice]");
      if (!button) return;
      byId("category").value = button.dataset.categoryChoice;
      state.page = 0;
      render();
      byId("results").scrollIntoView({ block: "start" });
    });
    byId("results").addEventListener("change", (event) => {
      if (!event.target.matches("[data-review-status]")) return;
      const select = event.target;
      const recordId = select.dataset.recordId;
      const note = byIdForRecord("[data-review-note]", recordId);
      const previous = reviewFor(recordId).status;
      if (select.value !== "not_reviewed" && !note.value.trim()) {
        select.value = previous;
        feedbackFor(recordId, "先填写审校依据，再保存人工结论。", "error");
        note.focus();
        return;
      }
      const saved = storeReview(recordId, select.value, note.value);
      renderCategoryStats();
      state.page = 0;
      render();
      feedbackFor(recordId, saved ? "已保存在本浏览器" : "存储失败；请导出审校 JSON。", saved ? "saved" : "error");
    });
    byId("results").addEventListener("input", (event) => {
      if (!event.target.matches("[data-review-note]")) return;
      const note = event.target;
      const recordId = note.dataset.recordId;
      const select = byIdForRecord("[data-review-status]", recordId);
      const previousStatus = select.value;
      if (!note.value.trim() && select.value !== "not_reviewed") {
        select.value = "not_reviewed";
        feedbackFor(recordId, "依据已清空，人工状态恢复为尚未审校。", "error");
      }
      const statusChanged = select.value !== previousStatus;
      const saved = storeReview(recordId, select.value, note.value);
      if (statusChanged) {
        renderCategoryStats();
        state.page = 0;
        render();
      }
      feedbackFor(
        recordId,
        saved ? (statusChanged ? "依据已清空，人工状态恢复为尚未审校。" : "已保存在本浏览器") : "存储失败；请导出审校 JSON。",
        saved ? "saved" : "error",
      );
    });
    byId("export-reviews").addEventListener("click", exportReviews);
    byId("import-reviews").addEventListener("change", importReviews);
  }

  function byIdForRecord(selector, recordId) {
    return Array.from(byId("results").querySelectorAll(selector)).find((node) => node.dataset.recordId === recordId);
  }

  function feedbackFor(recordId, message, stateName) {
    const feedback = Array.from(byId("results").querySelectorAll("[data-review-feedback]"))
      .find((node) => node.dataset.reviewFeedback === recordId);
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle("saved", stateName === "saved");
    feedback.classList.toggle("error", stateName === "error");
  }


  function exportReviews() {
    const output = {
      format: REVIEW_FORMAT,
      version: 1,
      dataset_fingerprint: state.audit.build_fingerprint,
      exported_at: new Date().toISOString(),
      reviews: Object.fromEntries(Object.entries(state.reviews).sort(([left], [right]) => left.localeCompare(right))),
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(output, null, 2)], { type: "application/json" }));
    const link = element("a");
    link.href = url;
    link.download = `zircon-name-reviews-${String(state.audit.build_fingerprint).slice(0, 12)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    flash(`已导出 ${Object.keys(state.reviews).length} 条本地审校记录。`, "saved");
  }

  async function importReviews(event) {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      if (parsed.format !== REVIEW_FORMAT || parsed.version !== 1) throw new Error("文件格式或版本不支持。");
      if (parsed.dataset_fingerprint !== state.audit.build_fingerprint) throw new Error("该审校文件对应另一份数据快照；拒绝合并。");
      if (!parsed.reviews || typeof parsed.reviews !== "object" || Array.isArray(parsed.reviews)) throw new Error("找不到审校记录对象。");
      const knownIds = new Set(state.records.map((record) => record.record_id));
      const accepted = {};
      let ignored = 0;
      for (const [recordId, review] of Object.entries(parsed.reviews)) {
        if (!knownIds.has(recordId) || !review || !REVIEW_LABELS[review.status]) { ignored += 1; continue; }
        const note = String(review.note || "").trim().slice(0, 500);
        if (review.status !== "not_reviewed" && !note) { ignored += 1; continue; }
        accepted[recordId] = { status: review.status, note, updated_at: String(review.updated_at || parsed.exported_at || "") };
      }
      const previousReviews = state.reviews;
      state.reviews = accepted;
      try {
        window.localStorage.setItem(state.reviewKey, JSON.stringify(state.reviews));
      } catch (error) {
        state.reviews = previousReviews;
        throw error;
      }
      renderCategoryStats();
      state.page = 0;
      render();
      flash(`已导入 ${Object.keys(accepted).length} 条；忽略 ${ignored} 条无效记录。`, "saved");
    } catch (error) {
      flash(`导入失败：${error.message || "无法读取文件"}`, "error");
    }
  }

  async function load() {
    try {
      const response = await fetch(DATA_URL, { cache: "no-cache" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.audit = await response.json();
      if (!Array.isArray(state.audit.records)) throw new Error("审计 JSON 缺少逐条 records。");
      state.records = state.audit.records;
      loadReviews();
      renderProvenance();
      renderCategoryStats();
      fillStatusFilter();
      buildSearchCache();
      bindFilters();
      render();
      renderPaginationMessage();
      const recordId = new URLSearchParams(window.location.search).get("record");
      if (recordId) {
        const record = state.records.find((item) => item.record_id === recordId);
        if (record) {
          byId("category").value = record.category;
          byId("search").value = recordId;
          byId("kind").value = record.kind;
          state.page = 0;
          render();
          const target = Array.from(byId("results").querySelectorAll(".record-card"))
            .find((card) => card.dataset.recordId === recordId);
          if (target) target.scrollIntoView({ block: "center" });
        }
      }
    } catch (error) {
      const host = byId("results");
      host.setAttribute("aria-busy", "false");
      host.replaceChildren();
      const box = element("div", "error-state");
      box.append(element("strong", "", "审计数据未能载入"), element("p", "", `${error.message || "读取失败"} · 检查 data/zircon_name_audit.json 是否已部署。`));
      host.append(box);
      byId("provenance").textContent = "证据快照不可用";
      byId("result-count").textContent = "0 条";
    }
  }

  load();
})();
