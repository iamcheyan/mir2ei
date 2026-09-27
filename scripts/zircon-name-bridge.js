(() => {
  "use strict";

  const script = document.currentScript || document.querySelector("[data-zircon-name-bridge]");
  const base = script && script.dataset.siteBase ? script.dataset.siteBase : "/";
  const baseWithoutTrailingSlash = base === "/" ? "" : base.replace(/\/$/, "");
  const listPages = new Set(["/items.html", "/monsters.html", "/npcs.html", "/skills.html", "/maps.html"]);
  const detailRoute = /^\/(item|monster|npc|skill|map)\/.+\.html$/;

  function routeFor(pathname) {
    let route = pathname;
    if (baseWithoutTrailingSlash && (route === baseWithoutTrailingSlash || route.startsWith(baseWithoutTrailingSlash + "/"))) {
      route = route.slice(baseWithoutTrailingSlash.length) || "/";
    }
    return route.startsWith("/") ? route : `/${route}`;
  }

  function publicUrl(path) {
    return `${base}${String(path || "").replace(/^\/+/, "")}`;
  }

  function addText(parent, tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = String(text || "");
    parent.append(node);
    return node;
  }

  function auditUrl(recordId) {
    const url = new URL(publicUrl("zircon-audit.html"), window.location.origin);
    if (recordId) url.searchParams.set("record", recordId);
    return url.href;
  }

  function translationSummary(records) {
    const unique = (field) => [...new Set(records.map((record) => record[field]).filter(Boolean))];
    const keys = unique("english_key");
    const zh = unique("zh_raw");
    const siteZh = unique("wiki_zh");
    if (records.length > 1) {
      return `候选 ${records.length} 条${zh.length ? ` · ZH ${zh.join(" / ")}` : ""}`;
    }
    if (!zh.length) return records[0].kind === "wiki_entity" ? "百科未关联 Zircon" : records[0].status_label;
    if (siteZh.length && siteZh[0] !== zh[0]) return `ZH ${zh[0]} · 百科 ${siteZh[0]}`;
    return `ZH ${zh[0]}`;
  }

  function makeAuditLink(record, label) {
    const link = document.createElement("a");
    link.className = "zircon-bridge-link";
    link.href = auditUrl(record.record_id);
    link.textContent = label;
    link.setAttribute("aria-label", `在名称审校簿查看 ${record.english_key || record.wiki_name || record.record_id}`);
    return link;
  }

  function decorateListLinks(indexByPath) {
    const anchors = document.querySelectorAll("a[href]");
    for (const anchor of anchors) {
      if (anchor.closest("header, footer, .pager, .pagination") || anchor.hasAttribute("data-zircon-audit-nav")) continue;
      let route;
      try { route = routeFor(new URL(anchor.href, window.location.href).pathname); } catch { continue; }
      const records = indexByPath.get(route);
      if (!records || anchor.dataset.zirconCrosswalk) continue;
      anchor.dataset.zirconCrosswalk = "true";
      const badge = document.createElement("span");
      badge.className = "zircon-bridge-badge";
      const copy = document.createElement("span");
      copy.className = "zircon-bridge-copy";
      copy.textContent = translationSummary(records);
      const link = makeAuditLink(records[0], records.length > 1 ? `核对 ${records.length} 条` : records[0].status_label || "审校");
      badge.append(copy, link);
      anchor.insertAdjacentElement("afterend", badge);
    }
  }

  function decorateDetail(records) {
    const main = document.querySelector("main");
    if (!main || main.querySelector(":scope > .zircon-crosswalk")) return;
    const banner = document.createElement("aside");
    banner.className = "zircon-crosswalk";
    const heading = document.createElement("div");
    heading.className = "zircon-crosswalk-heading";
    addText(heading, "span", "zircon-crosswalk-mark", "Z / EI");
    addText(heading, "strong", "", records.length > 1 ? `${records.length} 条候选关联` : "名称交叉证据");
    const open = document.createElement("a");
    open.className = "zircon-crosswalk-open";
    open.href = auditUrl(records[0].record_id);
    open.textContent = "打开审校簿 →";
    heading.append(open);
    banner.append(heading);
    const rows = document.createElement("div");
    rows.className = "zircon-crosswalk-rows";
    for (const record of records.slice(0, 6)) {
      const row = document.createElement("div");
      row.className = "zircon-crosswalk-row";
      const sourceIndex = record.source_index === null || record.source_index === undefined ? "无稳定 Index" : `Index ${record.source_index}`;
      addText(row, "span", "zircon-crosswalk-id", sourceIndex);
      const name = record.english_key || record.wiki_name || "未链接记录";
      addText(row, "span", "zircon-crosswalk-name", name);
      const translation = translationSummary([record]);
      addText(row, "span", "zircon-crosswalk-translation", translation);
      const status = document.createElement("span");
      status.className = `zircon-crosswalk-status status-${record.status}`;
      status.textContent = record.status_label || record.status;
      row.append(status);
      row.append(makeAuditLink(record, "查看证据"));
      rows.append(row);
    }
    if (records.length > 6) addText(rows, "p", "zircon-crosswalk-more", `另有 ${records.length - 6} 条候选关联；请在审校簿筛选查看。`);
    banner.append(rows);
    main.insertBefore(banner, main.firstChild);
  }

  async function loadIndex() {
    const route = routeFor(window.location.pathname);
    const isList = listPages.has(route);
    if (!isList && !detailRoute.test(route)) return;
    try {
      const indexUrl = new URL(publicUrl("data/zircon_name_index.json"), window.location.origin);
      const build = script ? new URL(script.src).searchParams.get("build") : null;
      if (build) indexUrl.searchParams.set("v", build);
      const response = await fetch(indexUrl.href, { cache: "force-cache" });
      if (!response.ok) return;
      const entries = await response.json();
      const indexByPath = new Map();
      for (const entry of entries) {
        const path = entry.page_url;
        if (!path) continue;
        if (!indexByPath.has(path)) indexByPath.set(path, []);
        indexByPath.get(path).push(entry);
      }
      if (isList) decorateListLinks(indexByPath);
      if (detailRoute.test(route)) decorateDetail(indexByPath.get(route) || []);
    } catch (error) {
      console.warn("Zircon cross-reference index unavailable", error);
    }
  }

  loadIndex();
})();
