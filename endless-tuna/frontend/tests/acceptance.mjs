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
const base = `http://127.0.0.1:${process.env.TUNA_ACCEPTANCE_PORT || 8021}`;
const env = {
  ...process.env,
  PYTHONPATH: backend,
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
let server, worker, browser, page;
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
async function ready() {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(base + "/api/health")).ok) return;
    } catch {}
    await delay(200);
  }
  throw Error(
    "Local acceptance server failed to start; inspect " + data + "/server.log",
  );
}
async function api(p, body) {
  const response = await fetch(base + "/api" + p, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-Collection": "demo" },
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
      new URL(base).port,
    ],
    "server",
  );
  await ready();
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
        .getByText("All sample research is fictional.", { exact: false })
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
      await page.goto(base + "/#/add?collection=demo");
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
      const row = page
        .locator(".job")
        .filter({ hasText: "Checkpoint 1" })
        .first();
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
          new URL(base).port,
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
  await stop(server);
  report.finished_utc = new Date().toISOString();
  fs.writeFileSync(
    path.join(artifacts, "acceptance.json"),
    JSON.stringify(report, null, 2),
  );
  console.log("Acceptance report: " + path.join(artifacts, "acceptance.json"));
}
