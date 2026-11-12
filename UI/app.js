/**
 * Website Scraper Studio — Full-Width Dashboard Application
 * Handles full-width responsive navigation, SSE telemetry, crawling lifecycle,
 * single-URL inspector, catalog browsing, and disk output management.
 */

(function () {
  "use strict";

  // --- Global Application State ---
  const state = {
    isRunning: false,
    elapsedTimer: null,
    crawlStartTime: null,
    allLogs: [],
    currentLogFilter: "ALL",
    savedPages: [],
    eventSource: null,
    activeView: "viewCrawlSetup",
    inspectFormat: "markdown",
    inspectDocument: null,
    inspectHasRun: false,
    inspectTimer: null,
    inspectController: null,
    inspectSeq: 0,
    velocityTimer: null,
    velocitySamples: [],
    lastVelocityTick: null,
    latestCrawled: 0,
    sessionAvgRate: 0,
    peakRate: 0,
    catalogRenderLimit: 100,
    isContainer: false,
    defaultOutputDir: "./output",
    discoveredMedia: [],
    mediaFilter: "",
    currentJobId: "",
  };

  // --- DOM Element References ---
  // Shell & Layout
  const appShell = document.getElementById("appShell");
  const sidebar = document.getElementById("sidebar");
  const mobileMenuBtn = document.getElementById("mobileMenuBtn");
  const sidebarScrim = document.getElementById("sidebarScrim");
  const navLinks = document.querySelectorAll(".nav-link");
  const views = document.querySelectorAll(".content-view");
  const topbarViewTitle = document.getElementById("topbarViewTitle");
  const topbarViewSubtitle = document.getElementById("topbarViewSubtitle");
  const breadcrumbCategory = document.getElementById("breadcrumbCategory");
  const sidebarPulse = document.getElementById("sidebarPulse");
  const sidebarStatusText = document.getElementById("sidebarStatusText");
  const sidebarOutputDir = document.getElementById("sidebarOutputDir");
  const sidebarOutputLabel = document.getElementById("sidebarOutputLabel");
  const navLogBadge = document.getElementById("navLogBadge");
  const navPageBadge = document.getElementById("navPageBadge");

  // Topbar Actions
  const statusPill = document.getElementById("statusPill");
  const statusText = document.getElementById("statusText");
  const topbarTicker = document.getElementById("topbarTicker");
  const topbarTickerText = document.getElementById("topbarTickerText");
  const globalStartBtn = document.getElementById("globalStartBtn");
  const globalStopBtn = document.getElementById("globalStopBtn");
  const themeToggleBtn = document.getElementById("themeToggleBtn");
  const themeIconSun = document.getElementById("themeIconSun");
  const themeIconMoon = document.getElementById("themeIconMoon");

  // Crawl Setup Form
  const crawlerForm = document.getElementById("crawlerForm");
  const urlInput = document.getElementById("urlInput");
  const depthInput = document.getElementById("depthInput");
  const depthDisplay = document.getElementById("depthDisplay");
  const depthHint = document.getElementById("depthHint");
  const maxPagesInput = document.getElementById("maxPagesInput");
  const concurrencyInput = document.getElementById("concurrencyInput");
  const delayInput = document.getElementById("delayInput");
  const sameDomainInput = document.getElementById("sameDomainInput");
  const respectRobotsInput = document.getElementById("respectRobotsInput");
  const sitemapInput = document.getElementById("sitemapInput");
  const sitemapUrlInput = document.getElementById("sitemapUrlInput");
  const renderJsInput = document.getElementById("renderJsInput");
  const dryRunInput = document.getElementById("dryRunInput");
  const impersonateInput = document.getElementById("impersonateInput");
  const proxyInput = document.getElementById("proxyInput");
  const webhookUrlInput = document.getElementById("webhookUrlInput");
  const incrementalInput = document.getElementById("incrementalInput");
  const checkpointInput = document.getElementById("checkpointInput");
  const adaptiveRateInput = document.getElementById("adaptiveRateInput");
  const maxRetriesInput = document.getElementById("maxRetriesInput");
  const resumeJobIdInput = document.getElementById("resumeJobIdInput");
  const dlqInput = document.getElementById("dlqInput");
  const dlqCard = document.getElementById("dlqCard");
  const refreshDlqBtn = document.getElementById("refreshDlqBtn");
  const retryDlqBtn = document.getElementById("retryDlqBtn");
  const dlqList = document.getElementById("dlqList");
  const dlqStatusText = document.getElementById("dlqStatusText");
  const outputDirInput = document.getElementById("outputDirInput");
  const outputDirHint = document.getElementById("outputDirHint");
  const browseDirBtn = document.getElementById("browseDirBtn");
  const submitCrawlBtn = document.getElementById("submitCrawlBtn");
  const resetFormBtn = document.getElementById("resetFormBtn");
  const setupSummary = document.getElementById("setupSummary");
  const loadSampleUrlsBtn = document.getElementById("loadSampleUrlsBtn");

  // Extraction Options
  const formatCards = document.querySelectorAll(".format-card");
  const formatInput = document.getElementById("formatInput");
  const selectorInput = document.getElementById("selectorInput");
  const excludeSelectorInput = document.getElementById("excludeSelectorInput");
  const schemaInput = document.getElementById("schemaInput");
  const chunkSizeInput = document.getElementById("chunkSizeInput");
  const chunkOverlapInput = document.getElementById("chunkOverlapInput");

  // URL Filters
  const includePatternInput = document.getElementById("includePatternInput");
  const excludePatternInput = document.getElementById("excludePatternInput");
  const testUrlInput = document.getElementById("testUrlInput");
  const evalPatternBtn = document.getElementById("evalPatternBtn");
  const testResultBox = document.getElementById("testResultBox");

  // Single URL Inspector
  const inspectorUrl = document.getElementById("inspectorUrl");
  const inspectScrapeBtn = document.getElementById("inspectScrapeBtn");
  const inspectorJsToggle = document.getElementById("inspectorJsToggle");
  const inspectorMetaBar = document.getElementById("inspectorMetaBar");
  const inspectorStatusTag = document.getElementById("inspectorStatusTag");
  const inspectorTime = document.getElementById("inspectorTime");
  const inspectorSize = document.getElementById("inspectorSize");
  const inspectorPreviewBlock = document.getElementById("inspectorPreviewBlock");
  const inspectorCopyBtn = document.getElementById("inspectorCopyBtn");
  const inspectFormatBtns = document.querySelectorAll("[data-inspect-format]");
  const inspectorSelectorInput = document.getElementById("inspectorSelectorInput");
  const inspectorExcludeSelectorInput = document.getElementById("inspectorExcludeSelectorInput");
  const inspectorSchemaInput = document.getElementById("inspectorSchemaInput");
  const inspectorLiveToggle = document.getElementById("inspectorLiveToggle");
  const inspectorSelectorStatus = document.getElementById("inspectorSelectorStatus");
  const inspectorWordCount = document.getElementById("inspectorWordCount");
  const inspectorUseSetupBtn = document.getElementById("inspectorUseSetupBtn");

  // Live Monitor & Console
  const monitorCrawledVal = document.getElementById("monitorCrawledVal");
  const monitorSavedVal = document.getElementById("monitorSavedVal");
  const monitorSkippedVal = document.getElementById("monitorSkippedVal");
  const monitorElapsedVal = document.getElementById("monitorElapsedVal");
  const monitorVelocityCard = document.querySelector(".telemetry-card-velocity");
  const monitorRateVal = document.getElementById("monitorRateVal");
  const monitorRatePeakVal = document.getElementById("monitorRatePeakVal");
  const monitorRateAvgVal = document.getElementById("monitorRateAvgVal");
  const monitorRateSparkline = document.getElementById("monitorRateSparkline");
  const monitorDepthTag = document.getElementById("monitorDepthTag");
  const monitorUrlText = document.getElementById("monitorUrlText");
  const terminalConsole = document.getElementById("terminalConsole");
  const terminalCounter = document.getElementById("terminalCounter");
  const terminalAutoScroll = document.getElementById("terminalAutoScroll");
  const terminalClearBtn = document.getElementById("terminalClearBtn");
  const monitorResetBtn = document.getElementById("monitorResetBtn");
  const levelPills = document.querySelectorAll(".level-pill");

  // Saved Pages Catalog
  const catalogTableBody = document.getElementById("catalogTableBody");
  const catalogSearchInput = document.getElementById("catalogSearchInput");
  const catalogTotalCount = document.getElementById("catalogTotalCount");
  const refreshCatalogBtn = document.getElementById("refreshCatalogBtn");
  const clearCatalogBtn = document.getElementById("clearCatalogBtn");
  const downloadZipCatalogBtn = document.getElementById("downloadZipCatalogBtn");
  const downloadFormatCatalog = document.getElementById("downloadFormatCatalog");

  // Output Storage
  const outputFolderLabel = document.getElementById("outputFolderLabel");
  const outputTotalFilesVal = document.getElementById("outputTotalFilesVal");
  const outputTotalSizeVal = document.getElementById("outputTotalSizeVal");
  const outputManifestVal = document.getElementById("outputManifestVal");
  const outputFileList = document.getElementById("outputFileList");
  const refreshOutputListBtn = document.getElementById("refreshOutputListBtn");
  const downloadZipBtn = document.getElementById("downloadZipBtn");
  const downloadFormatOutput = document.getElementById("downloadFormatOutput");
  const clearOutputBtn = document.getElementById("clearOutputBtn");

  // Drawer Preview
  const drawerOverlay = document.getElementById("drawerOverlay");
  const previewDrawer = document.getElementById("previewDrawer");
  const closeDrawerBtn = document.getElementById("closeDrawerBtn");
  const drawerDepth = document.getElementById("drawerDepth");
  const drawerTitle = document.getElementById("drawerTitle");
  const drawerUrl = document.getElementById("drawerUrl");
  const drawerFileName = document.getElementById("drawerFileName");
  const drawerFileSize = document.getElementById("drawerFileSize");
  const drawerLineCount = document.getElementById("drawerLineCount");
  const drawerCopyBtn = document.getElementById("drawerCopyBtn");
  const drawerCopyText = document.getElementById("drawerCopyText");
  const drawerContent = document.getElementById("drawerContent");

  // Toast Container
  const toastContainer = document.getElementById("toastContainer");

  // Presets
  const applyRecipeBtns = document.querySelectorAll(".apply-recipe-btn");

  // --- Depth Descriptions ---
  const depthDescriptions = {
    0: "Depth 0 (Seeds only): Crawls and saves seed pages without traversing links.",
    1: "Depth 1: Crawls seed pages and all direct links discovered on those pages.",
    2: "Depth 2: Deep crawl — seeds, direct links, and second-level pages.",
    3: "Depth 3: Broad crawl traversing through multi-tier hierarchies.",
    4: "Depth 4: Very deep crawl across extensive site sections.",
    5: "Depth 5: Maximum allowed crawl depth limit.",
  };

  // =========================================================================
  // Theme Management
  // =========================================================================
  function initTheme() {
    // Terminal Precision is dark-first. Respect an explicit user choice, but
    // default to the instrument-panel dark theme on first load.
    const saved = localStorage.getItem("scrapper_theme");
    const theme = saved || "dark";
    setTheme(theme);
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("scrapper_theme", theme);
    if (theme === "dark") {
      themeIconSun.classList.add("hidden");
      themeIconMoon.classList.remove("hidden");
      if (themeToggleBtn) themeToggleBtn.setAttribute("aria-label", "Switch to light theme");
    } else {
      themeIconSun.classList.remove("hidden");
      themeIconMoon.classList.add("hidden");
      if (themeToggleBtn) themeToggleBtn.setAttribute("aria-label", "Switch to dark theme");
    }
  }

  themeToggleBtn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    setTheme(current === "dark" ? "light" : "dark");
  });

  // =========================================================================
  // Toast Notifications
  // =========================================================================
  function showToast(message, type = "info", duration = 3500) {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(8px) scale(0.96)";
      setTimeout(() => toast.remove(), 220);
    }, duration);
  }

  // =========================================================================
  // Navigation & View Switching
  // =========================================================================
  function switchView(viewId, pushHistory = true) {
    const targetLink = document.querySelector(`.nav-link[data-view="${viewId}"]`);
    if (!targetLink) return;

    state.activeView = viewId;

    // Update active nav links
    navLinks.forEach((link) => link.classList.remove("active"));
    targetLink.classList.add("active");

    // Update views
    views.forEach((view) => view.classList.remove("active"));
    const activeViewEl = document.getElementById(viewId);
    if (activeViewEl) activeViewEl.classList.add("active");

    // Update topbar breadcrumbs and header
    const title = targetLink.getAttribute("data-title") || "Web Scraper Studio";
    const category = targetLink.getAttribute("data-category") || "Crawler Engine";
    const subtitle = targetLink.getAttribute("data-subtitle") || "";

    topbarViewTitle.textContent = title;
    breadcrumbCategory.textContent = category;
    topbarViewSubtitle.textContent = subtitle;
    document.title = `${title} · Web Scraper Studio`;

    // View-specific initialization
    if (viewId === "viewPages") {
      fetchSavedPages();
    } else if (viewId === "viewOutput") {
      fetchOutputDirectory();
    } else if (viewId === "viewMonitor" && terminalAutoScroll.checked) {
      terminalConsole.scrollTop = terminalConsole.scrollHeight;
    }

    if (window.scrollX !== 0 || window.scrollY !== 0) {
      window.scrollTo(0, 0);
    }

    if (pushHistory) {
      history.replaceState(null, "", `#${viewId}`);
    }

    // Close mobile drawer if open
    closeMobileSidebar();
  }

  navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      const viewId = link.getAttribute("data-view");
      if (viewId) switchView(viewId);
    });
  });

  // Sidebar Rail Collapse / Expand
  function initSidebarState() {
    const isCollapsed = localStorage.getItem("scrapper_sidebar_collapsed") === "true";
    if (isCollapsed && window.innerWidth > 1024) {
      appShell.classList.add("sidebar-collapsed");
    }
    if (mobileMenuBtn && window.innerWidth > 1024) {
      mobileMenuBtn.setAttribute("aria-expanded", String(!appShell.classList.contains("sidebar-collapsed")));
    }
  }

  // Single navigation toggle: collapses the rail on desktop and opens the drawer on small screens.
  function openMobileSidebar() {
    sidebar.classList.add("mobile-open");
    sidebar.removeAttribute("inert");
    sidebarScrim.hidden = false;
    if (mobileMenuBtn) mobileMenuBtn.setAttribute("aria-expanded", "true");
    const firstLink = sidebar.querySelector(".nav-link");
    if (firstLink) firstLink.focus();
  }

  function closeMobileSidebar() {
    sidebar.classList.remove("mobile-open");
    sidebarScrim.hidden = true;
    if (mobileMenuBtn && window.innerWidth <= 1024) {
      mobileMenuBtn.setAttribute("aria-expanded", "false");
    }
  }

  mobileMenuBtn.addEventListener("click", () => {
    if (window.innerWidth <= 1024) {
      if (sidebar.classList.contains("mobile-open")) closeMobileSidebar();
      else openMobileSidebar();
      return;
    }
    appShell.classList.toggle("sidebar-collapsed");
    const collapsed = appShell.classList.contains("sidebar-collapsed");
    localStorage.setItem("scrapper_sidebar_collapsed", String(collapsed));
    mobileMenuBtn.setAttribute("aria-expanded", String(!collapsed));
  });
  sidebarScrim.addEventListener("click", closeMobileSidebar);

  // Responsive layout window resize handler
  window.addEventListener("resize", () => {
    if (window.innerWidth > 1024) {
      closeMobileSidebar();
      const isCollapsed = localStorage.getItem("scrapper_sidebar_collapsed") === "true";
      if (isCollapsed) {
        appShell.classList.add("sidebar-collapsed");
      } else {
        appShell.classList.remove("sidebar-collapsed");
      }
      mobileMenuBtn.setAttribute("aria-expanded", String(!isCollapsed));
    } else {
      appShell.classList.remove("sidebar-collapsed");
    }
  });

  // =========================================================================
  // Crawl Setup Form Controls
  // =========================================================================
  // Depth slider interaction
  depthInput.addEventListener("input", (e) => {
    const val = parseInt(e.target.value, 10);
    depthInput.setAttribute("aria-valuenow", String(val));
    depthInput.setAttribute("aria-valuetext", depthDescriptions[val] || `Depth ${val}`);
    depthDisplay.textContent = String(val);
    depthHint.textContent = depthDescriptions[val] || `Depth level ${val}`;
    updateSetupSummary();
  });

  // Preset sample URLs
  document.querySelectorAll(".sample-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const url = chip.getAttribute("data-url");
      const current = urlInput.value.trim();
      if (!current) {
        urlInput.value = url;
      } else if (!current.includes(url)) {
        urlInput.value = current + "\n" + url;
      }
      urlInput.focus();
      updateSetupSummary();
    });
  });

  loadSampleUrlsBtn.addEventListener("click", () => {
    urlInput.value = "https://books.toscrape.com\nhttps://quotes.toscrape.com";
    showToast("Sample targets added to seeds", "info");
    updateSetupSummary();
  });

  // Max pages pills
  document.querySelectorAll(".preset-pill[data-pages]").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".preset-pill[data-pages]").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      maxPagesInput.value = pill.getAttribute("data-pages");
      updateSetupSummary();
    });
  });

  maxPagesInput.addEventListener("input", (e) => {
    const val = e.target.value;
    document.querySelectorAll(".preset-pill[data-pages]").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-pages") === val);
    });
    updateSetupSummary();
  });

  // Concurrency pills
  document.querySelectorAll(".preset-pill[data-concurrency]").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".preset-pill[data-concurrency]").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      if (concurrencyInput) concurrencyInput.value = pill.getAttribute("data-concurrency");
      updateSetupSummary();
    });
  });

  if (concurrencyInput) {
    concurrencyInput.addEventListener("input", (e) => {
      const val = e.target.value;
      document.querySelectorAll(".preset-pill[data-concurrency]").forEach((p) => {
        p.classList.toggle("active", p.getAttribute("data-concurrency") === val);
      });
      updateSetupSummary();
    });
  }

  // Delay pills
  document.querySelectorAll(".preset-pill[data-delay]").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".preset-pill[data-delay]").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      if (delayInput) delayInput.value = pill.getAttribute("data-delay");
      updateSetupSummary();
    });
  });

  if (delayInput) {
    delayInput.addEventListener("input", (e) => {
      const val = e.target.value;
      document.querySelectorAll(".preset-pill[data-delay]").forEach((p) => {
        p.classList.toggle("active", p.getAttribute("data-delay") === val);
      });
      updateSetupSummary();
    });
  }

  function updateSetupSummary() {
    const depth = depthInput.value;
    const maxPages = maxPagesInput.value;
    const concurrency = concurrencyInput ? concurrencyInput.value : 5;
    const delay = delayInput ? delayInput.value : 0.2;
    const sitemapActive = sitemapInput && sitemapInput.checked;
    const rawUrls = urlInput.value.trim();
    const count = rawUrls ? rawUrls.split(/[\n,]+/).filter((x) => x.trim()).length : 0;
    const domainMsg = sameDomainInput.checked ? "same domain" : "any domain";
    const format = formatInput.value.toUpperCase();
    const flags = [];
    if (sitemapActive || (sitemapUrlInput && sitemapUrlInput.value.trim())) flags.push("Sitemap");
    if (renderJsInput && renderJsInput.checked) flags.push("JS render");
    if (dryRunInput && dryRunInput.checked) flags.push("Dry run");
    if (incrementalInput && incrementalInput.checked) flags.push("Incremental");
    if (checkpointInput && checkpointInput.checked) flags.push("Checkpointed");
    if (dlqInput && dlqInput.checked) flags.push("DLQ tracking");
    const flagText = flags.length ? ` · ${flags.join(" · ")}` : "";
    const schemaField = parseSchemaField(schemaInput);
    let schemaText = "";
    if (schemaField.error) {
      schemaText = " · invalid schema JSON";
    } else if (schemaField.value) {
      const schemaCount = Object.keys(schemaField.value).length;
      if (schemaCount) schemaText = ` · ${schemaCount} schema field(s)`;
    }
    setupSummary.textContent = `${count} seed(s) · Depth ${depth} · Max ${maxPages} pages · ${concurrency} workers · ${delay}s delay${flagText} · ${domainMsg} · ${format}${schemaText}`;
  }

  urlInput.addEventListener("input", updateSetupSummary);
  sameDomainInput.addEventListener("change", updateSetupSummary);
  if (sitemapInput) sitemapInput.addEventListener("change", updateSetupSummary);
  if (sitemapUrlInput) sitemapUrlInput.addEventListener("input", updateSetupSummary);
  if (renderJsInput) renderJsInput.addEventListener("change", updateSetupSummary);
  if (dryRunInput) dryRunInput.addEventListener("change", updateSetupSummary);
  if (incrementalInput) incrementalInput.addEventListener("change", updateSetupSummary);
  if (checkpointInput) checkpointInput.addEventListener("change", updateSetupSummary);
  if (schemaInput) schemaInput.addEventListener("input", updateSetupSummary);

  function updateDlqVisibility() {
    const isEnabled = dlqInput ? dlqInput.checked : false;
    if (dlqCard) {
      dlqCard.style.display = isEnabled ? "" : "none";
    }
    if (isEnabled && state.currentJobId) {
      refreshFailures(state.currentJobId);
    }
  }

  if (dlqInput) {
    dlqInput.addEventListener("change", () => {
      updateDlqVisibility();
      updateSetupSummary();
    });
  }

  // Format Selection Cards
  formatCards.forEach((card) => {
    card.addEventListener("click", () => {
      formatCards.forEach((c) => c.classList.remove("active"));
      card.classList.add("active");
      const format = card.getAttribute("data-format");
      formatInput.value = format;
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
      updateSetupSummary();
      showToast(`Output format set to .${format.toUpperCase()}`, "info", 1800);
    });
  });

  // Preset Tags (URL Filters)
  document.querySelectorAll(".preset-tag").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-target");
      const pattern = btn.getAttribute("data-pattern");
      const input = document.getElementById(targetId);
      if (!input) return;

      const current = input.value.trim();
      if (!current) {
        input.value = pattern;
      } else if (!current.includes(pattern)) {
        input.value = current + ", " + pattern;
      }
      input.focus();
      showToast(`Added pattern: ${pattern}`, "info", 1500);
    });
  });

  // Native Folder Picker
  browseDirBtn.addEventListener("click", async () => {
    if (state.isContainer) {
      const containerPath = state.defaultOutputDir || "./output";
      setSelectedOutputDir(containerPath, "Docker volume");
      showToast(
        "Running in Docker: files are saved to './output', which is mounted to the 'output' folder on your computer. Use Download ZIP to export them.",
        "info",
        6500
      );
      fetchOutputDirectory();
      return;
    }

    try {
      browseDirBtn.disabled = true;
      browseDirBtn.innerHTML = `<span>Browsing...</span>`;
      const resp = await fetch("/api/system/pick-folder", { method: "POST" });
      if (!resp.ok) {
        let errMsg = `HTTP ${resp.status}`;
        try {
          const errJson = await resp.json();
          if (errJson.error) errMsg = errJson.error;
        } catch (_) {}
        throw new Error(errMsg);
      }
      const data = await resp.json();

      if (data.canceled) {
        // User closed picker dialog without selecting
        return;
      }

      if (data.is_cloud || data.container) {
        // Docker/cloud: the output folder is controlled by the mounted volume.
        state.isContainer = true;
        const containerPath = data.path || state.defaultOutputDir || "./output";
        setSelectedOutputDir(containerPath, "Docker volume");
        if (browseDirBtn) {
          browseDirBtn.title = "Docker controls this folder through a mounted volume";
        }
        showToast(data.message || "Running in Docker: files are saved to mounted volume './output'.", "info", 6500);
        fetchOutputDirectory();
        return;
      }

      if (data.path) {
        if (outputDirInput) outputDirInput.value = data.path;
        if (sidebarOutputLabel) {
          sidebarOutputLabel.textContent = data.path.length > 18 ? "..." + data.path.slice(-16) : data.path;
        }
        fetchSavedPages();
        fetchOutputDirectory();
        showToast(`Output location selected: ${data.path}`, "success");
      } else if (data.error) {
        showToast(data.error, "error");
      }
    } catch (err) {
      showToast(`Folder selection failed: ${err.message}`, "error");
    } finally {
      browseDirBtn.disabled = false;
      if (state.isContainer) {
        browseDirBtn.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>
          </svg>
          <span>Docker volume</span>
        `;
      } else {
        browseDirBtn.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>
          </svg>
          <span>Browse Folder</span>
        `;
      }
    }
  });

  // Live Pattern Matcher Evaluation
  evalPatternBtn.addEventListener("click", () => {
    const testUrl = testUrlInput.value.trim();
    if (!testUrl) {
      showToast("Please enter a URL to test", "warn");
      return;
    }

    const incRaw = includePatternInput.value.trim();
    const excRaw = excludePatternInput.value.trim();

    const incList = incRaw ? incRaw.split(",").map((s) => s.trim()).filter(Boolean) : [];
    const excList = excRaw ? excRaw.split(",").map((s) => s.trim()).filter(Boolean) : [];

    function matchesPattern(url, pattern) {
      if (pattern.startsWith("re:")) {
        try {
          const re = new RegExp(pattern.slice(3));
          return re.test(url);
        } catch {
          return false;
        }
      }
      // Simple glob conversion
      const escaped = pattern
        .replace(/[.+^${}()|[\]\\]/g, "\\$&")
        .replace(/\*/g, ".*")
        .replace(/\?/g, ".");
      return new RegExp(`^${escaped}$`, "i").test(url);
    }

    let isExcluded = false;
    for (const pat of excList) {
      if (matchesPattern(testUrl, pat)) {
        isExcluded = true;
        break;
      }
    }

    let isIncluded = incList.length === 0;
    if (!isIncluded) {
      for (const pat of incList) {
        if (matchesPattern(testUrl, pat)) {
          isIncluded = true;
          break;
        }
      }
    }

    const accepted = isIncluded && !isExcluded;
    testResultBox.style.display = "flex";
    if (accepted) {
      testResultBox.className = "test-result-box test-accepted";
      testResultBox.innerHTML = `<strong>ACCEPTED:</strong> This URL satisfies inclusion criteria and is not excluded.`;
    } else if (isExcluded) {
      testResultBox.className = "test-result-box test-blocked";
      testResultBox.innerHTML = `<strong>BLOCKED:</strong> This URL matched one or more exclusion rules.`;
    } else {
      testResultBox.className = "test-result-box test-blocked";
      testResultBox.innerHTML = `<strong>SKIPPED:</strong> This URL did not match any of the required include patterns.`;
    }
  });

  // Reset Defaults Button
  resetFormBtn.addEventListener("click", () => {
    depthInput.value = 1;
    depthInput.setAttribute("aria-valuenow", "1");
    depthInput.setAttribute("aria-valuetext", depthDescriptions[1]);
    depthDisplay.textContent = "1";
    depthHint.textContent = depthDescriptions[1];
    maxPagesInput.value = 100;
    document.querySelectorAll(".preset-pill[data-pages]").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-pages") === "100");
    });
    if (concurrencyInput) concurrencyInput.value = 10;
    document.querySelectorAll(".preset-pill[data-concurrency]").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-concurrency") === "10");
    });
    if (delayInput) delayInput.value = 0.2;
    document.querySelectorAll(".preset-pill[data-delay]").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-delay") === "0.2");
    });
    sameDomainInput.checked = true;
    respectRobotsInput.checked = true;
    if (sitemapInput) sitemapInput.checked = false;
    if (sitemapUrlInput) sitemapUrlInput.value = "";
    if (renderJsInput) renderJsInput.checked = false;
    if (dryRunInput) dryRunInput.checked = false;
    if (incrementalInput) incrementalInput.checked = false;
    if (checkpointInput) checkpointInput.checked = true;
    if (adaptiveRateInput) adaptiveRateInput.checked = true;
    if (maxRetriesInput) maxRetriesInput.value = 2;
    if (resumeJobIdInput) resumeJobIdInput.value = "";
    if (dlqInput) dlqInput.checked = false;
    updateDlqVisibility();
    if (state.isContainer) {
      setSelectedOutputDir(state.defaultOutputDir, "Docker volume");
    } else {
      if (outputDirInput) outputDirInput.value = "";
      if (sidebarOutputLabel) sidebarOutputLabel.textContent = "No folder selected";
    }
    if (webhookUrlInput) webhookUrlInput.value = "";
    selectorInput.value = "";
    excludeSelectorInput.value = "";
    if (schemaInput) schemaInput.value = "";
    chunkSizeInput.value = 0;
    chunkOverlapInput.value = 400;
    includePatternInput.value = "";
    excludePatternInput.value = "";
    updateSetupSummary();
    showToast("Parameters reset to defaults", "info");
  });

  // =========================================================================
  // Crawling Execution & Lifecycle
  // =========================================================================
  crawlerForm.addEventListener("submit", (e) => {
    e.preventDefault();
    startCrawlJob();
  });

  globalStartBtn.addEventListener("click", () => {
    startCrawlJob();
  });

  function parseSchemaField(input) {
    if (!input) return { value: undefined };
    const raw = input.value.trim();
    if (!raw) return { value: undefined };
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      return { error: "Schema must be valid JSON." };
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: "Schema must be a JSON object mapping field names to selectors." };
    }
    return { value: parsed };
  }

  async function startCrawlJob() {
    if (state.isRunning) return;

    const urlsRaw = urlInput.value.trim();
    const sitemap = sitemapInput ? sitemapInput.checked : false;
    const sitemapUrl = sitemapUrlInput ? sitemapUrlInput.value.trim() : "";
    const resumeJobId = resumeJobIdInput ? resumeJobIdInput.value.trim() : "";
    if (!urlsRaw && !sitemapUrl && !resumeJobId) {
      showToast("Enter a target URL or a custom sitemap URL in Crawl Setup.", "warn");
      switchView("viewCrawlSetup");
      urlInput.focus();
      return;
    }

    const depth = parseInt(depthInput.value, 10);
    const maxPages = parseInt(maxPagesInput.value, 10);
    const sameDomain = sameDomainInput.checked;
    const respectRobots = respectRobotsInput.checked;
    const outputDir = getSelectedOutputDir() || (state.isContainer ? state.defaultOutputDir : "");
    if (!outputDir) {
      showToast("Choose a folder with Browse before starting the crawl.", "warn");
      switchView("viewCrawlSetup");
      browseDirBtn.focus();
      return;
    }
    const format = formatInput.value || "md";
    const targetSelector = selectorInput.value.trim();
    const excludeSelectors = excludeSelectorInput.value.trim();
    const chunkSize = parseInt(chunkSizeInput.value, 10) || 0;
    const chunkOverlap = parseInt(chunkOverlapInput.value, 10) || 400;
    const includePatterns = includePatternInput.value.trim();
    const excludePatterns = excludePatternInput.value.trim();
    const concurrency = concurrencyInput ? (parseInt(concurrencyInput.value, 10) || 5) : 5;
    const delay = delayInput ? (parseFloat(delayInput.value) >= 0 ? parseFloat(delayInput.value) : 0.2) : 0.2;
    const renderJs = renderJsInput ? renderJsInput.checked : false;
    const dryRun = dryRunInput ? dryRunInput.checked : false;
    const incremental = incrementalInput ? incrementalInput.checked : false;
    const checkpoint = checkpointInput ? checkpointInput.checked : true;
    const adaptiveRateLimit = adaptiveRateInput ? adaptiveRateInput.checked : true;
    const maxRetries = maxRetriesInput ? Math.max(1, parseInt(maxRetriesInput.value, 10) || 2) : 2;
    const dlq = dlqInput ? dlqInput.checked : false;
    const impersonate = impersonateInput ? impersonateInput.value : "chrome";
    const proxy = proxyInput ? proxyInput.value.trim() : "";
    const webhookUrl = webhookUrlInput ? webhookUrlInput.value.trim() : "";
    const schemaField = parseSchemaField(schemaInput);
    if (schemaField.error) {
      showToast(`Invalid schema: ${schemaField.error}`, "warn");
      switchView("viewCrawlSetup");
      if (schemaInput) schemaInput.focus();
      return;
    }
    const schema = schemaField.value;

    const enableMedia = document.getElementById("enableMediaExtractor")?.checked || false;
    const mediaModeEl = document.querySelector('input[name="mediaModeOption"]:checked');
    const mediaMode = mediaModeEl ? mediaModeEl.value : "both";
    const downloadMedia = document.getElementById("downloadMediaFiles")?.checked || false;
    const mediaTypes = [];
    if (document.getElementById("mediaTypeImage")?.checked) mediaTypes.push("image");
    if (document.getElementById("mediaTypePdf")?.checked) mediaTypes.push("pdf");
    if (document.getElementById("mediaTypeDoc")?.checked) mediaTypes.push("doc");
    if (document.getElementById("mediaTypePpt")?.checked) mediaTypes.push("ppt");
    if (document.getElementById("mediaTypeVideo")?.checked) mediaTypes.push("video");

    // Disable start buttons, show loading state
    setLaunchState(true);

    try {
      const resp = await fetch("/api/scrape/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          urls: urlsRaw,
          depth,
          max_pages: maxPages,
          same_domain: sameDomain,
          respect_robots: respectRobots,
          output_dir: outputDir,
          output_format: format,
          target_selector: targetSelector,
          exclude_selectors: excludeSelectors,
          schema,
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          include_patterns: includePatterns,
          exclude_patterns: excludePatterns,
          concurrency,
          delay,
          sitemap,
          sitemap_url: sitemapUrl,
          render_js: renderJs,
          dry_run: dryRun,
          impersonate,
          proxy,
          webhook_url: webhookUrl,
          extract_media: enableMedia,
          media_mode: mediaMode,
          download_media: downloadMedia,
          media_types: mediaTypes,
          incremental,
          checkpoint,
          adaptive_rate_limit: adaptiveRateLimit,
          max_retries: maxRetries,
          resume_job_id: resumeJobId,
          dlq,
        }),
      });

      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || "Failed to start crawler");
      }
      if (data.job_id) {
        state.currentJobId = data.job_id;
        if (dlq) {
          refreshFailures(data.job_id);
        }
      }

      showToast(dryRun ? "Dry run started! Discovering URLs..." : "Crawl job started successfully!", "success");
      resetVelocity();
      updateStatus("running", "", dryRun);

      // Auto-switch to Live Monitor so user can watch progress immediately
      switchView("viewMonitor");
    } catch (err) {
      showToast(err.message, "error");
      updateStatus("idle");
    } finally {
      setLaunchState(false);
    }
  }

  async function refreshFailures(jobId = state.currentJobId) {
    if (!dlqList || !dlqCard) return;
    if (dlqInput && !dlqInput.checked) return;
    const params = new URLSearchParams();
    if (jobId) params.set("job_id", jobId);
    const outputDir = getSelectedOutputDir() || (state.isContainer ? state.defaultOutputDir : "");
    if (outputDir) params.set("output_dir", outputDir);
    try {
      const resp = await fetch(`/api/scrape/failures?${params.toString()}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Could not load failures");
      const failures = data.failures || [];
      if (!failures.length) {
        dlqStatusText.textContent = "No failures recorded";
        dlqList.innerHTML = '<p class="input-desc">Failed URLs will appear here with their error category. Retrying resumes the same checkpoint and only re-runs this list.</p>';
        retryDlqBtn.disabled = true;
        return;
      }
      dlqStatusText.textContent = `${failures.length} failed URL(s) for job ${data.job_id || "(latest)"}`;
      retryDlqBtn.disabled = false;
      dlqList.innerHTML = "";
      failures.slice(0, 100).forEach((failure) => {
        const row = document.createElement("div");
        row.className = "dlq-row";
        const badge = document.createElement("span");
        badge.className = "dlq-badge";
        badge.textContent = failure.error_category || "unknown";
        const url = document.createElement("span");
        url.className = "dlq-url";
        url.textContent = failure.url || "";
        const meta = document.createElement("span");
        meta.className = "dlq-meta";
        meta.textContent = `attempts ${failure.attempts || 0}${failure.status_code ? ` · HTTP ${failure.status_code}` : ""}`;
        row.append(badge, url, meta);
        row.title = failure.message || "";
        dlqList.appendChild(row);
      });
      if (failures.length > 100) {
        const more = document.createElement("p");
        more.className = "input-desc";
        more.textContent = `Showing the first 100 of ${failures.length} failed URLs.`;
        dlqList.appendChild(more);
      }
    } catch (err) {
      dlqStatusText.textContent = "Could not load failures";
      console.warn(err);
    }
  }

  if (refreshDlqBtn) {
    refreshDlqBtn.addEventListener("click", () => refreshFailures());
  }
  if (retryDlqBtn) {
    retryDlqBtn.addEventListener("click", async () => {
      const outputDir = getSelectedOutputDir() || (state.isContainer ? state.defaultOutputDir : "");
      retryDlqBtn.disabled = true;
      try {
        const resp = await fetch("/api/scrape/retry-failed", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: state.currentJobId, output_dir: outputDir }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Could not retry failed URLs");
        showToast("Retrying failed URLs from the checkpoint...", "success");
        state.isRunning = true;
        updateStatus("running");
        switchView("viewMonitor");
        refreshFailures(data.job_id || state.currentJobId);
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        retryDlqBtn.disabled = false;
      }
    });
  }

  function setLaunchState(loading) {
    if (loading) {
      globalStartBtn.disabled = true;
      submitCrawlBtn.disabled = true;
      globalStartBtn.innerHTML = `<span>Starting...</span>`;
      submitCrawlBtn.innerHTML = `<span>Starting...</span>`;
    } else {
      globalStartBtn.innerHTML = `
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="6 3 20 12 6 21 6 3"/>
        </svg>
        <span>Start Crawl</span>
      `;
      submitCrawlBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <polygon points="6 3 20 12 6 21 6 3"/>
        </svg>
        <span>Launch Crawl Job</span>
      `;
    }
  }

  // Stop Crawl Job
  globalStopBtn.addEventListener("click", async () => {
    if (!state.isRunning) return;
    globalStopBtn.disabled = true;

    try {
      const resp = await fetch("/api/scrape/stop", { method: "POST" });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Failed to stop crawl");
      showToast("Stopping crawler and saving files to disk...", "warn");
      updateStatus("stopping");

      // Fallback check: if still stopping after 3s, force check status
      setTimeout(async () => {
        try {
          const sResp = await fetch("/api/scrape/status");
          if (sResp.ok) {
            const snap = await sResp.json();
            if (snap.status) syncSnapshot(snap);
          }
        } catch (_) {}
      }, 3000);
    } catch (err) {
      showToast(err.message, "error");
      globalStopBtn.disabled = false;
    }
  });

  // --- Active Status Polling Heartbeat (Fallback resilience) ---
  let statusPollTimer = null;

  function startStatusPolling() {
    if (statusPollTimer) return;
    statusPollTimer = setInterval(async () => {
      if (!state.isRunning && !state.isStopping) {
        stopStatusPolling();
        return;
      }
      try {
        const resp = await fetch("/api/scrape/status");
        if (resp.ok) {
          const snap = await resp.json();
          if (snap.status) {
            syncSnapshot(snap);
            if (snap.status !== "running" && snap.status !== "stopping") {
              stopStatusPolling();
            }
          }
        }
      } catch (_) {
        // Transient network errors ignored; SSE or next poll will catch it
      }
    }, 800);
  }

  function stopStatusPolling() {
    if (statusPollTimer) {
      clearInterval(statusPollTimer);
      statusPollTimer = null;
    }
  }

  // Status updates
  function updateStatus(status, errorMsg = "", isDryRun = false) {
    statusPill.className = `status-pill status-${status}`;
    const labels = {
      idle: "Idle",
      running: isDryRun ? "Discovering..." : "Crawling...",
      stopping: "Stopping...",
      completed: "Completed",
      stopped: "Stopped",
      failed: "Failed",
    };
    statusText.textContent = labels[status] || status;

    if (status === "running") {
      state.isRunning = true;
      state.isStopping = false;
      globalStartBtn.disabled = true;
      submitCrawlBtn.disabled = true;
      globalStopBtn.disabled = false;
      topbarTicker.style.display = "flex";
      sidebarPulse.className = "pulse-dot pulsing";
      sidebarStatusText.textContent = isDryRun ? "Dry Run in Progress" : "Crawl in Progress";

      if (!state.elapsedTimer) {
        state.crawlStartTime = Date.now();
        state.elapsedTimer = setInterval(updateElapsedTimer, 200);
      }
      startVelocitySampling();
      startStatusPolling();
    } else if (status === "stopping") {
      state.isRunning = true;
      state.isStopping = true;
      globalStartBtn.disabled = true;
      submitCrawlBtn.disabled = true;
      globalStopBtn.disabled = true;
      sidebarPulse.className = "pulse-dot";
      sidebarStatusText.textContent = "Stopping Crawler...";
      monitorDepthTag.textContent = "Stopping";
      monitorUrlText.textContent = "Halting workers and saving crawl progress to disk...";
      startStatusPolling();
    } else {
      const wasRunning = state.isRunning;
      state.isRunning = false;
      state.isStopping = false;
      stopStatusPolling();
      globalStartBtn.disabled = false;
      submitCrawlBtn.disabled = false;
      globalStopBtn.disabled = true;
      topbarTicker.style.display = "none";
      sidebarPulse.className = "pulse-dot";
      sidebarStatusText.textContent = "Engine Ready";

      if (state.elapsedTimer) {
        clearInterval(state.elapsedTimer);
        state.elapsedTimer = null;
      }
      stopVelocitySampling();

      if (status === "completed") {
        monitorDepthTag.textContent = "Finished";
        if (isDryRun) {
          monitorUrlText.textContent = "Dry run complete. Discovered URLs listed in logs.";
          if (wasRunning) showToast("Dry run completed successfully!", "success");
        } else {
          monitorUrlText.textContent = "All pages crawled and saved to output folder.";
          if (wasRunning) {
            showToast("Crawl finished successfully!", "success");
            fetchSavedPages();
            fetchOutputDirectory();
          }
        }
      } else if (status === "stopped") {
        monitorDepthTag.textContent = "Stopped";
        monitorUrlText.textContent = isDryRun ? "Dry run stopped by user." : "Crawl stopped by user. All progress saved.";
        if (wasRunning) {
          showToast(isDryRun ? "Dry run stopped" : "Crawl stopped. Progress saved to disk.", "info");
          fetchSavedPages();
          fetchOutputDirectory();
        }
      } else if (status === "failed") {
        monitorDepthTag.textContent = "Error";
        monitorUrlText.textContent = errorMsg || "Crawl ended due to an error.";
        if (wasRunning) showToast(errorMsg || "Crawl job failed", "error");
      }
    }
  }

  function updateElapsedTimer() {
    if (!state.crawlStartTime) return;
    const sec = ((Date.now() - state.crawlStartTime) / 1000).toFixed(1);
    monitorElapsedVal.textContent = `${sec}s`;
  }

  // --- Live throughput (pages/second) sampling & sparkline -----------------
  const VELOCITY_SAMPLE_LIMIT = 40;

  function resetVelocity() {
    stopVelocitySampling();
    state.velocitySamples = [];
    state.lastVelocityTick = null;
    state.latestCrawled = 0;
    state.sessionAvgRate = 0;
    state.peakRate = 0;
    updateVelocityDisplay();
  }

  function startVelocitySampling() {
    if (state.velocityTimer) return;
    state.lastVelocityTick = { time: Date.now(), crawled: state.latestCrawled };
    state.velocityTimer = setInterval(sampleVelocity, 1000);
    if (monitorVelocityCard) monitorVelocityCard.classList.add("is-active");
  }

  function stopVelocitySampling() {
    if (state.velocityTimer) {
      clearInterval(state.velocityTimer);
      state.velocityTimer = null;
    }
    state.lastVelocityTick = null;
    if (monitorVelocityCard) monitorVelocityCard.classList.remove("is-active");
  }

  function sampleVelocity() {
    if (!state.isRunning) return;

    const now = Date.now();
    const crawled = state.latestCrawled;
    const previous = state.lastVelocityTick;

    if (!previous) {
      state.lastVelocityTick = { time: now, crawled };
      return;
    }

    const deltaSeconds = (now - previous.time) / 1000;
    const deltaPages = Math.max(0, crawled - previous.crawled);
    const rate = deltaSeconds > 0 ? deltaPages / deltaSeconds : 0;

    state.lastVelocityTick = { time: now, crawled };
    state.velocitySamples.push(rate);
    if (state.velocitySamples.length > VELOCITY_SAMPLE_LIMIT) {
      state.velocitySamples.shift();
    }
    state.peakRate = Math.max(state.peakRate, rate);
    updateVelocityDisplay();
  }

  function updateVelocityDisplay() {
    const samples = state.velocitySamples;
    const current = samples.length ? samples[samples.length - 1] : state.sessionAvgRate;
    const peak = Math.max(state.peakRate, current);

    if (monitorRateVal) monitorRateVal.textContent = (current || 0).toFixed(1);
    if (monitorRatePeakVal) monitorRatePeakVal.textContent = `peak ${(peak || 0).toFixed(1)} p/s`;
    if (monitorRateAvgVal) monitorRateAvgVal.textContent = (state.sessionAvgRate || 0).toFixed(1);

    renderVelocitySparkline();
  }

  function renderVelocitySparkline() {
    if (!monitorRateSparkline) return;

    let series = state.velocitySamples.slice();
    if (!series.length && state.sessionAvgRate > 0) {
      series = [state.sessionAvgRate];
    }
    if (!series.length) {
      monitorRateSparkline.setAttribute("points", "0,22 100,22");
      return;
    }

    const maxRate = Math.max(...series, 1);
    const step = series.length > 1 ? 100 / (series.length - 1) : 100;
    const yFor = (rate) => 22 - (Math.max(0, rate) / maxRate) * 20;

    const points = series.map((rate, index) => {
      const x = series.length === 1 ? 0 : index * step;
      return `${x.toFixed(2)},${yFor(rate).toFixed(2)}`;
    });

    if (series.length === 1) {
      points.push(`100.00,${yFor(series[0]).toFixed(2)}`);
    }

    monitorRateSparkline.setAttribute("points", points.join(" "));
  }

  // =========================================================================
  // Server-Sent Events (SSE) Telemetry
  // =========================================================================
  function initSSE() {
    if (state.eventSource) {
      state.eventSource.close();
    }

    state.eventSource = new EventSource("/api/scrape/events");

    state.eventSource.addEventListener("init", (e) => {
      try {
        const data = JSON.parse(e.data);
        syncSnapshot(data);
      } catch (err) {
        console.error("Failed to parse SSE init:", err);
      }
    });

    state.eventSource.addEventListener("status", (e) => {
      try {
        const data = JSON.parse(e.data);
        syncSnapshot(data);
      } catch (err) {
        console.error("Failed to parse SSE status:", err);
      }
    });

    state.eventSource.addEventListener("completed", (e) => {
      try {
        const data = JSON.parse(e.data);
        syncSnapshot(data);
        refreshFailures(data.job_id || state.currentJobId);
      } catch (err) {
        console.error("Failed to parse SSE completed:", err);
      }
    });

    state.eventSource.addEventListener("dlq", (e) => {
      try {
        JSON.parse(e.data);
        refreshFailures(state.currentJobId);
      } catch (err) {
        console.error("Failed to parse SSE dlq:", err);
      }
    });

    state.eventSource.addEventListener("stopped", (e) => {
      try {
        const data = JSON.parse(e.data);
        syncSnapshot(data);
        refreshFailures(data.job_id || state.currentJobId);
      } catch (err) {
        console.error("Failed to parse SSE stopped:", err);
      }
    });

    state.eventSource.addEventListener("stats", (e) => {
      try {
        const snap = JSON.parse(e.data);
        applyStats(snap);
      } catch (err) {
        console.error("Failed to parse SSE stats:", err);
      }
    });

    state.eventSource.addEventListener("log", (e) => {
      try {
        const entry = JSON.parse(e.data);
        appendLogEntry(entry);
      } catch (err) {
        console.error("Failed to parse SSE log:", err);
      }
    });

    state.eventSource.addEventListener("page_saved", (e) => {
      try {
        const page = JSON.parse(e.data);
        addSavedPage(page);
      } catch (err) {
        console.error("Failed to parse SSE page_saved:", err);
      }
    });

    state.eventSource.addEventListener("media_found", (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.items && Array.isArray(data.items)) {
          addDiscoveredMedia(data.items);
        }
      } catch (err) {
        console.error("Failed to parse SSE media_found:", err);
      }
    });

    state.eventSource.addEventListener("media_cleared", () => {
      state.discoveredMedia = [];
      state.mediaFilter = "";
      renderMediaTable();
      const navMediaBadge = document.getElementById("navMediaBadge");
      if (navMediaBadge) {
        navMediaBadge.textContent = "0";
        navMediaBadge.style.display = "none";
      }
      const mediaTotalCountEl = document.getElementById("mediaTotalCount");
      if (mediaTotalCountEl) mediaTotalCountEl.textContent = "0";
    });

    state.eventSource.addEventListener("reset", () => {
      clearAllClientData();
    });

    state.eventSource.onerror = () => {
      // Browser EventSource automatically handles reconnection
    };
  }

  function syncSnapshot(snap) {
    if (!snap) return;
    if (snap.job_id) {
      state.currentJobId = snap.job_id;
    }
    if (snap.dlq !== undefined && dlqInput) {
      dlqInput.checked = Boolean(snap.dlq);
      updateDlqVisibility();
    }
    applyStats(snap);

    if (snap.logs && Array.isArray(snap.logs) && state.allLogs.length === 0) {
      for (const log of snap.logs) {
        state.allLogs.push(log);
      }
      if (state.allLogs.length > 600) {
        state.allLogs = state.allLogs.slice(-600);
      }
      if (navLogBadge) navLogBadge.textContent = state.allLogs.length;
      if (terminalCounter) terminalCounter.textContent = `${state.allLogs.length} logs`;
      rebuildConsoleLogs();
    }

    if (snap.recent_pages && Array.isArray(snap.recent_pages) && snap.recent_pages.length > 0) {
      addSavedPagesBatch(snap.recent_pages);
    }

    if (snap.recent_media && Array.isArray(snap.recent_media) && snap.recent_media.length > 0) {
      addDiscoveredMedia(snap.recent_media);
    }

    updateStatus(snap.status || "idle", snap.error_message, Boolean(snap.dry_run));
  }

  function applyStats(snap) {
    if (snap.status && snap.status !== "running" && state.isRunning) {
      updateStatus(snap.status, snap.error_message, Boolean(snap.dry_run));
    }

    const crawled = Number(snap.pages_crawled) || 0;
    const elapsed = Number(snap.elapsed_seconds) || 0;

    state.latestCrawled = crawled;
    state.sessionAvgRate = elapsed > 0 ? crawled / elapsed : 0;

    if (monitorCrawledVal) monitorCrawledVal.textContent = crawled;
    if (monitorSavedVal) monitorSavedVal.textContent = snap.pages_saved ?? 0;
    if (monitorSkippedVal) monitorSkippedVal.textContent = snap.pages_skipped ?? 0;
    if (monitorElapsedVal) {
      monitorElapsedVal.textContent = `${elapsed}s`;
    }
    const mediaFoundEl = document.getElementById("monitorMediaFoundVal");
    if (mediaFoundEl && snap.media_extracted !== undefined) {
      mediaFoundEl.textContent = snap.media_extracted;
    }
    const mediaDownloadedEl = document.getElementById("monitorMediaDownloadedVal");
    if (mediaDownloadedEl && snap.media_downloaded !== undefined) {
      mediaDownloadedEl.textContent = snap.media_downloaded;
    }
    const navMediaBadge = document.getElementById("navMediaBadge");
    if (navMediaBadge) {
      const count = snap.media_extracted ?? state.discoveredMedia.length;
      navMediaBadge.textContent = count;
      navMediaBadge.style.display = count > 0 ? "inline-block" : "none";
    }
    updateVelocityDisplay();

    if (snap.current_url) {
      const depthStr = `Depth ${snap.current_depth ?? 0}`;
      if (monitorDepthTag) monitorDepthTag.textContent = depthStr;
      if (monitorUrlText) monitorUrlText.textContent = snap.current_url;
      if (topbarTickerText) topbarTickerText.textContent = `[${depthStr}] ${snap.current_url}`;
    } else if (!state.isRunning) {
      if (monitorDepthTag) monitorDepthTag.textContent = "Depth 0";
      if (monitorUrlText) monitorUrlText.textContent = "Engine idle. Ready to crawl.";
    }
  }

  // =========================================================================
  // Live Streaming Terminal Console
  // =========================================================================
  let consoleScrollPending = false;
  function requestConsoleScroll() {
    if (consoleScrollPending || !terminalAutoScroll || !terminalAutoScroll.checked) return;
    consoleScrollPending = true;
    requestAnimationFrame(() => {
      consoleScrollPending = false;
      if (terminalConsole) {
        terminalConsole.scrollTop = terminalConsole.scrollHeight;
      }
    });
  }

  function normalizeLogLevel(level) {
    const lvl = String(level || "INFO").trim().toUpperCase();
    if (lvl === "WARNING" || lvl === "WARN") return "WARN";
    if (lvl === "ERROR" || lvl === "CRITICAL" || lvl === "FATAL" || lvl === "EXCEPTION") return "ERROR";
    if (lvl === "INFO") return "INFO";
    if (lvl === "DEBUG") return "DEBUG";
    return lvl;
  }

  function matchesLogFilter(entryLevel, filter) {
    if (!filter || filter === "ALL") return true;
    return normalizeLogLevel(entryLevel) === normalizeLogLevel(filter);
  }

  let logRenderRaf = null;
  let pendingLogEntries = [];

  function appendLogEntry(entry) {
    state.allLogs.push(entry);
    if (state.allLogs.length > 600) state.allLogs.shift();

    if (navLogBadge) navLogBadge.textContent = state.allLogs.length;

    if (matchesLogFilter(entry.level, state.currentLogFilter)) {
      pendingLogEntries.push(entry);
      if (!logRenderRaf) {
        logRenderRaf = requestAnimationFrame(flushLogDOM);
      }
    }

    if (terminalCounter) {
      if (state.currentLogFilter === "ALL") {
        terminalCounter.textContent = `${state.allLogs.length} logs`;
      } else {
        const count = state.allLogs.filter((e) => matchesLogFilter(e.level, state.currentLogFilter)).length;
        terminalCounter.textContent = `${count} / ${state.allLogs.length} logs (${state.currentLogFilter})`;
      }
    }
  }

  function createLogRowElement(entry) {
    const row = document.createElement("div");
    const norm = normalizeLogLevel(entry.level);
    const lvl = norm.toLowerCase();
    row.className = `log-row log-${lvl}`;

    const ts = document.createElement("span");
    ts.className = "log-ts";
    ts.textContent = entry.time || new Date().toTimeString().slice(0, 8);

    const tag = document.createElement("span");
    tag.className = "log-tag";
    tag.textContent = norm;

    const content = document.createElement("span");
    content.className = "log-content";
    content.textContent = entry.message || "";

    row.appendChild(ts);
    row.appendChild(tag);
    row.appendChild(content);
    return row;
  }

  function flushLogDOM() {
    logRenderRaf = null;
    if (!terminalConsole || !pendingLogEntries.length) return;
    const batch = pendingLogEntries.slice(-100);
    pendingLogEntries = [];
    const frag = document.createDocumentFragment();
    for (const ent of batch) {
      frag.appendChild(createLogRowElement(ent));
    }
    terminalConsole.appendChild(frag);
    while (terminalConsole.children.length > 400) {
      terminalConsole.removeChild(terminalConsole.firstChild);
    }
    requestConsoleScroll();
  }

  levelPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      levelPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      state.currentLogFilter = pill.getAttribute("data-level");
      rebuildConsoleLogs();
    });
  });

  function rebuildConsoleLogs() {
    if (!terminalConsole) return;
    terminalConsole.innerHTML = "";
    const fragment = document.createDocumentFragment();
    const relevantLogs = state.allLogs.filter(
      (e) => matchesLogFilter(e.level, state.currentLogFilter)
    );
    const visibleLogs = relevantLogs.slice(-400);
    for (const entry of visibleLogs) {
      fragment.appendChild(createLogRowElement(entry));
    }
    terminalConsole.appendChild(fragment);

    if (terminalCounter) {
      if (state.currentLogFilter === "ALL") {
        terminalCounter.textContent = `${state.allLogs.length} logs`;
      } else {
        terminalCounter.textContent = `${relevantLogs.length} / ${state.allLogs.length} logs (${state.currentLogFilter})`;
      }
    }
    requestConsoleScroll();
  }

  if (terminalClearBtn) {
    terminalClearBtn.addEventListener("click", async () => {
      state.allLogs = [];
      if (terminalConsole) terminalConsole.innerHTML = "";
      if (navLogBadge) navLogBadge.textContent = "0";
      if (terminalCounter) terminalCounter.textContent = "0 logs";
      try {
        await fetch("/api/scrape/logs/clear", { method: "POST" });
      } catch (_) {}
      showToast("Console logs cleared", "info", 1500);
    });
  }

  if (monitorResetBtn) {
    monitorResetBtn.addEventListener("click", async () => {
      if (state.isRunning && !state.isStopping) {
        const confirmForce = confirm("A crawl job is currently active. Halt and reset the session now?");
        if (!confirmForce) return;
        try {
          await fetch("/api/scrape/stop", { method: "POST" });
        } catch (_) {}
      } else {
        const confirmed = confirm("Are you sure you want to reset the live monitor telemetry and session metrics?");
        if (!confirmed) return;
      }

      try {
        await fetch("/api/scrape/reset", { method: "POST" });
      } catch (_) {}
      clearAllClientData();
      updateStatus("idle");
      showToast("Live Monitor and session data reset", "info");
    });
  }

  // =========================================================================
  // Single URL Inspector (Interactive Scraper Tester)
  // =========================================================================
  const INSPECT_BUTTON_HTML = `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="5 3 19 12 5 21 5 3"/>
    </svg>
    <span>Inspect Page</span>
  `;

  function inspectorContentFor(format, documentData) {
    if (!documentData) return "";
    switch (format) {
      case "text":
        return documentData.text || "";
      case "json":
        return JSON.stringify(documentData, null, 2);
      case "html":
        return documentData.html || "";
      case "markdown":
      default:
        return documentData.markdown || documentData.text || "";
    }
  }

  function renderInspectorPreview() {
    if (!state.inspectDocument) return;
    const content = inspectorContentFor(state.inspectFormat, state.inspectDocument);
    inspectorPreviewBlock.textContent = content || "[Empty response]";
    inspectorSize.textContent = `${(new Blob([content]).size / 1024).toFixed(1)} KB`;
  }

  function updateInspectorMeta(documentData, elapsed, httpStatus) {
    inspectorMetaBar.style.display = "flex";
    inspectorStatusTag.style.color = "";
    inspectorStatusTag.textContent = `HTTP ${httpStatus || documentData.status_code || 200} OK`;
    inspectorTime.textContent = `${elapsed}s`;
    inspectorWordCount.textContent = String(documentData.word_count || 0);

    const selector = inspectorSelectorInput ? inspectorSelectorInput.value.trim() : "";
    if (!selector) {
      inspectorSelectorStatus.textContent = "full page";
      inspectorSelectorStatus.style.color = "";
    } else if (documentData.selector_matched !== false) {
      inspectorSelectorStatus.textContent = "matched";
      inspectorSelectorStatus.style.color = "var(--success)";
    } else {
      inspectorSelectorStatus.textContent = "not found (body fallback)";
      inspectorSelectorStatus.style.color = "var(--warning, var(--danger))";
    }
    renderInspectorPreview();
  }

  async function runInspectorScrape({ live = false } = {}) {
    const url = inspectorUrl.value.trim();
    if (!url) {
      if (!live) showToast("Please enter a URL to inspect", "warn");
      return;
    }
    const schemaField = parseSchemaField(inspectorSchemaInput);
    if (schemaField.error) {
      if (!live) showToast(`Invalid schema: ${schemaField.error}`, "warn");
      return;
    }

    if (state.inspectTimer) {
      clearTimeout(state.inspectTimer);
      state.inspectTimer = null;
    }
    if (state.inspectController) state.inspectController.abort();
    const controller = new AbortController();
    state.inspectController = controller;
    const seq = ++state.inspectSeq;

    if (!live) {
      inspectScrapeBtn.disabled = true;
      inspectScrapeBtn.innerHTML = `<span>Inspecting...</span>`;
      inspectorPreviewBlock.textContent = `Connecting to ${url} and extracting content...`;
      inspectorMetaBar.style.display = "none";
    }

    const startTime = performance.now();
    const inspectorChunkSize = chunkSizeInput ? parseInt(chunkSizeInput.value, 10) : 0;
    const inspectorChunkOverlap = chunkOverlapInput ? parseInt(chunkOverlapInput.value, 10) : 400;
    const inspectorDelay = delayInput ? parseFloat(delayInput.value) : 0;
    try {
      const resp = await fetch("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          url,
          // JSON carries Markdown, text, HTML, and metadata, so every output
          // tab renders instantly without re-fetching the page.
          format: "json",
          render_js: inspectorJsToggle.checked,
          target_selector: inspectorSelectorInput.value.trim() || undefined,
          exclude_selectors: inspectorExcludeSelectorInput.value.trim() || undefined,
          schema: schemaField.value,
          respect_robots: respectRobotsInput ? respectRobotsInput.checked : true,
          chunk_size: Number.isFinite(inspectorChunkSize) ? inspectorChunkSize : 0,
          chunk_overlap: Number.isFinite(inspectorChunkOverlap) ? inspectorChunkOverlap : 400,
          delay: Number.isFinite(inspectorDelay) ? inspectorDelay : 0,
          impersonate: impersonateInput ? impersonateInput.value : undefined,
          proxy: proxyInput ? proxyInput.value.trim() || undefined : undefined,
        }),
      });

      const json = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error((json && json.error) || `HTTP ${resp.status}`);
      if (seq !== state.inspectSeq) return;

      const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
      state.inspectDocument = json;
      state.inspectHasRun = true;
      updateInspectorMeta(json, elapsed, resp.status);

      if (!live) showToast("Page scraped and rendered successfully!", "success");
    } catch (err) {
      if (err.name === "AbortError" || seq !== state.inspectSeq) return;
      inspectorPreviewBlock.textContent = `Scrape Error:\n${err.message}`;
      inspectorMetaBar.style.display = "flex";
      inspectorStatusTag.textContent = "Failed";
      inspectorStatusTag.style.color = "var(--danger)";
      inspectorSelectorStatus.textContent = "—";
      inspectorWordCount.textContent = "0";
      if (!live) showToast(`Inspector failed: ${err.message}`, "error");
    } finally {
      if (seq === state.inspectSeq) {
        inspectScrapeBtn.disabled = false;
        inspectScrapeBtn.innerHTML = INSPECT_BUTTON_HTML;
      }
    }
  }

  function scheduleInspectorPreview() {
    if (!inspectorLiveToggle || !inspectorLiveToggle.checked) return;
    if (!state.inspectHasRun) return;
    if (state.inspectTimer) clearTimeout(state.inspectTimer);
    state.inspectTimer = setTimeout(() => {
      state.inspectTimer = null;
      runInspectorScrape({ live: true });
    }, 650);
  }

  inspectFormatBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      inspectFormatBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.inspectFormat = btn.getAttribute("data-inspect-format");
      renderInspectorPreview();
    });
  });

  inspectScrapeBtn.addEventListener("click", () => runInspectorScrape());

  inspectorUrl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runInspectorScrape();
    }
  });

  [inspectorSelectorInput, inspectorExcludeSelectorInput].forEach((input) => {
    if (!input) return;
    input.addEventListener("input", scheduleInspectorPreview);
    input.addEventListener("change", scheduleInspectorPreview);
  });

  if (inspectorJsToggle) {
    inspectorJsToggle.addEventListener("change", scheduleInspectorPreview);
  }

  if (inspectorLiveToggle) {
    inspectorLiveToggle.addEventListener("change", () => {
      if (!inspectorLiveToggle.checked) {
        if (state.inspectTimer) {
          clearTimeout(state.inspectTimer);
          state.inspectTimer = null;
        }
        return;
      }
      scheduleInspectorPreview();
    });
  }

  if (inspectorUseSetupBtn) {
    inspectorUseSetupBtn.addEventListener("click", () => {
      if (inspectorSelectorInput) inspectorSelectorInput.value = selectorInput.value.trim();
      if (inspectorExcludeSelectorInput) inspectorExcludeSelectorInput.value = excludeSelectorInput.value.trim();
      if (inspectorSchemaInput && schemaInput) inspectorSchemaInput.value = schemaInput.value.trim();
      showToast("Copied selectors from Crawl Setup", "info", 1600);
      if (state.inspectHasRun) {
        runInspectorScrape({ live: true });
      } else if (inspectorUrl.value.trim()) {
        runInspectorScrape();
      }
    });
  }

  // Keep the tester and the crawl setup in sync on first load.
  if (inspectorSelectorInput && !inspectorSelectorInput.value) {
    inspectorSelectorInput.value = selectorInput.value.trim();
  }
  if (inspectorExcludeSelectorInput && !inspectorExcludeSelectorInput.value) {
    inspectorExcludeSelectorInput.value = excludeSelectorInput.value.trim();
  }
  if (inspectorSchemaInput && !inspectorSchemaInput.value && schemaInput) {
    inspectorSchemaInput.value = schemaInput.value.trim();
  }

  inspectorCopyBtn.addEventListener("click", async () => {
    const text = inspectorPreviewBlock.textContent;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      inspectorCopyBtn.textContent = "Copied!";
      setTimeout(() => (inspectorCopyBtn.textContent = "Copy Result"), 1800);
      showToast("Inspector content copied to clipboard", "success");
    } catch {
      showToast("Clipboard copy failed", "error");
    }
  });

  // =========================================================================
  // Saved Pages Catalog & Results Data Fetching
  // =========================================================================
  let activeResultsPromise = null;
  async function fetchResultsData(outDir) {
    if (activeResultsPromise) return activeResultsPromise;
    activeResultsPromise = (async () => {
      try {
        const resp = await fetch(`/api/results?output_dir=${encodeURIComponent(outDir)}`);
        if (!resp.ok) return null;
        return await resp.json();
      } catch (err) {
        console.warn("Failed to fetch results:", err);
        return null;
      } finally {
        setTimeout(() => {
          activeResultsPromise = null;
        }, 300);
      }
    })();
    return activeResultsPromise;
  }

  function setSelectedOutputDir(path, sidebarText) {
    if (outputDirInput) outputDirInput.value = path || "";
    if (sidebarOutputLabel) {
      if (sidebarText) {
        sidebarOutputLabel.textContent = sidebarText;
      } else {
        sidebarOutputLabel.textContent = path
          ? (path.length > 18 ? "..." + path.slice(-16) : path)
          : "No folder selected";
      }
    }
  }

  function getSelectedOutputDir() {
    return outputDirInput ? outputDirInput.value.trim() : "";
  }

  let catalogRenderTimer = null;
  function scheduleCatalogRender() {
    if (catalogRenderTimer) return;
    catalogRenderTimer = requestAnimationFrame(() => {
      catalogRenderTimer = null;
      renderCatalogTable();
    });
  }

  function addSavedPagesBatch(pages) {
    if (!pages || !pages.length) return;
    const existingMap = new Map();
    state.savedPages.forEach((p, idx) => {
      if (p.file) existingMap.set(p.file, idx);
    });

    let modified = false;
    for (const p of pages) {
      if (!p || !p.file) continue;
      if (existingMap.has(p.file)) {
        state.savedPages[existingMap.get(p.file)] = p;
      } else {
        state.savedPages.unshift(p);
        existingMap.set(p.file, 0);
      }
      modified = true;
    }

    if (modified) {
      if (navPageBadge) navPageBadge.textContent = state.savedPages.length;
      scheduleCatalogRender();
    }
  }

  function addSavedPage(page) {
    if (!page || !page.file) return;
    const existing = state.savedPages.findIndex((p) => p.file === page.file);
    if (existing >= 0) {
      state.savedPages[existing] = page;
    } else {
      state.savedPages.unshift(page);
    }
    if (navPageBadge) navPageBadge.textContent = state.savedPages.length;
    scheduleCatalogRender();
  }

  async function fetchSavedPages() {
    const outDir = getSelectedOutputDir() || state.defaultOutputDir || "./output";
    if (!outDir) return;
    const data = await fetchResultsData(outDir);
    if (!data) return;
    if (data.pages && Array.isArray(data.pages)) {
      state.savedPages = data.pages;
      if (navPageBadge) navPageBadge.textContent = state.savedPages.length;
      scheduleCatalogRender();
    }
  }

  function renderCatalogTable() {
    if (!catalogTableBody) return;
    const query = catalogSearchInput ? catalogSearchInput.value.trim().toLowerCase() : "";
    const filtered = state.savedPages.filter((page) => {
      if (!query) return true;
      return (
        (page.title && page.title.toLowerCase().includes(query)) ||
        (page.url && page.url.toLowerCase().includes(query)) ||
        (page.file && page.file.toLowerCase().includes(query))
      );
    });

    if (catalogTotalCount) catalogTotalCount.textContent = state.savedPages.length;

    if (filtered.length === 0) {
      catalogTableBody.innerHTML = `
        <tr class="empty-state-row">
          <td colspan="5">
            <div class="empty-box">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
              <h4>${query ? "No documents match your query" : "No pages saved yet"}</h4>
              <p>${query ? "Try searching for a different keyword or filename." : "Start a crawl job or test an individual URL in the Inspector to see documents here."}</p>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    const fragment = document.createDocumentFragment();
    const limit = query ? filtered.length : (state.catalogRenderLimit || 100);
    const displayList = filtered.slice(0, limit);

    for (let i = 0; i < displayList.length; i++) {
      const page = displayList[i];
      const tr = document.createElement("tr");
      const sizeStr = page.bytes ? `${(page.bytes / 1024).toFixed(1)} KB` : "—";
      const titleStr = escapeHtml(page.title || "Untitled Document");
      const urlStr = escapeHtml(page.url || "");
      const fileStr = escapeHtml(page.file || "");

      tr.innerHTML = `
        <td class="col-title">
          <span class="table-page-title" title="${titleStr}">${titleStr}</span>
          <a href="${urlStr}" target="_blank" rel="noopener noreferrer" class="table-page-url" title="${urlStr}">${urlStr}</a>
        </td>
        <td class="col-depth">
          <span class="depth-badge">Depth ${page.depth ?? 0}</span>
        </td>
        <td class="col-file">
          <code class="table-filename" title="${fileStr}">${fileStr}</code>
        </td>
        <td class="col-size">
          <span class="table-size-val">${sizeStr}</span>
        </td>
        <td class="col-action" style="text-align: right;">
          <button type="button" class="btn btn-secondary btn-sm preview-btn" data-file="${fileStr}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
            <span>Preview</span>
          </button>
        </td>
      `;
      fragment.appendChild(tr);
    }

    if (!query && filtered.length > limit) {
      const loadMoreTr = document.createElement("tr");
      loadMoreTr.innerHTML = `
        <td colspan="5" style="text-align: center; padding: 14px 0;">
          <button type="button" id="loadMoreCatalogBtn" class="btn btn-secondary btn-sm" style="margin: 0 auto;">
            Showing ${limit} of ${filtered.length} pages · Load More
          </button>
        </td>
      `;
      fragment.appendChild(loadMoreTr);
    }

    catalogTableBody.innerHTML = "";
    catalogTableBody.appendChild(fragment);
  }

  catalogSearchInput.addEventListener("input", () => {
    state.catalogRenderLimit = 100;
    renderCatalogTable();
  });
  refreshCatalogBtn.addEventListener("click", () => {
    fetchSavedPages();
    showToast("Catalog refreshed from disk", "info");
  });

  if (clearCatalogBtn) {
    clearCatalogBtn.addEventListener("click", async () => {
      const outDir = getSelectedOutputDir() || state.defaultOutputDir || "./output";
      if (state.savedPages.length === 0) {
        showToast("No saved pages to clear.", "info");
        return;
      }
      const count = state.savedPages.length;
      const confirmed = confirm(`Are you sure you want to delete all ${count} saved pages from '${outDir}'? This cannot be undone.`);
      if (!confirmed) return;

      try {
        const resp = await fetch("/api/results/clear", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ output_dir: outDir }),
        });
        const data = await resp.json();
        state.savedPages = [];
        renderCatalogTable();
        fetchOutputDirectory();
        if (navPageBadge) navPageBadge.textContent = "0";
        showToast(`Cleared saved pages (${data.deleted_files || 0} files deleted)`, "success");
      } catch (err) {
        showToast(`Failed to clear saved pages: ${err.message}`, "error");
      }
    });
  }

  // =========================================================================
  // Output Storage & Export
  // =========================================================================
  async function fetchOutputDirectory() {
    const outDir = getSelectedOutputDir() || state.defaultOutputDir || "./output";
    if (outputFolderLabel) outputFolderLabel.textContent = outDir;

    const data = await fetchResultsData(outDir);
    if (!data) return;

    if (outputTotalFilesVal) outputTotalFilesVal.textContent = data.total_pages || 0;
    if (outputTotalSizeVal) outputTotalSizeVal.textContent = `${((data.total_bytes || 0) / 1024).toFixed(1)} KB`;
    if (outputManifestVal) outputManifestVal.textContent = data.has_manifest ? "index.json present" : "No manifest";

    if (!outputFileList) return;
    if (!data.pages || data.pages.length === 0) {
      outputFileList.innerHTML = `<p class="empty-hint">No files in directory yet.</p>`;
      return;
    }

    const fragment = document.createDocumentFragment();
    const displayCount = Math.min(data.pages.length, 100);

    for (let i = 0; i < displayCount; i++) {
      const page = data.pages[i];
      const item = document.createElement("div");
      item.className = "file-item-row";
      const fileEsc = escapeHtml(page.file || "");
      item.innerHTML = `
        <div class="file-item-left">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <span>${fileEsc}</span>
        </div>
        <div class="file-item-meta">
          <span>${((page.bytes || 0) / 1024).toFixed(1)} KB</span>
          <button type="button" class="btn btn-secondary btn-sm view-file-btn" data-file="${fileEsc}">View</button>
        </div>
      `;
      fragment.appendChild(item);
    }

    if (data.pages.length > 100) {
      const note = document.createElement("div");
      note.className = "file-item-row";
      note.style.justifyContent = "center";
      note.style.color = "var(--text-muted)";
      note.style.fontSize = "12px";
      note.textContent = `Showing first 100 files of ${data.pages.length} total on disk.`;
      fragment.appendChild(note);
    }

    outputFileList.innerHTML = "";
    outputFileList.appendChild(fragment);
  }

  refreshOutputListBtn.addEventListener("click", () => {
    fetchOutputDirectory();
    showToast("Storage files list refreshed", "info");
  });

  function clearAllClientData() {
    // 1. Reset client application state
    state.savedPages = [];
    state.allLogs = [];
    state.isRunning = false;
    state.catalogRenderLimit = 100;
    if (state.elapsedTimer) {
      clearInterval(state.elapsedTimer);
      state.elapsedTimer = null;
    }
    state.crawlStartTime = null;

    // 2. Clear Live Monitor Telemetry Metrics
    resetVelocity();
    if (monitorCrawledVal) monitorCrawledVal.textContent = "0";
    if (monitorSavedVal) monitorSavedVal.textContent = "0";
    if (monitorSkippedVal) monitorSkippedVal.textContent = "0";
    if (monitorElapsedVal) monitorElapsedVal.textContent = "0.0s";

    // 3. Clear Active URL Ticker Box
    if (monitorDepthTag) monitorDepthTag.textContent = "Depth 0";
    if (monitorUrlText) monitorUrlText.textContent = "Engine idle. Ready to crawl.";

    // 4. Clear Terminal Console & Badges
    if (terminalConsole) {
      terminalConsole.innerHTML = "";
      const initRow = document.createElement("div");
      initRow.className = "log-row log-system";
      initRow.innerHTML = `
        <span class="log-ts">${new Date().toTimeString().slice(0, 8)}</span>
        <span class="log-tag">SYSTEM</span>
        <span class="log-content">Crawler engine initialized and ready.</span>
      `;
      terminalConsole.appendChild(initRow);
    }
    if (terminalCounter) terminalCounter.textContent = "0 logs";
    if (navLogBadge) navLogBadge.textContent = "0";

    // 5. Clear Saved Pages Catalog & Badge
    if (catalogSearchInput) catalogSearchInput.value = "";
    renderCatalogTable();
    if (catalogTotalCount) catalogTotalCount.textContent = "0";
    if (navPageBadge) navPageBadge.textContent = "0";

    // 6. Clear Output Storage Explorer
    if (outputTotalFilesVal) outputTotalFilesVal.textContent = "0";
    if (outputTotalSizeVal) outputTotalSizeVal.textContent = "0.0 KB";
    if (outputManifestVal) outputManifestVal.textContent = "None";
    if (outputFileList) {
      outputFileList.innerHTML = '<p class="empty-hint">No files in directory yet.</p>';
    }

    // 7. Clear Media Extractor Catalog & Badge
    state.discoveredMedia = [];
    state.mediaFilter = "";
    const navMediaBadge = document.getElementById("navMediaBadge");
    if (navMediaBadge) {
      navMediaBadge.textContent = "0";
      navMediaBadge.style.display = "none";
    }
    const mediaTotalCountEl = document.getElementById("mediaTotalCount");
    if (mediaTotalCountEl) mediaTotalCountEl.textContent = "0";
    const mediaSearchInput = document.getElementById("mediaSearchInput");
    if (mediaSearchInput) mediaSearchInput.value = "";
    renderMediaTable();

    // 8. Reset Topbar & Sidebar indicators
    if (statusPill) statusPill.className = "status-pill status-idle";
    if (statusText) statusText.textContent = "Idle";
    if (topbarTicker) topbarTicker.style.display = "none";
    if (topbarTickerText) topbarTickerText.textContent = "Starting crawl...";
    if (sidebarPulse) sidebarPulse.className = "pulse-dot";
    if (sidebarStatusText) sidebarStatusText.textContent = "Engine Ready";

    // 8. Reset Action Buttons
    if (globalStartBtn) globalStartBtn.disabled = false;
    if (submitCrawlBtn) submitCrawlBtn.disabled = false;
    if (globalStopBtn) globalStopBtn.disabled = true;

    // 9. Close Preview Drawer if open
    if (previewDrawer && previewDrawer.classList.contains("open")) {
      closePreviewDrawer();
    }
  }

  if (downloadFormatCatalog && downloadFormatOutput) {
    downloadFormatCatalog.addEventListener("change", () => {
      downloadFormatOutput.value = downloadFormatCatalog.value;
    });
    downloadFormatOutput.addEventListener("change", () => {
      downloadFormatCatalog.value = downloadFormatOutput.value;
    });
  }

  function getDownloadFormat() {
    if (downloadFormatCatalog && downloadFormatCatalog.offsetParent !== null) {
      return downloadFormatCatalog.value || "";
    }
    if (downloadFormatOutput && downloadFormatOutput.offsetParent !== null) {
      return downloadFormatOutput.value || "";
    }
    return (downloadFormatCatalog && downloadFormatCatalog.value) ||
           (downloadFormatOutput && downloadFormatOutput.value) || "";
  }

  async function downloadResultsZip() {
    if (state.isRunning) {
      showToast("A crawl job is currently running. Please stop it or wait for completion before downloading.", "warn");
      return;
    }

    const outDir = getSelectedOutputDir() || state.defaultOutputDir || "./output";

    const btns = [downloadZipBtn, downloadZipCatalogBtn].filter(Boolean);
    const origHtmls = btns.map((b) => b.innerHTML);
    btns.forEach((b) => {
      b.disabled = true;
      b.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        <span>Downloading...</span>
      `;
    });
    const downloadFormat = getDownloadFormat();
    const formatLabel = downloadFormat ? ` as ${downloadFormat.toUpperCase()}` : "";
    showToast(`Generating ZIP archive download${formatLabel}...`, "info");

    try {
      let downloadUrl = `/api/results/download?output_dir=${encodeURIComponent(outDir)}`;
      if (downloadFormat) downloadUrl += `&format=${encodeURIComponent(downloadFormat)}`;

      // Verify server is ready to build and serve the archive
      const checkResp = await fetch(downloadUrl, { method: "HEAD" });
      if (!checkResp.ok) {
        const errResp = await fetch(downloadUrl);
        let errorMsg = `HTTP ${errResp.status}`;
        try {
          const errData = await errResp.json();
          if (errData.error) errorMsg = errData.error;
        } catch (_) {}
        throw new Error(errorMsg);
      }

      // Stream download directly through the browser's native download manager.
      // This avoids memory bloat and prevents .crdownload truncation/failure caused by revoked blob URLs.
      const downloadLink = document.createElement("a");
      downloadLink.style.display = "none";
      downloadLink.href = downloadUrl;
      downloadLink.setAttribute("download", "");
      document.body.appendChild(downloadLink);
      downloadLink.click();
      setTimeout(() => downloadLink.remove(), 1000);

      showToast("ZIP download started successfully!", "success");
    } catch (err) {
      showToast(`Download failed: ${err.message}`, "error");
    } finally {
      btns.forEach((b, i) => {
        b.disabled = false;
        b.innerHTML = origHtmls[i];
      });
    }
  }

  if (downloadZipBtn) {
    downloadZipBtn.addEventListener("click", downloadResultsZip);
  }
  if (downloadZipCatalogBtn) {
    downloadZipCatalogBtn.addEventListener("click", downloadResultsZip);
  }

  clearOutputBtn.addEventListener("click", async () => {
    const confirmed = confirm("Are you sure you want to delete all scraped files in the output directory?");
    if (!confirmed) return;

    const outDir = getSelectedOutputDir() || state.defaultOutputDir || "./output";
    try {
      const resp = await fetch("/api/results/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ output_dir: outDir }),
      });
      const data = await resp.json();
      clearAllClientData();
      showToast(`Purged output folder (${data.deleted_files} files deleted)`, "info");
    } catch (err) {
      showToast(`Failed to clear folder: ${err.message}`, "error");
    }
  });

  // =========================================================================
  // Document Slide-Over Preview Drawer
  // =========================================================================
  let lastFocusedDrawerElement = null;

  async function openPreviewDrawer(filename, pageUrl = "", title = "", depth = 0) {
    lastFocusedDrawerElement = document.activeElement;
    const outDir = getSelectedOutputDir();
    if (!outDir) {
      showToast("Choose a folder with Browse to open saved files.", "warn");
      return;
    }

    drawerFileName.textContent = filename;
    drawerTitle.textContent = title || filename;
    drawerDepth.textContent = `Depth ${depth ?? 0}`;
    drawerUrl.href = pageUrl || "#";
    drawerUrl.textContent = pageUrl || filename;
    drawerContent.textContent = "Loading file content from disk...";
    drawerFileSize.textContent = "...";
    drawerLineCount.textContent = "...";

    drawerOverlay.hidden = false;
    previewDrawer.removeAttribute("inert");
    previewDrawer.classList.add("open");
    previewDrawer.setAttribute("aria-hidden", "false");

    setTimeout(() => {
      if (closeDrawerBtn) closeDrawerBtn.focus();
    }, 50);

    try {
      const resp = await fetch(`/api/results/file?file=${encodeURIComponent(filename)}&output_dir=${encodeURIComponent(outDir)}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
      const data = await resp.json();

      drawerContent.textContent = data.content || "[Empty file content]";
      drawerFileSize.textContent = `${((data.bytes || 0) / 1024).toFixed(1)} KB`;
      drawerLineCount.textContent = data.lines || 0;
    } catch (err) {
      drawerContent.textContent = `Failed to preview page: ${err.message}`;
    }
  }

  function closePreviewDrawer() {
    previewDrawer.classList.remove("open");
    previewDrawer.setAttribute("aria-hidden", "true");
    previewDrawer.setAttribute("inert", "");
    drawerOverlay.hidden = true;
    if (lastFocusedDrawerElement && typeof lastFocusedDrawerElement.focus === "function") {
      lastFocusedDrawerElement.focus();
    }
  }

  closeDrawerBtn.addEventListener("click", closePreviewDrawer);
  drawerOverlay.addEventListener("click", closePreviewDrawer);

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (previewDrawer.classList.contains("open")) {
        closePreviewDrawer();
      } else if (sidebar.classList.contains("mobile-open")) {
        closeMobileSidebar();
      }
    }
  });

  drawerCopyBtn.addEventListener("click", async () => {
    const text = drawerContent.textContent;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      drawerCopyText.textContent = "Copied!";
      setTimeout(() => (drawerCopyText.textContent = "Copy Content"), 1800);
      showToast("Content copied to clipboard", "success");
    } catch {
      showToast("Clipboard copy failed", "error");
    }
  });

  // =========================================================================
  // 1-Click Scraping Presets / Recipes
  // =========================================================================
  const recipes = {
    rag: {
      format: "md",
      depth: 2,
      maxPages: 150,
      sameDomain: true,
      selector: "article, main, .content, #content",
      excludeSelector: "nav, footer, .ad, aside, .cookie-banner, .sidebar",
      chunkSize: 1500,
      chunkOverlap: 250,
      includePattern: "",
      excludePattern: "*.pdf, *.zip, *.jpg, *.png",
    },
    catalog: {
      format: "json",
      depth: 2,
      maxPages: 200,
      sameDomain: true,
      selector: ".product-item, .item, .catalog, main",
      excludeSelector: ".cart, .checkout, .account, nav, footer",
      chunkSize: 0,
      chunkOverlap: 200,
      includePattern: "*/product/*, */item/*, */catalogue/*",
      excludePattern: "*cart*, *checkout*, *login*",
    },
    seedsonly: {
      format: "txt",
      depth: 0,
      maxPages: 50,
      sameDomain: false,
      selector: "",
      excludeSelector: "",
      chunkSize: 0,
      chunkOverlap: 200,
      includePattern: "",
      excludePattern: "",
    },
    deepdocs: {
      format: "md",
      depth: 3,
      maxPages: 300,
      sameDomain: true,
      selector: "article, main, .markdown-body, .documentation",
      excludeSelector: "nav, aside, .sidebar, .footer",
      chunkSize: 1800,
      chunkOverlap: 300,
      includePattern: "*/docs/*, */guide/*",
      excludePattern: "*login*, *.pdf",
    },
  };

  applyRecipeBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const presetKey = btn.getAttribute("data-preset");
      const recipe = recipes[presetKey];
      if (!recipe) return;

      // Apply Format
      formatInput.value = recipe.format;
      formatCards.forEach((card) => {
        card.classList.toggle("active", card.getAttribute("data-format") === recipe.format);
      });

      // Apply Limits & Scope
      depthInput.value = recipe.depth;
      depthInput.setAttribute("aria-valuenow", String(recipe.depth));
      depthInput.setAttribute("aria-valuetext", depthDescriptions[recipe.depth] || `Depth ${recipe.depth}`);
      depthDisplay.textContent = String(recipe.depth);
      depthHint.textContent = depthDescriptions[recipe.depth] || `Depth level ${recipe.depth}`;

      maxPagesInput.value = recipe.maxPages;
      document.querySelectorAll(".preset-pill[data-pages]").forEach((p) => {
        p.classList.toggle("active", p.getAttribute("data-pages") === String(recipe.maxPages));
      });

      sameDomainInput.checked = recipe.sameDomain;
      selectorInput.value = recipe.selector;
      excludeSelectorInput.value = recipe.excludeSelector;
      if (schemaInput) schemaInput.value = recipe.schema || "";
      chunkSizeInput.value = recipe.chunkSize;
      chunkOverlapInput.value = recipe.chunkOverlap;
      includePatternInput.value = recipe.includePattern;
      excludePatternInput.value = recipe.excludePattern;

      updateSetupSummary();
      showToast(`Applied preset recipe: ${btn.closest(".recipe-card").querySelector("h3").textContent}`, "success");
      switchView("viewCrawlSetup");
    });
  });

  // =========================================================================
  // HTML Escaping Helper
  // =========================================================================
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // =========================================================================
  // Delegated Table & File List Click Handlers
  // =========================================================================
  if (catalogTableBody) {
    catalogTableBody.addEventListener("click", (e) => {
      const loadBtn = e.target.closest("#loadMoreCatalogBtn");
      if (loadBtn) {
        state.catalogRenderLimit = (state.catalogRenderLimit || 100) + 200;
        renderCatalogTable();
        return;
      }
      const previewBtn = e.target.closest(".preview-btn");
      if (!previewBtn) return;
      const file = previewBtn.dataset.file;
      const page = state.savedPages.find((p) => p.file === file);
      if (page) {
        openPreviewDrawer(page.file, page.url, page.title, page.depth);
      } else if (file) {
        openPreviewDrawer(file, "", file, 0);
      }
    });
  }

  if (outputFileList) {
    outputFileList.addEventListener("click", (e) => {
      const btn = e.target.closest(".view-file-btn");
      if (!btn) return;
      const file = btn.dataset.file;
      const page = state.savedPages.find((p) => p.file === file);
      if (page) {
        openPreviewDrawer(page.file, page.url, page.title, page.depth);
      } else if (file) {
        openPreviewDrawer(file, "", file, 0);
      }
    });
  }

  // Synchronize ARIA state on switches
  [sameDomainInput, respectRobotsInput, inspectorJsToggle, terminalAutoScroll].forEach((toggle) => {
    if (!toggle) return;
    toggle.addEventListener("change", () => {
      toggle.setAttribute("aria-checked", String(toggle.checked));
    });
  });

  // =========================================================================
  // Media Extractor UI Logic
  // =========================================================================
  let mediaRenderDebounceTimer = null;
  function scheduleMediaRender() {
    if (mediaRenderDebounceTimer) return;
    mediaRenderDebounceTimer = setTimeout(() => {
      mediaRenderDebounceTimer = null;
      renderMediaTable();
    }, 120);
  }

  function addDiscoveredMedia(items) {
    if (!items || !items.length) return;
    const seen = new Set(state.discoveredMedia.map((m) => m.media_url));
    let hasNew = false;
    for (const item of items) {
      if (!seen.has(item.media_url)) {
        seen.add(item.media_url);
        state.discoveredMedia.unshift(item);
        hasNew = true;
      }
    }
    if (!hasNew) return;
    if (state.discoveredMedia.length > 500) {
      state.discoveredMedia = state.discoveredMedia.slice(0, 500);
    }
    const navMediaBadge = document.getElementById("navMediaBadge");
    if (navMediaBadge) {
      navMediaBadge.textContent = state.discoveredMedia.length;
      navMediaBadge.style.display = state.discoveredMedia.length > 0 ? "inline-block" : "none";
    }
    const totalCountEl = document.getElementById("mediaTotalCount");
    if (totalCountEl) totalCountEl.textContent = state.discoveredMedia.length;
    scheduleMediaRender();
  }

  function getBadgeClassForType(type) {
    switch ((type || "").toLowerCase()) {
      case "image": return "badge-image";
      case "pdf": return "badge-pdf";
      case "doc": return "badge-doc";
      case "ppt": return "badge-ppt";
      case "video": return "badge-video";
      default: return "";
    }
  }

  function renderMediaTable() {
    const tableBody = document.getElementById("mediaTableBody");
    if (!tableBody) return;

    const filter = (state.mediaFilter || "").toLowerCase().trim();
    const filtered = state.discoveredMedia.filter((m) => {
      if (!filter) return true;
      return (
        (m.media_url && m.media_url.toLowerCase().includes(filter)) ||
        (m.filename && m.filename.toLowerCase().includes(filter)) ||
        (m.page_url && m.page_url.toLowerCase().includes(filter)) ||
        (m.media_type && m.media_type.toLowerCase().includes(filter))
      );
    });

    if (filtered.length === 0) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="5" class="empty-state">
            ${filter ? "No media assets matched your search filter." : "No media assets discovered yet. Enable Media Extractor and run a crawl."}
          </td>
        </tr>
      `;
      return;
    }

    tableBody.innerHTML = filtered.map((m) => {
      const typeBadge = `<span class="type-badge ${getBadgeClassForType(m.media_type)}">${escapeHtml(m.media_type || "asset")}</span>`;
      const urlText = escapeHtml(m.media_url || "");
      const pageText = escapeHtml(m.page_url || "");
      const filename = escapeHtml(m.filename || "file");
      const statusClass = m.download_status === "downloaded" ? "media-status-downloaded" : (m.download_status === "failed" ? "media-status-failed" : "media-status-discovered");
      const statusLabel = m.download_status || "Discovered";

      return `
        <tr>
          <td>${typeBadge}</td>
          <td class="media-url-cell">
            <a href="${urlText}" target="_blank" rel="noopener noreferrer" class="media-url-link" title="${urlText}">
              ${filename}
            </a>
            <div style="font-size: 10.5px; color: var(--text-muted); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${urlText}</div>
          </td>
          <td class="media-url-cell">
            <a href="${pageText}" target="_blank" rel="noopener noreferrer" style="color: var(--text-secondary); text-decoration: none; font-size: 11px;" title="${pageText}">
              ${pageText}
            </a>
          </td>
          <td><span class="media-status-badge ${statusClass}">${statusLabel}</span></td>
          <td style="text-align: right;">
            <button type="button" class="btn btn-secondary btn-sm copy-media-url-btn" data-url="${urlText}" title="Copy media link">Copy</button>
          </td>
        </tr>
      `;
    }).join("");
  }

  async function fetchMediaCatalog() {
    try {
      const dir = getSelectedOutputDir();
      const resp = await fetch(`/api/media?output_dir=${encodeURIComponent(dir)}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.media && Array.isArray(data.media)) {
        addDiscoveredMedia(data.media);
      }
    } catch (err) {
      console.warn("Could not fetch media catalog:", err);
    }
  }

  function initMediaExtractor() {
    const modeRadios = document.querySelectorAll('input[name="mediaModeOption"]');
    const downloadMediaCheckbox = document.getElementById("downloadMediaFiles");
    modeRadios.forEach((r) => {
      r.addEventListener("change", () => {
        document.querySelectorAll(".media-mode-card").forEach((card) => {
          card.classList.toggle("active", card.contains(r) && r.checked);
        });
        if (r.value === "media-only" && r.checked && downloadMediaCheckbox) {
          downloadMediaCheckbox.checked = true;
        }
      });
    });

    const masterToggle = document.getElementById("enableMediaExtractor");
    if (masterToggle) {
      masterToggle.addEventListener("change", () => {
        if (masterToggle.checked && downloadMediaCheckbox && !downloadMediaCheckbox.checked) {
          downloadMediaCheckbox.checked = true;
        }
      });
    }

    const downloadAllBtn = document.getElementById("downloadAllMediaBtn");
    if (downloadAllBtn) {
      downloadAllBtn.addEventListener("click", async () => {
        const dir = getSelectedOutputDir();
        downloadAllBtn.disabled = true;
        downloadAllBtn.textContent = "Downloading...";
        showToast("Starting download of discovered media files...", "info");

        try {
          const resp = await fetch("/api/media/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ output_dir: dir }),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.error || "Failed to download media");

          showToast(`Downloaded ${data.downloaded} media file(s) to output/media/!`, "success", 4000);
          if (data.media && Array.isArray(data.media)) {
            state.discoveredMedia = data.media;
            renderMediaTable();
          } else {
            fetchMediaCatalog();
          }
          fetchOutputDirectory();
        } catch (err) {
          showToast(`Media download error: ${err.message}`, "error");
        } finally {
          downloadAllBtn.disabled = false;
          downloadAllBtn.textContent = "Download All to Disk";
        }
      });
    }

    const searchInput = document.getElementById("mediaSearchInput");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        state.mediaFilter = e.target.value;
        renderMediaTable();
      });
    }

    const refreshBtn = document.getElementById("refreshMediaBtn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        fetchMediaCatalog();
        showToast("Refreshed media catalog", "info");
      });
    }

    const clearMediaBtn = document.getElementById("clearMediaBtn");
    if (clearMediaBtn) {
      clearMediaBtn.addEventListener("click", async () => {
        const dir = getSelectedOutputDir() || state.defaultOutputDir || "./output";
        if (state.discoveredMedia.length === 0) {
          showToast("No media records to clear.", "info");
          return;
        }

        const count = state.discoveredMedia.length;
        const confirmed = confirm(
          `Are you sure you want to clear media history and delete all saved media files from '${dir}'? This cannot be undone.`
        );
        if (!confirmed) return;

        try {
          const resp = await fetch("/api/media/clear", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ output_dir: dir, delete_files: true }),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.error || "Failed to clear media");

          state.discoveredMedia = [];
          state.mediaFilter = "";
          renderMediaTable();

          const navMediaBadge = document.getElementById("navMediaBadge");
          if (navMediaBadge) {
            navMediaBadge.textContent = "0";
            navMediaBadge.style.display = "none";
          }
          const mediaTotalCountEl = document.getElementById("mediaTotalCount");
          if (mediaTotalCountEl) mediaTotalCountEl.textContent = "0";

          fetchOutputDirectory();
          showToast(`Media history cleared (${data.deleted_files || count} files removed)`, "info");
        } catch (err) {
          showToast(`Error clearing media: ${err.message}`, "error");
        }
      });
    }

    const tableBody = document.getElementById("mediaTableBody");
    if (tableBody) {
      tableBody.addEventListener("click", (e) => {
        const copyBtn = e.target.closest(".copy-media-url-btn");
        if (copyBtn && copyBtn.dataset.url) {
          navigator.clipboard.writeText(copyBtn.dataset.url).then(() => {
            showToast("Copied media URL to clipboard", "success");
          });
        }
      });
    }
  }

  // =========================================================================
  // App Bootstrapping
  // =========================================================================
  async function initEnvironment() {
    try {
      const resp = await fetch("/api/system/info");
      if (!resp.ok) return;
      const info = await resp.json();
      if (!info.container) return;

      state.isContainer = true;
      state.defaultOutputDir = info.default_output_dir || "./output";
      setSelectedOutputDir(state.defaultOutputDir, "Docker volume");

      if (browseDirBtn) {
        browseDirBtn.title = "Docker controls this folder through a mounted volume";
        const label = browseDirBtn.querySelector("span");
        if (label) label.textContent = "Docker volume";
      }
      if (outputDirHint) {
        outputDirHint.textContent = info.output_dir_note || "Saved to the mounted output volume";
      }
    } catch (err) {
      console.warn("Failed to load environment info:", err);
    }
  }

  // Defensively ensure the root browser window is never scrolled out of position.
  // The viewport is fixed and only internal scroll containers (like .workspace) scroll.
  window.addEventListener("scroll", () => {
    if (window.scrollX !== 0 || window.scrollY !== 0) {
      window.scrollTo(0, 0);
    }
  }, { passive: true });

  initTheme();
  initSidebarState();
  initMediaExtractor();
  updateDlqVisibility();
  updateSetupSummary();
  initEnvironment().finally(() => {
    fetchSavedPages();
    fetchMediaCatalog();
    fetchOutputDirectory();
    initSSE();
  });

  // Load view from hash if present
  const initialHash = window.location.hash.replace("#", "");
  if (initialHash && document.getElementById(initialHash)) {
    switchView(initialHash, false);
  }
})();
