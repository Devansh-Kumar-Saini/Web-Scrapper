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
  const impersonateInput = document.getElementById("impersonateInput");
  const proxyInput = document.getElementById("proxyInput");
  const webhookUrlInput = document.getElementById("webhookUrlInput");
  const outputDirInput = document.getElementById("outputDirInput");
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
  const inspectorLiveToggle = document.getElementById("inspectorLiveToggle");
  const inspectorSelectorStatus = document.getElementById("inspectorSelectorStatus");
  const inspectorWordCount = document.getElementById("inspectorWordCount");
  const inspectorUseSetupBtn = document.getElementById("inspectorUseSetupBtn");

  // Live Monitor & Console
  const monitorCrawledVal = document.getElementById("monitorCrawledVal");
  const monitorSavedVal = document.getElementById("monitorSavedVal");
  const monitorSkippedVal = document.getElementById("monitorSkippedVal");
  const monitorElapsedVal = document.getElementById("monitorElapsedVal");
  const monitorDepthTag = document.getElementById("monitorDepthTag");
  const monitorUrlText = document.getElementById("monitorUrlText");
  const terminalConsole = document.getElementById("terminalConsole");
  const terminalCounter = document.getElementById("terminalCounter");
  const terminalAutoScroll = document.getElementById("terminalAutoScroll");
  const terminalClearBtn = document.getElementById("terminalClearBtn");
  const levelPills = document.querySelectorAll(".level-pill");

  // Saved Pages Catalog
  const catalogTableBody = document.getElementById("catalogTableBody");
  const catalogSearchInput = document.getElementById("catalogSearchInput");
  const catalogTotalCount = document.getElementById("catalogTotalCount");
  const refreshCatalogBtn = document.getElementById("refreshCatalogBtn");
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
    const saved = localStorage.getItem("scrapper_theme");
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = saved || (prefersDark ? "dark" : "light");
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
    const sitemapText = sitemapActive ? " · Sitemap" : "";
    setupSummary.textContent = `${count} seed(s) · Depth ${depth} · Max ${maxPages} pages · ${concurrency} workers · ${delay}s delay${sitemapText} · ${domainMsg} · ${format}`;
  }

  urlInput.addEventListener("input", updateSetupSummary);
  sameDomainInput.addEventListener("change", updateSetupSummary);
  if (sitemapInput) sitemapInput.addEventListener("change", updateSetupSummary);

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
    try {
      browseDirBtn.disabled = true;
      browseDirBtn.innerHTML = `<span>Browsing...</span>`;
      const resp = await fetch("/api/system/pick-folder", { method: "POST" });
      const data = await resp.json();

      if (data.canceled) {
        // User closed picker dialog without selecting
        return;
      }

      if (data.is_cloud) {
        showToast(data.message, "warn", 4500);
        if (outputDirInput) outputDirInput.value = data.path || "./output";
        return;
      }

      if (data.path) {
        if (outputDirInput) outputDirInput.value = data.path;
        if (sidebarOutputLabel) {
          sidebarOutputLabel.textContent = data.path.length > 18 ? "..." + data.path.slice(-16) : data.path;
        }
        showToast(`Output location selected: ${data.path}`, "success");
      } else if (data.error) {
        showToast(data.error, "error");
      }
    } catch (err) {
      showToast(`Folder selection failed: ${err.message}`, "error");
    } finally {
      browseDirBtn.disabled = false;
      browseDirBtn.innerHTML = `
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>
        </svg>
        Browse Folder
      `;
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
    if (concurrencyInput) concurrencyInput.value = 5;
    document.querySelectorAll(".preset-pill[data-concurrency]").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-concurrency") === "5");
    });
    if (delayInput) delayInput.value = 0.2;
    document.querySelectorAll(".preset-pill[data-delay]").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-delay") === "0.2");
    });
    sameDomainInput.checked = true;
    respectRobotsInput.checked = true;
    if (sitemapInput) sitemapInput.checked = false;
    if (sitemapUrlInput) sitemapUrlInput.value = "";
    if (outputDirInput) outputDirInput.value = "./output";
    if (webhookUrlInput) webhookUrlInput.value = "";
    selectorInput.value = "";
    excludeSelectorInput.value = "";
    chunkSizeInput.value = 0;
    chunkOverlapInput.value = 200;
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

  async function startCrawlJob() {
    if (state.isRunning) return;

    const urlsRaw = urlInput.value.trim();
    if (!urlsRaw) {
      showToast("Please enter at least one target URL in Crawl Setup.", "warn");
      switchView("viewCrawlSetup");
      urlInput.focus();
      return;
    }

    const depth = parseInt(depthInput.value, 10);
    const maxPages = parseInt(maxPagesInput.value, 10);
    const sameDomain = sameDomainInput.checked;
    const respectRobots = respectRobotsInput.checked;
    const outputDir = (outputDirInput ? outputDirInput.value.trim() : "") || "./output";
    const format = formatInput.value || "md";
    const targetSelector = selectorInput.value.trim();
    const excludeSelectors = excludeSelectorInput.value.trim();
    const chunkSize = parseInt(chunkSizeInput.value, 10) || 0;
    const chunkOverlap = parseInt(chunkOverlapInput.value, 10) || 200;
    const includePatterns = includePatternInput.value.trim();
    const excludePatterns = excludePatternInput.value.trim();
    const concurrency = concurrencyInput ? (parseInt(concurrencyInput.value, 10) || 5) : 5;
    const delay = delayInput ? (parseFloat(delayInput.value) >= 0 ? parseFloat(delayInput.value) : 0.2) : 0.2;
    const sitemap = sitemapInput ? sitemapInput.checked : false;
    const sitemapUrl = sitemapUrlInput ? sitemapUrlInput.value.trim() : "";
    const impersonate = impersonateInput ? impersonateInput.value : "chrome";
    const proxy = proxyInput ? proxyInput.value.trim() : "";
    const webhookUrl = webhookUrlInput ? webhookUrlInput.value.trim() : "";

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
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          include_patterns: includePatterns,
          exclude_patterns: excludePatterns,
          concurrency,
          delay,
          sitemap,
          sitemap_url: sitemapUrl,
          impersonate,
          proxy,
          webhook_url: webhookUrl,
        }),
      });

      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || "Failed to start crawler");
      }

      showToast("Crawl job started successfully!", "success");
      updateStatus("running");

      // Auto-switch to Live Monitor so user can watch progress immediately
      switchView("viewMonitor");
    } catch (err) {
      showToast(err.message, "error");
      updateStatus("idle");
    } finally {
      setLaunchState(false);
    }
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
      showToast("Stopping crawl gracefully...", "warn");
      updateStatus("stopping");
    } catch (err) {
      showToast(err.message, "error");
      globalStopBtn.disabled = false;
    }
  });

  // Status updates
  function updateStatus(status, errorMsg = "") {
    statusPill.className = `status-pill status-${status}`;
    const labels = {
      idle: "Idle",
      running: "Crawling...",
      stopping: "Stopping...",
      completed: "Completed",
      failed: "Failed",
    };
    statusText.textContent = labels[status] || status;

    if (status === "running") {
      state.isRunning = true;
      globalStartBtn.disabled = true;
      submitCrawlBtn.disabled = true;
      globalStopBtn.disabled = false;
      topbarTicker.style.display = "flex";
      sidebarPulse.className = "pulse-dot pulsing";
      sidebarStatusText.textContent = "Crawl in Progress";

      if (!state.elapsedTimer) {
        state.crawlStartTime = Date.now();
        state.elapsedTimer = setInterval(updateElapsedTimer, 200);
      }
    } else {
      state.isRunning = false;
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

      if (status === "completed") {
        monitorDepthTag.textContent = "Finished";
        monitorUrlText.textContent = "All pages crawled and saved to output folder.";
        showToast("Crawl finished successfully!", "success");
        fetchSavedPages();
        fetchOutputDirectory();
      } else if (status === "failed") {
        monitorDepthTag.textContent = "Error";
        monitorUrlText.textContent = errorMsg || "Crawl ended due to an error.";
        showToast(errorMsg || "Crawl job failed", "error");
      }
    }
  }

  function updateElapsedTimer() {
    if (!state.crawlStartTime) return;
    const sec = ((Date.now() - state.crawlStartTime) / 1000).toFixed(1);
    monitorElapsedVal.textContent = `${sec}s`;
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

    state.eventSource.addEventListener("reset", () => {
      clearAllClientData();
    });

    state.eventSource.onerror = () => {
      // Browser EventSource automatically handles reconnection
    };
  }

  function syncSnapshot(snap) {
    if (!snap) return;
    applyStats(snap);

    if (snap.logs && Array.isArray(snap.logs) && state.allLogs.length === 0) {
      for (const log of snap.logs) {
        appendLogEntry(log);
      }
    }

    if (snap.recent_pages && Array.isArray(snap.recent_pages)) {
      for (const p of snap.recent_pages) {
        addSavedPage(p);
      }
    }

    updateStatus(snap.status || "idle", snap.error_message);
  }

  function applyStats(snap) {
    if (monitorCrawledVal) monitorCrawledVal.textContent = snap.pages_crawled ?? 0;
    if (monitorSavedVal) monitorSavedVal.textContent = snap.pages_saved ?? 0;
    if (monitorSkippedVal) monitorSkippedVal.textContent = snap.pages_skipped ?? 0;
    if (monitorElapsedVal) {
      const elapsed = snap.elapsed_seconds ?? 0;
      monitorElapsedVal.textContent = `${elapsed}s`;
    }

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
  function appendLogEntry(entry) {
    state.allLogs.push(entry);
    if (state.allLogs.length > 600) state.allLogs.shift();

    navLogBadge.textContent = state.allLogs.length;
    terminalCounter.textContent = `${state.allLogs.length} logs`;

    if (state.currentLogFilter === "ALL" || entry.level === state.currentLogFilter) {
      renderLogDOM(entry);
    }
  }

  function renderLogDOM(entry) {
    const row = document.createElement("div");
    const lvl = (entry.level || "INFO").toLowerCase();
    row.className = `log-row log-${lvl}`;

    const ts = document.createElement("span");
    ts.className = "log-ts";
    ts.textContent = entry.time || new Date().toTimeString().slice(0, 8);

    const tag = document.createElement("span");
    tag.className = "log-tag";
    tag.textContent = entry.level || "INFO";

    const content = document.createElement("span");
    content.className = "log-content";
    content.textContent = entry.message || "";

    row.appendChild(ts);
    row.appendChild(tag);
    row.appendChild(content);
    terminalConsole.appendChild(row);

    if (terminalAutoScroll.checked) {
      terminalConsole.scrollTop = terminalConsole.scrollHeight;
    }
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
    terminalConsole.innerHTML = "";
    for (const entry of state.allLogs) {
      if (state.currentLogFilter === "ALL" || entry.level === state.currentLogFilter) {
        renderLogDOM(entry);
      }
    }
  }

  terminalClearBtn.addEventListener("click", () => {
    state.allLogs = [];
    terminalConsole.innerHTML = "";
    navLogBadge.textContent = "0";
    terminalCounter.textContent = "0 logs";
    showToast("Terminal logs cleared", "info", 1500);
  });

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
  // Saved Pages Catalog
  // =========================================================================
  function addSavedPage(page) {
    const existing = state.savedPages.findIndex((p) => p.file === page.file);
    if (existing >= 0) {
      state.savedPages[existing] = page;
    } else {
      state.savedPages.unshift(page);
    }
    navPageBadge.textContent = state.savedPages.length;
    renderCatalogTable();
  }

  async function fetchSavedPages() {
    const outDir = (outputDirInput ? outputDirInput.value.trim() : "") || "./output";
    try {
      const resp = await fetch(`/api/results?output_dir=${encodeURIComponent(outDir)}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.pages && Array.isArray(data.pages)) {
        state.savedPages = data.pages;
        navPageBadge.textContent = state.savedPages.length;
        renderCatalogTable();
      }
    } catch (err) {
      console.warn("Failed to fetch saved pages:", err);
    }
  }

  function renderCatalogTable() {
    const query = catalogSearchInput.value.trim().toLowerCase();
    const filtered = state.savedPages.filter((page) => {
      if (!query) return true;
      return (
        (page.title && page.title.toLowerCase().includes(query)) ||
        (page.url && page.url.toLowerCase().includes(query)) ||
        (page.file && page.file.toLowerCase().includes(query))
      );
    });

    catalogTotalCount.textContent = state.savedPages.length;
    catalogTableBody.innerHTML = "";

    if (filtered.length === 0) {
      const tr = document.createElement("tr");
      tr.className = "empty-state-row";
      tr.innerHTML = `
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
      `;
      catalogTableBody.appendChild(tr);
      return;
    }

    filtered.forEach((page) => {
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

      tr.querySelector(".preview-btn").addEventListener("click", () => {
        openPreviewDrawer(page.file, page.url, page.title, page.depth);
      });

      catalogTableBody.appendChild(tr);
    });
  }

  catalogSearchInput.addEventListener("input", renderCatalogTable);
  refreshCatalogBtn.addEventListener("click", () => {
    fetchSavedPages();
    showToast("Catalog refreshed from disk", "info");
  });

  // =========================================================================
  // Output Storage & Export
  // =========================================================================
  async function fetchOutputDirectory() {
    const outDir = (outputDirInput ? outputDirInput.value.trim() : "") || "./output";
    if (outputFolderLabel) outputFolderLabel.textContent = outDir;

    try {
      const resp = await fetch(`/api/results?output_dir=${encodeURIComponent(outDir)}`);
      if (!resp.ok) return;
      const data = await resp.json();

      outputTotalFilesVal.textContent = data.total_pages || 0;
      outputTotalSizeVal.textContent = `${((data.total_bytes || 0) / 1024).toFixed(1)} KB`;
      outputManifestVal.textContent = data.has_manifest ? "index.json present" : "No manifest";

      outputFileList.innerHTML = "";
      if (!data.pages || data.pages.length === 0) {
        outputFileList.innerHTML = `<p class="empty-hint">No files in directory yet.</p>`;
        return;
      }

      data.pages.forEach((page) => {
        const item = document.createElement("div");
        item.className = "file-item-row";
        item.innerHTML = `
          <div class="file-item-left">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            <span>${escapeHtml(page.file)}</span>
          </div>
          <div class="file-item-meta">
            <span>${((page.bytes || 0) / 1024).toFixed(1)} KB</span>
            <button type="button" class="btn btn-secondary btn-sm view-file-btn" data-file="${escapeHtml(page.file)}">View</button>
          </div>
        `;
        item.querySelector(".view-file-btn").addEventListener("click", () => {
          openPreviewDrawer(page.file, page.url, page.title, page.depth);
        });
        outputFileList.appendChild(item);
      });
    } catch (err) {
      console.warn("Failed to load output directory:", err);
    }
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
    if (state.elapsedTimer) {
      clearInterval(state.elapsedTimer);
      state.elapsedTimer = null;
    }
    state.crawlStartTime = null;

    // 2. Clear Live Monitor Telemetry Metrics
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

    // 7. Reset Topbar & Sidebar indicators
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

  function getDownloadFormat() {
    const selects = [downloadFormatCatalog, downloadFormatOutput].filter(Boolean);
    const visible = selects.find((select) => select.offsetParent !== null);
    const active = visible || selects[0];
    return active ? active.value || "" : "";
  }

  async function downloadResultsZip() {
    if (state.isRunning) {
      showToast("A crawl job is currently running. Please stop it or wait for completion before downloading.", "warn");
      return;
    }

    const outDir = (outputDirInput ? outputDirInput.value.trim() : "") || "./output";
    const totalFiles = parseInt(outputTotalFilesVal ? outputTotalFilesVal.textContent : "0", 10) || 0;
    if (state.savedPages.length === 0 && totalFiles === 0) {
      showToast("No files found in output directory to download.", "warn");
      return;
    }

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
      const resp = await fetch(downloadUrl);
      if (!resp.ok) {
        let errorMsg = `HTTP ${resp.status}`;
        try {
          const errData = await resp.json();
          if (errData.error) errorMsg = errData.error;
        } catch (_) {}
        throw new Error(errorMsg);
      }

      let filename = `scraped_pages_${Date.now()}.zip`;
      const disposition = resp.headers.get("content-disposition") || resp.headers.get("Content-Disposition");
      if (disposition && disposition.includes("filename=")) {
        const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
        if (match && match[1]) {
          filename = match[1].replace(/['"]/g, "").trim();
        }
      }

      const blob = await resp.blob();
      const blobUrl = URL.createObjectURL(blob);
      const downloadLink = document.createElement("a");
      downloadLink.href = blobUrl;
      downloadLink.download = filename;
      document.body.appendChild(downloadLink);
      downloadLink.click();
      downloadLink.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);

      // Once the user downloads the zip file, clear all the Live Monitor and Saved Pages, etc
      try {
        await fetch("/api/results/clear", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ output_dir: outDir }),
        });
      } catch (clearErr) {
        console.warn("Failed to clear server results:", clearErr);
      }

      clearAllClientData();
      showToast("ZIP downloaded. Live Monitor, Saved Pages, and storage have been cleared.", "success");
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

    const outDir = (outputDirInput ? outputDirInput.value.trim() : "") || "./output";
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
    const outDir = (outputDirInput ? outputDirInput.value.trim() : "") || "./output";

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
  // App Bootstrapping
  // =========================================================================
  initTheme();
  initSidebarState();
  updateSetupSummary();
  fetchSavedPages();
  fetchOutputDirectory();
  initSSE();

  // Load view from hash if present
  const initialHash = window.location.hash.replace("#", "");
  if (initialHash && document.getElementById(initialHash)) {
    switchView(initialHash, false);
  }
})();

  // Synchronize ARIA state on switches
  [sameDomainInput, respectRobotsInput, inspectorJsToggle, terminalAutoScroll].forEach((toggle) => {
    if (!toggle) return;
    toggle.addEventListener("change", () => {
      toggle.setAttribute("aria-checked", String(toggle.checked));
    });
  });
