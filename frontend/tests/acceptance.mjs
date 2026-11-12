import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const project = path.dirname(frontend),
  backend = path.join(project, "backend");
const python =
  process.env.TUNA_TEST_PYTHON || path.join(project, ".venv", "bin", "python");
const data = fs.mkdtempSync(path.join(os.tmpdir(), "endless-tuna-acceptance-"));
const artifacts = path.join(project, "var", "acceptance");
fs.mkdirSync(artifacts, { recursive: true });
const apiBase = `http://127.0.0.1:${process.env.TUNA_ACCEPTANCE_PORT || 8021}`;
const base = `http://127.0.0.1:${process.env.TUNA_ACCEPTANCE_UI_PORT || 8022}`;
const env = {
  ...process.env,
  PYTHONPATH: backend,
  TUNA_API_PORT: new URL(apiBase).port,
  TUNA_DATA_DIR: data,
  LAS_API_KEY: "",
  OPENAI_KEY: "",
  LAS_MODEL: "",
  TUNA_SEARCH_ENDPOINT: "",
  TUNA_DOWNLOAD_CONCURRENCY: "1",
};
const report = {
  started_utc: new Date().toISOString(),
  mode: "isolated fictional demo; collection transport mocked; no LAS credentials",
  data_directory: data,
  checks: [],
  console_errors: [],
  external_requests: [],
  las_requests: 0,
};
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
let server, frontendServer, worker, browser, page;
function launch(args, name) {
  const fd = fs.openSync(path.join(data, name + ".log"), "a");
  const child = spawn(python, args, {
    cwd: backend,
    env,
    stdio: ["ignore", fd, fd],
  });
  fs.closeSync(fd);
  return child;
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([new Promise((r) => child.once("exit", r)), delay(4000)]);
  if (child.exitCode === null) {
    child.kill("SIGKILL");
    await delay(100);
  }
}
async function ready(url = apiBase) {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(url + "/api/health")).ok) return;
    } catch {}
    await delay(200);
  }
  throw Error(
    "Local acceptance server failed to start; inspect " + data + "/server.log",
  );
}
async function api(p, body, collection = "demo") {
  const response = await fetch(base + "/api" + p, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-Collection": collection },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  assert.ok(response.ok, JSON.stringify(result));
  return result;
}
async function until(fn, message) {
  for (let i = 0; i < 120; i++) {
    if (await fn()) return;
    await delay(150);
  }
  throw Error(message);
}
async function check(name, fn) {
  try {
    const detail = await fn();
    report.checks.push({ name, status: "Passed", detail: detail ?? null });
    console.log("Passed: " + name);
  } catch (e) {
    report.checks.push({ name, status: "Failed", detail: e.message });
    throw e;
  }
}
function csv(rows) {
  return [
    "title,authors,official_url,inventory_url,year,track,pdf_url",
    ...rows.map(([title, id, pdf]) =>
      [
        title,
        JSON.stringify(["Fixture Researcher"]),
        `https://fixtures.example/papers/${id}`,
        "https://fixtures.example/inventory",
        2025,
        "Main research track",
        `https://fixtures.example/${pdf}`,
      ]
        .map((v) => '"' + String(v).replaceAll('"', '""') + '"')
        .join(","),
    ),
  ].join("\n");
}
async function importInventory(rows) {
  await page.goto(base + "/#/conferences/harbor?collection=demo");
  await page.getByText("Import a CSV paper inventory", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "CSV inventory text", exact: true })
    .fill(csv(rows));
  await page
    .getByRole("button", {
      name: "Import inventory & queue collection",
      exact: true,
    })
    .click();
  await page
    .getByRole("heading", { name: "Collection jobs", exact: true })
    .waitFor();
}
try {
  const setup = spawnSync(python, ["tests/acceptance_fixture.py", "prepare"], {
    cwd: backend,
    env,
    encoding: "utf8",
  });
  assert.equal(setup.status, 0, setup.stderr);
  server = launch(
    [
      "-m",
      "uvicorn",
      "endless_tuna.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      new URL(apiBase).port,
    ],
    "server",
  );
  await ready();
  const viteLog = fs.openSync(path.join(data, "vite.log"), "a");
  frontendServer = spawn(process.execPath, [path.join(frontend,"node_modules/vite/bin/vite.js"),"--host","127.0.0.1","--port",new URL(base).port,"--strictPort"], {cwd:frontend,env,stdio:["ignore",viteLog,viteLog]});
  fs.closeSync(viteLog);
  await ready(base);
  report.frontend_transport = "Actual Vite development proxy; browser Origin and Host preserved";
  worker = launch(["tests/acceptance_fixture.py", "worker"], "worker");
  const executables = [
    process.env.CHROME_EXECUTABLE,
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].filter(Boolean);
  const executablePath = executables.find((p) => fs.existsSync(p));
  browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
    args: process.platform === "linux" ? ["--no-sandbox"] : [],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1024 },
  });
  await context.route("**/*", async route => {
    const origin = new URL(route.request().url()).origin;
    if (origin === new URL(base).origin) return route.continue();
    report.external_requests.push(origin);
    return route.abort();
  });
  page = await context.newPage();
  page.on("pageerror", (e) => report.console_errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().includes("favicon"))
      report.console_errors.push(m.text());
  });
  await page.route("**/api/las/**", (r) => {
    report.las_requests++;
    return r.abort();
  });
  await check("0. Browser POST through the real Vite proxy preserves local Origin", async () => {
    await page.goto(base + "/#/add?collection=real");
    const response = await page.evaluate(async () => {
      const r = await fetch("/api/intake/preview", {method:"POST",headers:{"Content-Type":"application/json","X-Collection":"real"},body:JSON.stringify({url:"http://localhost/"})});
      return {status:r.status,body:await r.json()};
    });
    assert.equal(response.status,200);
    assert.equal(response.body.ok,false);
    const foreign = await page.request.post(base + "/api/intake/preview", {headers:{Origin:"https://foreign.invalid","Sec-Fetch-Site":"cross-site"},data:{url:"http://localhost/"}});
    assert.equal(foreign.status(),403);
    return "Real browser/Vite/API round trip accepted; unsafe source rejected without fetching. Foreign-origin POST still blocked.";
  });
  let savedSearch;
  await check("1. Clearly labeled demo and operation without LAS", async () => {
    await page.goto(base + "/#/?collection=demo");
    await page.locator(".conference-card").first().waitFor();
    assert.equal(
      await page.getByLabel("Collection", { exact: true }).inputValue(),
      "demo",
    );
    assert.ok(
      await page
        .getByText("Demo data · fictional research", { exact: true })
        .isVisible(),
    );
    const settings = await api("/settings");
    assert.equal(settings.las.credentials_configured, false);
    return "Demo and real databases isolated; LAS credentials explicitly empty.";
  });
  await check(
    "2. Keyboard search, filters, URL state, phrases, pagination and history",
    async () => {
      await page.mouse.click(1400, 160);
      for (let i = 0; i < 30; i++) {
        await page.keyboard.press("Tab");
        if (
          await page.evaluate(
            () =>
              document.activeElement?.getAttribute("aria-label") ===
              "Search indexed papers",
          )
        )
          break;
      }
      assert.equal(
        await page.evaluate(() =>
          document.activeElement?.getAttribute("aria-label"),
        ),
        "Search indexed papers",
      );
      assert.ok(
        await page.evaluate(
          () =>
            parseFloat(getComputedStyle(document.activeElement).outlineWidth) >=
            2,
        ),
      );
      await page.keyboard.type('"SHARED NAVIGATION"');
      await page.keyboard.press("Enter");
      await until(
        () => page.evaluate(() => location.hash.includes("q=")),
        "Search URL missing",
      );
      await page.getByRole("checkbox", { name: "2025", exact: true }).check();
      await page
        .getByRole("checkbox", { name: "Has PDF", exact: true })
        .check();
      await page.getByRole("checkbox", { name: "Canada", exact: true }).check();
      await until(
        async () => (await page.locator(".conference-card").count()) === 1,
        "Filtered conference count incorrect",
      );
      savedSearch = new URL(page.url()).hash;
      assert.ok(savedSearch.includes("country=Canada"));
      await page.reload();
      await page.locator(".conference-card").first().waitFor();
      assert.ok(
        await page
          .getByRole("checkbox", { name: "Canada", exact: true })
          .isChecked(),
      );
      await page
        .getByRole("checkbox", { name: "Confirmed", exact: true })
        .check();
      await until(
        () => page.evaluate(() => location.hash.includes("review=confirmed")),
        "Review state missing",
      );
      await page.goBack();
      await until(
        async () =>
          !(await page
            .getByRole("checkbox", { name: "Confirmed", exact: true })
            .isChecked()),
        "Review checkbox did not restore after Back",
      );
      await page.goForward();
      await until(
        async () =>
          await page
            .getByRole("checkbox", { name: "Confirmed", exact: true })
            .isChecked(),
        "Review checkbox did not restore after Forward",
      );
      await page.screenshot({
        path: path.join(artifacts, "desktop.png"),
        fullPage: true,
      });
      await page
        .getByRole("button", { name: "Clear all", exact: true })
        .click();
      await page
        .getByLabel("Results per page", { exact: true })
        .selectOption("1");
      await page
        .getByRole("button", { name: "Next page", exact: true })
        .click();
      await until(
        () => page.evaluate(() => location.hash.includes("page=2")),
        "Page state missing",
      );
      await page
        .getByText("3 results · Page 2 of 3", { exact: true })
        .waitFor();
      const second = await page
        .locator(".conference-card h2")
        .first()
        .innerText();
      await page.goBack();
      await until(
        async () =>
          !(await page
            .getByRole("button", { name: "Previous page", exact: true })
            .isEnabled()),
        "Pagination back state wrong",
      );
      assert.notEqual(
        await page.locator(".conference-card h2").first().innerText(),
        second,
      );
      await page.goto(base + "/" + savedSearch);
      await page.locator(".conference-card").first().waitFor();
    },
  );
  await check(
    "3–4. Open matching conference and paper; inspect extraction evidence",
    async () => {
      await page
        .getByRole("link", { name: "View matching papers", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "1 matching papers", exact: true })
        .waitFor();
      await page.locator(".paper-row").first().click();
      await page
        .getByRole("heading", {
          name: "Author & organization enrichment",
          exact: true,
        })
        .waitFor();
      const evidence = page
        .locator(".assertion-card")
        .filter({
          has: page.getByRole("heading", {
            name: "Tidal Research Institute",
            exact: true,
          }),
        })
        .first();
      await evidence
        .getByText("Inspect assertion evidence", { exact: true })
        .click();
      await evidence.getByText("deterministic pdf", { exact: true }).waitFor();
      assert.ok(
        await evidence
          .getByRole("link", { name: "Source URL", exact: false })
          .isVisible(),
      );
      await page.goBack();
      await page
        .getByRole("heading", { name: "1 matching papers", exact: true })
        .waitFor();
      assert.ok(page.url().includes("country=Canada"));
    },
  );
  await check(
    "5. Import a small CSV inventory through the browser",
    async () => {
      await importInventory([
        ["Fictional imported robotics A", "import-a", "import-a.pdf"],
        ["Fictional imported robotics B", "import-b", "import-b.pdf"],
      ]);
      await until(async () => {
        const rows = await api("/papers?edition=harbor");
        return rows.some((p) => p.title === "Fictional imported robotics B");
      }, "CSV inventory not collected");
      await until(
        async () =>
          (await api("/jobs")).some(
            (j) => j.edition_id === "harbor" && j.status === "complete",
          ),
        "Imported inventory job did not complete",
      );
      return "Two fictional inventory rows; source/PDF transport supplied by the isolated worker fixture.";
    },
  );
  let failedJob;
  await check(
    "6. Inspect failed job; retry without duplicate records",
    async () => {
      await page.goto(base + "/#/add/advanced?collection=demo");
      await page
        .getByLabel("Conference name", { exact: true })
        .fill("Fictional failing source");
      await page.getByLabel("Edition year", { exact: true }).fill("2025");
      await page
        .getByLabel("Official source URL", { exact: true })
        .fill("https://fixtures.example/failing-inventory.json");
      await page
        .getByRole("button", {
          name: "Add conference & queue job",
          exact: true,
        })
        .click();
      await until(async () => {
        failedJob = (await api("/jobs")).find(
          (j) => j.name === "Fictional failing source",
        );
        return failedJob?.status === "failed";
      }, "Mocked failure did not persist");
      const card = page
        .locator(".job")
        .filter({ hasText: "Fictional failing source" });
      await card
        .getByText(
          "Mocked official source returned HTTP 503; retry this fixture job.",
          { exact: false },
        )
        .waitFor();
      fs.writeFileSync(path.join(data, "fixture-source-enabled"), "yes");
      await card.getByRole("button", { name: "Retry", exact: true }).click();
      await until(
        async () =>
          (await api("/jobs")).find((j) => j.id === failedJob.id)?.status ===
          "complete",
        "Retried job did not complete",
      );
      const before = (await api("/papers")).length;
      await api(`/jobs/${failedJob.id}/retry`, {});
      await until(
        async () =>
          (await api("/jobs")).find((j) => j.id === failedJob.id)?.status ===
          "complete",
        "Repeated retry did not finish",
      );
      assert.equal((await api("/papers")).length, before);
      return "HTTP 503 is mocked. Retry reused the same durable job/canonical records.";
    },
  );
  await check(
    "7. Reject an uncertain same-name author match with explicit outcome",
    async () => {
      await page.goto(base + "/#/authors/a2?collection=demo");
      await page
        .getByText("Propose an identity match", { exact: true })
        .click();
      const form = page.locator(".identity-proposal-form");
      await form
        .getByLabel("Other original author ID", { exact: true })
        .fill("a4");
      await form
        .getByLabel("Corroborating source URL", { exact: true })
        .fill("https://fixtures.example/identity-review");
      await form
        .getByLabel("Evidence linking publications and identity", {
          exact: true,
        })
        .fill(
          "Alex Rivera and Alex Rivera are same-name results; no ownership evidence is available.",
        );
      await form
        .getByRole("button", {
          name: "Save proposal without merging",
          exact: true,
        })
        .click();
      await page.locator(".nav-more > summary").click();
      await page
        .getByRole("link", { name: "Review queue", exact: true })
        .click();
      const identity = page.locator(".identity-review").first();
      await identity.waitFor();
      assert.ok(
        !(await identity
          .getByRole("button", { name: "Confirm identity link", exact: true })
          .isEnabled()),
      );
      await identity
        .getByLabel("Identity review note", { exact: true })
        .fill("Rejected: names alone are insufficient evidence.");
      await identity
        .getByRole("button", { name: "Reject identity match", exact: true })
        .click();
      await page.getByText("rejected", { exact: true }).first().waitFor();
      assert.equal((await api("/authors?q=Alex%20Rivera")).length, 2);
    },
  );
  let excel, zip;
  await check(
    "8–9. Download and inspect Excel workbook and PDF ZIP",
    async () => {
      await page.goto(
        base + "/#/conferences/harbor?collection=demo&q=robotics&page_size=1",
      );
      await page.getByText("Export research", { exact: true }).click();
      await page
        .getByLabel("Export scope", { exact: true })
        .selectOption("conference");
      await page
        .getByRole("button", { name: "Generate Excel workbook", exact: true })
        .click();
      const x = page.waitForEvent("download");
      await page
        .getByRole("link", { name: "Download Excel workbook", exact: false })
        .click();
      excel = path.join(artifacts, "acceptance.xlsx");
      await (await x).saveAs(excel);
      await page
        .getByLabel("Maximum ZIP bundle size (MB)", { exact: true })
        .fill("1");
      await page
        .getByRole("button", { name: "Generate PDF ZIP bundles", exact: true })
        .click();
      const z = page.waitForEvent("download");
      await page
        .getByRole("link", {
          name: "Download endless-tuna-demo-conference-part-001.zip",
          exact: false,
        })
        .click();
      zip = path.join(artifacts, "acceptance.zip");
      await (await z).saveAs(zip);
      const inspected = spawnSync(
        python,
        ["tests/acceptance_inspect.py", excel, zip],
        { cwd: backend, env, encoding: "utf8" },
      );
      assert.equal(inspected.status, 0, inspected.stderr);
      return JSON.parse(inspected.stdout);
    },
  );
  await check(
    "10. Restart backend/worker; preserve data and resume a checkpointed job",
    async () => {
      fs.writeFileSync(path.join(data, "fixture-block-transfer"), "yes");
      await importInventory([
        ["Fictional resumed robotics A", "resume-a", "resume-now.pdf"],
        ["Fictional resumed robotics B", "resume-b", "resume-later.pdf"],
      ]);
      let job;
      await until(async () => {
        job = (await api("/jobs")).find(
          (j) => j.edition_id === "harbor" && j.status === "running",
        );
        return job?.cursor === 1;
      }, "First paper checkpoint was not persisted");
      const row = page.locator(`[data-job-id="${job.id}"]`);
      await row.getByRole("button", { name: "Cancel", exact: true }).click();
      await until(
        async () =>
          (await api("/jobs")).find((j) => j.id === job.id)?.status ===
          "cancelled",
        "Cancelled state missing",
      );
      const before = (await api("/papers")).length;
      await stop(worker);
      await stop(server);
      server = launch(
        [
          "-m",
          "uvicorn",
          "endless_tuna.main:app",
          "--host",
          "127.0.0.1",
          "--port",
          new URL(apiBase).port,
        ],
        "server",
      );
      await ready();
      worker = launch(["tests/acceptance_fixture.py", "worker"], "worker");
      await page.reload();
      await page
        .getByRole("heading", { name: "Collection jobs", exact: true })
        .waitFor();
      assert.equal((await api("/papers")).length, before);
      assert.equal((await api("/jobs")).find((j) => j.id === job.id).cursor, 1);
      fs.unlinkSync(path.join(data, "fixture-block-transfer"));
      const cancelled = page
        .locator(".job")
        .filter({ hasText: "Cancelled by analyst" })
        .first();
      await cancelled
        .getByRole("button", { name: "Resume", exact: true })
        .click();
      await until(
        async () =>
          (await api("/jobs")).find((j) => j.id === job.id)?.status ===
          "complete",
        "Restarted job did not resume",
      );
      assert.equal((await api("/papers")).length, before);
      const resumed = (await api("/jobs")).find((j) => j.id === job.id);
      assert.equal(resumed.cursor, 2);
      return "Restarted the actual ASGI and worker subprocesses on the same isolated SQLite/filesystem state. First paper was not duplicated.";
    },
  );
  await check(
    "11. Narrow layout, empty state, keyboard focus, contrast and console",
    async () => {
      await page.goto(
        base + "/#/?collection=demo&q=unfindable-acceptance-word",
      );
      await page
        .getByRole("heading", { name: "No matching conferences", exact: true })
        .waitFor();
      await page.goto(base + "/" + savedSearch);
      await page.locator(".conference-card").first().waitFor();
      const axe = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      const badgeContrast = await page
        .locator(".landscape > span")
        .first()
        .evaluate((el) => {
          const style = getComputedStyle(el);
          const rgb = (value) =>
            value
              .match(/[\d.]+/g)
              .slice(0, 3)
              .map(Number);
          const luminance = (color) =>
            rgb(color)
              .map((v) => {
                v /= 255;
                return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
              })
              .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
          const foreground = luminance(style.color),
            background = luminance(style.backgroundColor);
          return {
            foreground: style.color,
            background: style.backgroundColor,
            ratio:
              (Math.max(foreground, background) + 0.05) /
              (Math.min(foreground, background) + 0.05),
            z_index: style.zIndex,
            opacity: style.opacity,
          };
        });
      assert.ok(badgeContrast.ratio >= 4.5);
      assert.ok(
        Number(badgeContrast.z_index) >= 1 && badgeContrast.opacity === "1",
      );
      fs.writeFileSync(
        path.join(artifacts, "accessibility.json"),
        JSON.stringify(
          {
            violations: axe.violations,
            incomplete: axe.incomplete,
            explicit_solid_badge_contrast: badgeContrast,
          },
          null,
          2,
        ),
      );
      assert.deepEqual(
        axe.violations.map((v) => v.id),
        [],
      );
      assert.equal(
        await page
          .locator(".conference-grid")
          .evaluate(
            (el) => getComputedStyle(el).gridTemplateColumns.split(" ").length,
          ),
        2,
      );
      await page.setViewportSize({ width: 390, height: 844 });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      assert.equal(
        await page
          .locator(".conference-grid")
          .evaluate(
            (el) => getComputedStyle(el).gridTemplateColumns.split(" ").length,
          ),
        1,
      );
      await page
        .getByRole("button", { name: "Refine results", exact: false })
        .click();
      assert.equal(
        await page
          .getByRole("button", { name: "Refine results", exact: false })
          .getAttribute("aria-expanded"),
        "true",
      );
      assert.ok(
        await page
          .getByRole("checkbox", { name: "Canada", exact: true })
          .isChecked(),
      );
      await page.screenshot({
        path: path.join(artifacts, "mobile.png"),
        fullPage: true,
      });
      assert.equal(report.las_requests, 0);
      assert.deepEqual(report.console_errors, []);
      assert.deepEqual(report.external_requests, [], "Browser attempted an external service request");
      return {
        wcag_violations: 0,
        manual_review_items: axe.incomplete.map((r) => r.id),
        explicit_solid_badge_contrast: badgeContrast,
        mobile_page_overflow: false,
        console_errors: 0,
        live_LAS_requests: 0,
      };
    },
  );
  await check("12. Conference discovery, source checks, collection handoff and accessibility", async () => {
    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.goto(base + "/#/?collection=demo");
    await page.getByRole("button", { name: "Find conferences", exact: true }).click();
    await page.getByRole("heading", { name: "Find conferences", exact: true }).waitFor();
    await page.locator(".discovery-card").first().waitFor();
    assert.equal(await page.locator(".discovery-card").count(), 6);
    const desktop = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    assert.deepEqual(desktop.violations.map(v => v.id), []);
    // Search traffic is intercepted in the browser harness; production has no fixture transport.
    const starter = await api("/discovery/conferences?q=CoRL");
    await page.route("**/api/discovery/conferences?*", async route => {
      const params = new URL(route.request().url()).searchParams;
      if (params.get("directory") !== "official") return route.continue();
      return route.fulfill({ json: { ...starter, directory: "official", warning: "Mocked official directory result for browser acceptance.", fetched_at: null } });
    });
    let inspectCount = 0;
    await page.route("**/api/discovery/inspect", async route => {
      inspectCount++;
      return route.fulfill({ json: inspectCount === 1 ? { ok: false, message: "Mocked source HTTP 403; retry." } : {
        ok: true, official_count: 2, year: 2024, checked_at: 1794484800, source_url: "https://proceedings.mlr.press/v270/",
        sample_titles: ["Fictional browser test title"], message: "Mocked inventory accessible. No papers were added.", pdf_status: "not_checked"
      } });
    });
    const field = page.getByRole("textbox", { name: "Search conference sources" });
    await field.fill("CoRL");
    await page.getByRole("button", { name: "Search official directory", exact: true }).click();
    await until(async () => new URLSearchParams(new URL(page.url()).hash.split("?")[1]).get("q") === "CoRL", "Discovery search missing from URL");
    await until(async () => await page.locator(".discovery-card").count() === 1, "Discovery results did not update");
    const add = page.getByRole("button", { name: "Add to Real collection", exact: true });
    assert.equal(await add.isDisabled(), true);
    await page.getByRole("button", { name: "Check source", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "Mocked source HTTP 403" }).waitFor();
    assert.equal(await add.isDisabled(), true);
    await page.getByRole("button", { name: "Check again", exact: true }).click();
    await page.getByText("2 listed papers", { exact: true }).waitFor();
    assert.equal(await add.isEnabled(), true);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const narrow = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    assert.deepEqual(narrow.violations.map(v => v.id), []);
    await page.screenshot({ path: path.join(artifacts, "conference-discovery-mobile.png"), fullPage: true });
    await add.click();
    await page.getByRole("heading", { name: "Add conference", exact: true }).waitFor();
    await until(async () => await page.getByRole("combobox", { name: "Collection", exact: true }).inputValue() === "real", "Discovery handoff did not select Real collection");
    assert.equal(await page.getByLabel("Conference or proceedings link", { exact: true }).inputValue(), "https://proceedings.mlr.press/v270/");
    await page.getByRole("button", { name: "Collect papers", exact: true }).waitFor();
    await page.goBack();
    await page.getByRole("heading", { name: "Find conferences", exact: true }).waitFor();
    assert.equal(await page.getByRole("textbox", { name: "Search conference sources" }).inputValue(), "CoRL");
    await until(async () => await page.getByRole("combobox", { name: "Collection", exact: true }).inputValue() === "demo", "Back did not restore discovery collection context");
    await page.unroute("**/api/discovery/conferences?*");
    await page.unroute("**/api/discovery/inspect");
    assert.equal(report.las_requests, 0);
    assert.equal(report.console_errors.length, 0);
    return "Starter sources from real API; official-directory/inspection traffic mocked. Source failure/retry, desktop/mobile axe, URL history and Real/link-first handoff passed; no real papers queued.";
  });

  await check("13. Paste CoRL link, collect titles first, then explicitly retrieve free PDFs", async () => {
    const beforeDemo = (await api("/papers")).length;
    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.goto(base + "/#/add/manual?collection=demo");
    await page.getByLabel("Conference or proceedings link", { exact: true }).fill("https://proceedings.mlr.press/v270/");
    let calls = 0;
    await page.route("**/api/intake/preview", async route => {
      calls++;
      assert.equal(route.request().headers()["x-collection"], "real");
      return route.fulfill({ json: calls === 1 ? { ok:false, message:"Mocked source temporarily unavailable. Try again.",suggestions:[] } : {
        ok:true, preview_id:"fixture-corl-preview", name:"Fictional CoRL browser fixture",year:2024,
        source_url:"https://proceedings.mlr.press/v270/",listed_count:2,official_count:2,completeness:"official inventory",
        titles:["Fictional CoRL fixture 1","Fictional CoRL fixture 2"]
      } });
    });
    await page.getByRole("button", { name:"Preview paper list",exact:true }).click();
    await page.getByRole("heading", { name:"Let’s find the paper listing",exact:true }).waitFor();
    await page.getByRole("button", { name:"Preview paper list",exact:true }).click();
    await page.getByRole("heading", { name:"2 paper titles found",exact:true }).waitFor();
    assert.equal(await page.getByLabel("Conference name",{exact:true}).inputValue(),"Fictional CoRL browser fixture");
    assert.equal(await page.getByLabel("Edition year",{exact:true}).inputValue(),"2024");
    assert.equal(await page.getByRole("radio",{name:/quick test/}).isChecked(),true);
    let axe = await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze();
    assert.deepEqual(axe.violations.map(v=>v.id),[]);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    axe = await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze();
    assert.deepEqual(axe.violations.map(v=>v.id),[]);
    await page.screenshot({path:path.join(artifacts,"link-first-preview-mobile.png"),fullPage:true});
    await page.getByRole("radio",{name:/All 2 titles/}).check();
    await page.getByRole("button",{name:"Save 2 paper titles",exact:true}).click();
    await until(async()=>page.url().includes("/conferences/") && page.url().includes("collection=real"),"Did not open real conference");
    const eid = new URL(page.url()).hash.split("?")[0].split("/").pop();
    await until(async()=> (await api(`/conferences/${eid}/workflow`,undefined,"real")).jobs.some(j=>j.kind==="inventory" && j.status==="complete"),"Title-only job did not complete");
    await until(async()=>await page.locator(".paper-row").count()===2,"Saved titles did not appear in the conference view");
    let detail=await api(`/conferences/${eid}`,undefined,"real");
    assert.equal(detail.papers.length,2);assert.equal(detail.coverage.pdfs,0);assert.equal(detail.coverage.inventory_complete,true);
    await page.getByText("Collection details & tools",{exact:true}).click();
    await page.getByRole("button",{name:"Find free PDFs · next 10",exact:true}).waitFor();
    await until(async()=>await page.getByRole("button",{name:"Find free PDFs · next 10",exact:true}).isEnabled(),"PDF next step was not enabled");
    await page.setViewportSize({width:1440,height:1024});
    await page.screenshot({path:path.join(artifacts,"paper-list-ready-desktop.png"),fullPage:true});
    await page.getByRole("button",{name:"Find free PDFs · next 10",exact:true}).click();
    await until(async()=> (await api(`/conferences/${eid}/workflow`,undefined,"real")).jobs.some(j=>j.kind==="pdfs" && j.status==="complete"),"Explicit PDF job did not complete");
    detail=await api(`/conferences/${eid}`,undefined,"real");
    assert.equal(detail.papers.length,2);assert.equal(detail.coverage.pdfs,2);assert.equal(detail.coverage.inventory_complete,true);
    assert.equal((await api("/papers")).length,beforeDemo);
    await page.unroute("**/api/intake/preview");
    assert.equal(report.las_requests,0);
    return "Exact CoRL URL input; mocked source preview/transport and fictional durable snapshot. Real backend/worker saved titles with zero downloads, then a separate explicit job downloaded two PDFs. Desktop/mobile axe passed; demo preserved.";
  });

  await check("14. One analyst action automatically collects WACV papers and PDFs", async () => {
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(base + "/#/add?collection=demo");
    await page.getByLabel("Conference or proceedings link",{exact:true}).fill("https://wacv.thecvf.com/Conferences/2026");
    assert.equal(await page.getByRole("button",{name:"Preview paper list",exact:true}).count(),0);
    assert.equal(await page.getByLabel("Edition year",{exact:true}).count(),0);
    assert.equal(await page.getByLabel("Collection scope",{exact:true}).inputValue(),"sample");
    await page.getByLabel("Collection scope",{exact:true}).selectOption("all");
    const desktop=await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze();
    assert.deepEqual(desktop.violations.map(v=>v.id),[]);
    await page.screenshot({path:path.join(artifacts,"automatic-add-desktop.png"),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    const narrow=await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze();
    assert.deepEqual(narrow.violations.map(v=>v.id),[]);
    await page.screenshot({path:path.join(artifacts,"automatic-add-mobile.png"),fullPage:true});
    let requests=0;
    await page.route("**/api/intake/collect", async route => {
      requests++;
      const body=route.request().postDataJSON();
      assert.equal(body.url,"https://wacv.thecvf.com/Conferences/2026");assert.equal(body.full_collection,true);
      // Inject only a fictional persisted source snapshot. The real API queues
      // the job and the actual worker completes both phases without UI handoffs.
      const response=await route.fetch({postData:JSON.stringify({...body,preview_id:"fixture-wacv-preview"})});
      return route.fulfill({response});
    });
    await page.getByRole("button",{name:"Collect papers",exact:true}).click();
    await until(async()=>page.url().includes("/conferences/"),"Automatic collection did not open the conference");
    const eid=new URL(page.url()).hash.split("?")[0].split("/").pop();
    await until(async()=>(await api(`/conferences/${eid}/workflow`,undefined,"real")).jobs.some(j=>j.kind==="automatic"&&j.status==="complete"),"Automatic paper/PDF collection did not finish");
    await until(async()=>await page.locator(".paper-row").count()===2,"Automatically collected papers did not appear");
    const detail=await api(`/conferences/${eid}`,undefined,"real");
    assert.equal(detail.coverage.pdfs,2);assert.equal(detail.papers.length,2);assert.equal(detail.coverage.inventory_complete,true);
    assert.equal(detail.tracks[0].name,"Main Conference");assert.equal(requests,1);
    await page.getByRole("heading", {name:"Your papers", exact:true}).waitFor();
    await until(async () => (await page.locator(".collection-counts > div").nth(1).locator("strong").innerText()) === "2", "Completed PDF count did not refresh");
    await page.setViewportSize({width:1440,height:1000});
    await page.screenshot({path:path.join(artifacts,"automatic-collection-ready.png"),fullPage:true});
    await page.unroute("**/api/intake/collect");
    assert.equal(report.las_requests,0);
    return "One Collect papers click; actual API/worker automatically saved titles and PDFs from a fictional WACV snapshot. No preview/save/download handoffs; explicit full scope; desktop/mobile axe clean.";
  });

  await check("15. Streamlined navigation, paper filters and secondary tools on desktop/mobile", async () => {
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(base + "/#/conferences/harbor?collection=demo");
    await page.locator(".paper-row").first().waitFor();
    assert.equal(await page.locator("header .header-add").count(), 1);
    assert.equal(await page.getByLabel("Review filter",{exact:true}).isVisible(), false);
    assert.equal(await page.locator(".detailed-coverage").getAttribute("open"), null);
    assert.equal(await page.locator(".collection-sources").getAttribute("open"), null);
    await page.locator(".paper-filters > summary").click();
    await page.getByLabel("Review filter",{exact:true}).selectOption("confirmed");
    await page.reload();
    await page.getByLabel("Review filter",{exact:true}).waitFor();
    assert.equal(await page.getByLabel("Review filter",{exact:true}).inputValue(), "confirmed");
    await page.getByText("Export research",{exact:true}).click();
    assert.equal(await page.getByRole("button",{name:"Export CSV",exact:true}).isVisible(),true);
    assert.equal(await page.getByRole("button",{name:"Generate Excel workbook",exact:true}).isVisible(),true);
    await page.setViewportSize({width:390,height:844});
    const more = page.locator(".nav-more > summary");
    await more.click();
    const jobs = page.getByRole("link",{name:"Collection jobs",exact:true});
    assert.equal(await jobs.isVisible(),true);
    const bounds=await jobs.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
    await page.keyboard.press("Escape");
    assert.equal(await jobs.isVisible(),false);
    assert.equal(await more.evaluate(el=>el===document.activeElement),true);
    await more.click();
    const accessibility=await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze();
    assert.deepEqual(accessibility.violations.map(v=>v.id),[]);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(artifacts,"streamlined-conference-mobile.png"),fullPage:true});
    await jobs.click();
    await page.getByRole("heading",{name:"Collection jobs",exact:true}).waitFor();
    await page.getByRole("button",{name:"Add conference",exact:true}).click();
    await page.getByRole("heading",{name:"Add conference",exact:true}).waitFor();
    assert.equal(await page.locator(".header-add").count(),0);
    assert.ok(page.url().includes("collection=real"));
    return "Primary browsing navigation plus keyboard-accessible More; one Add action; secondary filters restore from URL; all export formats accessible; mobile menu stays in viewport; axe clean.";
  });

  report.checks.push({
    name: "Live LAS inference",
    status: "Unverified",
    detail:
      "Not attempted. Credentials are explicitly absent; model tests use mocked transports.",
  });
  report.checks.push({
    name: "Real source collection during this acceptance run",
    status: "Unverified",
    detail:
      "This browser workflow uses fictional inventories and mocked transport. The previously recorded real 10-paper NeurIPS collection is separate evidence.",
  });
} catch (error) {
  console.error(error);
  report.error = error.message;
  process.exitCode = 1;
} finally {
  await browser?.close();
  await stop(worker);
  await stop(frontendServer);
  await stop(server);
  report.finished_utc = new Date().toISOString();
  fs.writeFileSync(
    path.join(artifacts, "acceptance.json"),
    JSON.stringify(report, null, 2),
  );
  console.log("Acceptance report: " + path.join(artifacts, "acceptance.json"));
}
