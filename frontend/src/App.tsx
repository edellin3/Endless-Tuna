import {
  createContext,
  useContext,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Search,
  Plus,
  ArrowRight,
  FileText,
  BookOpen,
  Users,
  Settings,
  X,
  SlidersHorizontal,
  ChevronDown,
  Check,
  ExternalLink,
  ArrowLeft,
  RefreshCw,
  Waves,
} from "lucide-react";

type Row = Record<string, any>;
type Filters = {
  year: string;
  conference: string;
  organization: string;
  country: string;
  pdf: string;
  review: string;
};
const blank: Filters = {
  year: "",
  conference: "",
  organization: "",
  country: "",
  pdf: "",
  review: "",
};
const navigate = (path: string) => {
  const [base, raw = ""] = path.split("?");
  const params = new URLSearchParams(raw);
  if (!params.has("collection"))
    params.set(
      "collection",
      new URLSearchParams(location.hash.split("?")[1] || "").get(
        "collection",
      ) ||
        localStorage.getItem("tuna-collection") ||
        "demo",
    );
  const hash = "#" + base + "?" + params.toString();
  if (location.hash !== hash) history.pushState(null, "", hash);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
};
function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

type AppServices = {
  api: (path: string, body?: unknown, targetCollection?: string) => Promise<any>;
  download: (path: string, name: string) => Promise<void>;
  refresh: () => void;
  collection: string;
  id: string | undefined;
  query: string;
  setNotice: (s: string) => void;
  revision: number;
};
const AppContext = createContext<AppServices>(null!);
const useApp = () => useContext(AppContext);
const queryParams = (values: Record<string, string>) =>
  new URLSearchParams(
    Object.entries(values).filter(([, value]) => value !== ""),
  );
function useSearchURL(
  defaults: Record<string, string>,
): [
  Record<string, string>,
  (patch: Record<string, string>, replace?: boolean) => void,
] {
  const { query, collection } = useApp();
  const params = new URLSearchParams(query);
  const values = { ...defaults };
  for (const key of Object.keys(defaults))
    values[key] = params.get(key) ?? defaults[key];
  if ("page" in values)
    values.page = String(
      Math.max(1, Math.min(100000, Number(values.page) || 1)),
    );
  if ("page_size" in values)
    values.page_size = String(
      Math.max(
        1,
        Math.min(100, Number(values.page_size) || Number(defaults.page_size)),
      ),
    );
  return [
    values,
    (patch, replace = false) => {
      const next = new URLSearchParams(query);
      const merged = { ...values, ...patch };
      if (!("page" in patch) && Object.keys(patch).some((k) => k !== "page"))
        merged.page = "1";
      for (const [key, value] of Object.entries(merged)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      next.set("collection", collection);
      const route =
        location.hash.slice(1).split("?")[0] + "?" + next.toString();
      if (replace) {
        history.replaceState(null, "", "#" + route);
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      } else navigate(route);
    },
  ];
}
const backRoute = (fallback: string) => {
  const candidate = new URLSearchParams(location.hash.split("?")[1] || "").get(
    "from",
  );
  return candidate?.startsWith("/") &&
    !candidate.startsWith("//") &&
    candidate.length < 8000
    ? candidate
    : fallback;
};
function Pagination({
  result,
  onPage,
  onSize,
}: {
  result: Row | null;
  onPage: (n: number) => void;
  onSize: (n: string) => void;
}) {
  if (!result) return null;
  return (
    <div
      className="pagination"
      role="navigation"
      aria-label="Search result pages"
    >
      <p>
        {result.total} results · Page {result.page} of {result.pages}
      </p>
      <label>
        Results per page
        <select
          aria-label="Results per page"
          value={result.page_size}
          onChange={(e) => onSize(e.target.value)}
        >
          {[1, 5, 12, 25, 50, 100].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <button
        disabled={result.page <= 1}
        onClick={() => onPage(result.page - 1)}
      >
        Previous page
      </button>
      <button
        disabled={result.page >= result.pages}
        onClick={() => onPage(result.page + 1)}
      >
        Next page
      </button>
    </div>
  );
}
function ExportPanel({
  editionId,
  filters,
}: {
  editionId?: string;
  filters: Record<string, string>;
}) {
  const { api, download } = useApp();
  const [scope, setScope] = useState("filtered");
  const [max, setMax] = useState("100");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [workbook, setWorkbook] = useState<Row | null>(null);
  const [bundles, setBundles] = useState<Row | null>(null);
  const key = JSON.stringify(filters);
  useEffect(() => {
    setWorkbook(null);
    setBundles(null);
    setError("");
  }, [key, scope, editionId]);
  async function create(kind: string) {
    setBusy(kind);
    setError("");
    try {
      const f: Row = {};
      for (const name of [
        "q",
        "year",
        "conference",
        "organization",
        "country",
        "pdf",
        "review",
      ]) {
        if (filters[name])
          f[name] = name === "year" ? Number(filters[name]) : filters[name];
      }
      const response = await api(`/exports/${kind}`, {
        scope,
        edition_id: editionId || null,
        filters: f,
        max_bundle_mb: kind === "pdf-bundles" ? Number(max) : null,
      });
      if (kind === "workbook") setWorkbook(response);
      else setBundles(response);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  const label =
    scope === "all"
      ? "All records in the selected collection"
      : scope === "conference"
        ? "All papers in this conference; search filters are ignored"
        : "All papers matching the current filters, across every result page";
  return (
    <section className="panel export-panel">
      <details>
        <summary>Export research</summary>
        {editionId && <div className="toolbar quick-exports">
          <span>Current paper results</span>
          {["csv", "json"].map(format => <button key={format} onClick={() => download(
            `/conferences/${editionId}/export?format=${format}&${queryParams(filters)}`, `papers.${format}`
          )}>Export {format.toUpperCase()}</button>)}
        </div>}
        <div className="toolbar">
          <label>
            Export scope
            <select
              aria-label="Export scope"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="filtered">
                Current filters · every result page
              </option>
              {editionId && (
                <option value="conference">
                  Selected conference · all its papers
                </option>
              )}
              <option value="all">
                All stored records · selected collection
              </option>
            </select>
          </label>
          <label>
            Maximum ZIP bundle size (MB)
            <input
              aria-label="Maximum ZIP bundle size (MB)"
              type="number"
              min="1"
              max="500"
              value={max}
              onChange={(e) => setMax(e.target.value)}
            />
          </label>
        </div>
        <p className="export-scope">
          {label}. Pagination never limits an export.
        </p>
        {scope === "filtered" && (
          <p className="diagnostic-help">
            Active filters:{" "}
            {Object.entries(filters)
              .filter(([k, v]) => v && !["page", "page_size"].includes(k))
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ") || "none"}
          </p>
        )}
        <div className="toolbar">
          <button
            className="primary"
            disabled={!!busy}
            onClick={() => create("workbook")}
          >
            {busy === "workbook"
              ? "Building workbook…"
              : "Generate Excel workbook"}
          </button>
          <button
            disabled={!!busy || Number(max) < 1 || Number(max) > 500}
            onClick={() => create("pdf-bundles")}
          >
            {busy === "pdf-bundles"
              ? "Building PDF bundles…"
              : "Generate PDF ZIP bundles"}
          </button>
        </div>
        <p className="diagnostic-help">
          Excel contains Conferences, Papers, Paper Authors, Affiliations,
          Sources, Missing PDFs, and Review Queue. ZIPs contain one preferred
          available PDF per paper, plus manifest.json and missing-files.csv.
          Oversize PDFs are reported rather than silently exceeding the limit.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {workbook && (
          <p role="status">
            <a
              className="artifact-download"
              href={workbook.download_url}
              download={workbook.name}
            >
              Download Excel workbook · {workbook.included_papers} unique papers
              · {(workbook.size_bytes / 1000000).toFixed(2)} MB
            </a>
          </p>
        )}
        {bundles && (
          <div role="status">
            <p>
              {bundles.selected_papers} selected papers ·{" "}
              {bundles.included_papers} included · {bundles.missing_papers}{" "}
              missing or excluded · {bundles.parts.length} bundle(s)
            </p>
            {bundles.parts.map((part: Row) => (
              <p key={part.id}>
                <a
                  className="artifact-download"
                  href={part.download_url}
                  download={part.name}
                >
                  Download {part.name} · {part.included_papers} papers ·{" "}
                  {(part.size_bytes / 1000000).toFixed(2)} MB
                </a>
              </p>
            ))}
          </div>
        )}
      </details>
    </section>
  );
}

function useData(url: string) {
  const { api, collection, revision } = useApp();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    api(url)
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [url, collection, revision]);
  return { data, error };
}
function State({
  data,
  error,
  children,
}: {
  data: any;
  error: string;
  children: ReactNode;
}) {
  const { refresh } = useApp();
  if (error)
    return (
      <div className="state error" role="alert">
        <h3>We couldn’t load this collection</h3>
        <p>{error}</p>
        <button onClick={refresh}>
          <RefreshCw size={16} /> Try again
        </button>
      </div>
    );
  if (data === null)
    return (
      <div className="state" role="status">
        <span className="spinner" /> Loading your collection…
      </div>
    );
  return <>{children}</>;
}
function PaperList({ papers }: { papers: Row[] }) {
  const { collection } = useApp();
  return papers.length ? (
    <div className="paper-list">
      {papers.map((p) => (
        <a
          className="paper-row"
          href={`#/papers/${p.id}?${queryParams({ collection, from: location.hash.slice(1) })}`}
          key={p.id}
        >
          <div className="paper-icon">
            <FileText size={22} />
          </div>
          <div>
            <h3>{p.title}</h3>
            <p>{p.authors?.map((a: Row) => a.name).join(" · ")}</p>
            <small>
              {p.conference} {p.year} · {p.track}
            </small>
            {p.matching_pages?.map((page: Row) => (
              <p className="page-excerpt" key={page.download_id + page.page}>
                {page.version} PDF p. {page.page}: {page.excerpt}
              </p>
            ))}
            <div className="tags">
              <Badge tone={p.review_status === "confirmed" ? "green" : ""}>
                {p.review_status}
              </Badge>
              <Badge>{p.has_pdf ? "PDF available" : "PDF missing"}</Badge>
            </div>
          </div>
          <ArrowRight size={19} />
        </a>
      ))}
    </div>
  ) : (
    <div className="state">
      <BookOpen />
      <h3>No papers to show</h3>
      <p>Try a different keyword or clear your filters.</p>
    </div>
  );
}
function Explore() {
  const { collection, refresh } = useApp();
  const [search, setSearch] = useSearchURL({
    q: "",
    ...blank,
    page: "1",
    page_size: "12",
  });
  const q = search.q;
  const [input, setInput] = useState(q);
  const [open, setOpen] = useState(false);
  useEffect(() => setInput(q), [q]);
  const f: Filters = {
    year: search.year,
    conference: search.conference,
    organization: search.organization,
    country: search.country,
    pdf: search.pdf,
    review: search.review,
  };
  const params = queryParams(search).toString();
  const result = useData("/search/conferences?" + params);
  const data = result.data?.items ?? null;
  const error = result.error;
  const facets = useData("/filters");
  const inventory = useData("/coverage");
  const filtered = !!q || Object.values(f).some(Boolean);
  const change = (key: keyof Filters, value: string) =>
    setSearch({ [key]: value, page: "1" });
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Explore conferences</h1>
          <p>Search your collected papers, or add a conference to get started.</p>
        </div>
      </div>
      <form
        className="search-panel"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch({ q: input, page: "1" });
        }}
      >
        <div className="search-field">
          <Search size={24} />
          <input
            aria-label="Search indexed papers"
            placeholder="Search a topic, idea, or keyword…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          {input && (
            <button
              type="button"
              className="icon-button"
              aria-label="Clear search"
              onClick={() => {
                setInput("");
                setSearch({ q: "", page: "1" });
              }}
            >
              <X size={20} />
            </button>
          )}
        </div>
        <button className="primary" type="submit">
          Search <ArrowRight size={18} />
        </button>
        <p>
          Searches indexed titles, abstracts, and available PDF text.{" "}
          {collection === "demo"
            ? "Fictional demo inventory."
            : inventory.data?.inventory_complete
              ? "Full official inventory collection is complete."
              : "Official inventory collection is incomplete or unverified; results cover collected records only."}
        </p>
      </form>
      <div className="explore-layout">
        <aside className={"filters " + (open ? "expanded" : "")}>
          <div className="filter-title">
            <h2>
              <SlidersHorizontal size={18} /> Filters
            </h2>
            <button
              className="text-button"
              onClick={() => setSearch({ ...blank, page: "1" })}
            >
              Clear all
            </button>
          </div>
          <button
            className="mobile-toggle"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
          >
            Refine results <ChevronDown size={16} />
          </button>
          <div className="filter-body">
            {facets.error && (
              <p role="alert">
                Filters unavailable. <button onClick={refresh}>Retry</button>
              </p>
            )}
            {(
              [
                [
                  "year",
                  "Year",
                  facets.data?.years.map((x: number) => ({
                    id: String(x),
                    name: String(x),
                  })),
                ],
                ["conference", "Conference", facets.data?.conferences],
                ["organization", "Organization", facets.data?.organizations],
                [
                  "country",
                  "Verified organization country",
                  facets.data?.countries.map((v: string) => ({
                    id: v,
                    name: v,
                  })),
                ],
                [
                  "pdf",
                  "PDF availability",
                  [
                    { id: "yes", name: "Has PDF" },
                    { id: "no", name: "No PDF" },
                  ],
                ],
                [
                  "review",
                  "Review status",
                  [
                    { id: "confirmed", name: "Confirmed" },
                    { id: "uncertain", name: "Needs review" },
                    { id: "rejected", name: "Rejected" },
                  ],
                ],
              ] as [keyof Filters, string, Row[] | undefined][]
            ).map(([key, label, options]) => (
              <fieldset key={key}>
                <legend>{label}</legend>
                {options?.map((o) => (
                  <label className="check-label" key={o.id}>
                    <input
                      type="checkbox"
                      checked={f[key] === o.id}
                      onChange={() => change(key, f[key] === o.id ? "" : o.id)}
                    />
                    {o.name}
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
        </aside>
        <section className="results">
          <div className="results-heading">
            <p>
              {data ? (
                <>
                  <strong>{result.data?.total}</strong> conference
                  {result.data?.total !== 1 ? "s" : ""}
                  {q ? (
                    <>
                      {" "}
                      matching <strong>“{q}”</strong>
                    </>
                  ) : (
                    " in your collection"
                  )}
                </>
              ) : (
                "Discover your collection"
              )}
            </p>
            <button onClick={() => navigate("/discover")}><Search size={18} /> Find conferences</button>
          </div>
          <State data={data} error={error}>
            {data?.length ? (
              <div className="conference-grid">
                {data.map((c: Row, i: number) => (
                  <article className="conference-card" key={c.id}>
                    <div className="card-top">
                      <div className={"landscape landscape-" + (i % 3)}>
                        <Waves size={37} />
                        <span>{c.year}</span>
                      </div>
                      <div>
                        <Badge
                          tone={
                            c.coverage?.inventory_complete
                              ? "green"
                              : collection === "demo"
                                ? "blue"
                                : "amber"
                          }
                        >
                          {c.coverage?.inventory_complete
                            ? "Inventory complete"
                            : collection === "demo"
                              ? "Demo sample"
                              : ["complete", "partial"].includes(c.status)
                                ? "Partial collection"
                                : c.status}
                        </Badge>
                        <h2>
                          {c.name} <span>{c.year}</span>
                        </h2>
                      </div>
                    </div>
                    <p className="description">{c.description}</p>
                    <p className="coverage-line">
                      {c.coverage?.pdfs || 0} PDFs available · {c.coverage?.fulltext || 0} searchable full texts
                      {!c.coverage?.inventory_complete && <span className="coverage-note">Partial or unverified inventory · results cover collected papers only</span>}
                      {c.official_count != null && <span className="coverage-note">{c.total_count} of {c.official_count} official papers collected</span>}
                    </p>
                    <div className="evidence-snippet">
                      <span>FROM THE INDEXED EVIDENCE</span>
                      <p>{c.snippet}</p>
                    </div>
                    <div className="card-stats">
                      <span>
                        <FileText size={17} />
                        <strong>{c.matching_count}</strong> matching papers
                      </span>
                      <small>{c.total_count} total indexed</small>
                    </div>
                    <a
                      className="card-action"
                      href={`#/conferences/${c.id}?${queryParams({ ...search, page: "1", page_size: "25", collection, from: location.hash.slice(1) })}`}
                    >
                      View matching papers <ArrowRight size={18} />
                    </a>
                  </article>
                ))}
              </div>
            ) : (
              <div className="state">
                <Search size={32} />
                <h3>
                  {filtered
                    ? "No matching conferences"
                    : "Your collection is ready for its first conference"}
                </h3>
                <p>
                  {filtered
                    ? "Try a broader keyword or clear your filters. Only indexed papers appear here."
                    : "Add an official source to start a collection job."}
                </p>
                <button
                  onClick={() => {
                    setSearch({ ...blank, q: "", page: "1" });
                    setInput("");
                  }}
                >
                  Clear search and filters
                </button>
              </div>
            )}
          </State>
          <Pagination
            result={result.data}
            onPage={(n) => setSearch({ page: String(n) })}
            onSize={(n) => setSearch({ page_size: n, page: "1" })}
          />
          {result.data?.query.notes.map((note: string) => (
            <p className="diagnostic-help" key={note}>
              {note}
            </p>
          ))}
          <p className="diagnostic-help">
            All terms are required; use double quotes for phrases. Punctuation
            separates words. AND, OR, NOT, and other operators are searched as
            literal words. Metadata-only papers remain searchable, but have no
            PDF-text coverage.
          </p>
          <ExportPanel filters={search} />
          <p className="collection-note">
            <Check size={14} /> Evidence stays connected to its source.{" "}
            {collection === "demo"
              ? "All people, conferences, and papers shown here are fictional."
              : "Records belong to your real collection."}
          </p>
        </section>
      </div>
    </>
  );
}
function Conference() {
  const { download, id, query, api, setNotice } = useApp();
  const { data: d, error } = useData("/conferences/" + id + "?include_papers=false");
  const [search, setSearch] = useSearchURL({
    q: "",
    ...blank,
    page: "1",
    page_size: "25",
  });
  const q = search.q,
    pdf = search.pdf,
    review = search.review;
  const setQ = (q: string) => setSearch({ q, page: "1" }, true);
  const setPdf = (pdf: string) => setSearch({ pdf, page: "1" });
  const setReview = (review: string) => setSearch({ review, page: "1" });
  const params = queryParams(search);
  const list = useData(`/search/papers?edition=${id}&${params}`);
  const facets = useData("/filters");
  return (
    <State data={d} error={error}>
      {d && (
        <>
          <a className="back" href={"#" + backRoute("/")}>
            <ArrowLeft size={16} /> Explore conferences
          </a>
          <div className="page-heading">
            <div>
              <Badge>{({complete:"Collection ready",partial:"Collection saved",queued:"Collecting",collecting:"Collecting",list_ready:"Paper list ready",cancelled:"Paused",failed:"Needs attention"} as Record<string,string>)[d.status] || d.status.replaceAll("_", " ")}</Badge>
              <h1>
                {d.name} {d.year}
              </h1>
              <p>{d.description}</p>
            </div>
          </div>
          <CollectionWorkflow editionId={d.id} baseline={d.coverage} initialStatus={d.status} sourceURL={d.source_url} conferenceName={d.name} conferenceYear={d.year} />
          <div className="toolbar">
            <input
              aria-label="Filter conference papers"
              placeholder="Filter papers by keyword"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select
              aria-label="PDF filter"
              value={pdf}
              onChange={(e) => setPdf(e.target.value)}
            >
              <option value="">All PDF statuses</option>
              <option value="yes">Has PDF</option>
              <option value="no">No PDF</option>
            </select>
          </div>
          <details className="paper-filters" open={!!(review || search.organization || search.country)}>
            <summary>More filters{[review, search.organization, search.country].filter(Boolean).length > 0 && ` (${[review, search.organization, search.country].filter(Boolean).length} active)`}</summary>
            <div className="toolbar">
              <label>Review status
            <select
              aria-label="Review filter"
              value={review}
              onChange={(e) => setReview(e.target.value)}
            >
              <option value="">All review statuses</option>
              <option value="uncertain">Needs review</option>
              <option value="confirmed">Confirmed</option>
              <option value="rejected">Rejected</option>
            </select>
              </label>
            <label>
              Organization
              <select
                aria-label="Conference organization filter"
                value={search.organization}
                onChange={(e) =>
                  setSearch({ organization: e.target.value, page: "1" })
                }
              >
                <option value="">All organizations</option>
                {facets.data?.organizations.map((o: Row) => (
                  <option value={o.id} key={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Verified organization country
              <select
                aria-label="Conference verified country filter"
                value={search.country}
                onChange={(e) =>
                  setSearch({ country: e.target.value, page: "1" })
                }
              >
                <option value="">All verified countries</option>
                {facets.data?.countries.map((v: string) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
          </div>
          </details>
          <h2>{list.data?.total ?? "…"} matching papers</h2>
          <State {...list}>
            <PaperList papers={list.data?.items || []} />
          </State>
          <Pagination
            result={list.data}
            onPage={(n) => setSearch({ page: String(n) })}
            onSize={(n) => setSearch({ page_size: n, page: "1" })}
          />
          <ExportPanel editionId={d.id} filters={search} />
          <details className="panel detailed-coverage"><summary>Detailed collection coverage</summary>
          <div className="metrics coverage-metrics">
            {[
              [d.coverage.official_count ?? "Unknown", "Official inventory"],
              [d.coverage.inventory_records, "Inventory records collected"],
              [d.coverage.pdfs, "PDFs available"],
              [d.coverage.missing_pdfs, "PDFs missing"],
              [d.coverage.ambiguous, "Ambiguous candidates"],
              [d.coverage.fulltext, "Papers with full text"],
              [d.coverage.failed_jobs, "Failed / partial jobs"],
              [d.coverage.pending_jobs, "Pending / interrupted jobs"],
            ].map(([value, label]) => (
              <div key={label}>
                <strong>{value}</strong>
                <span>{label}</span>
              </div>
            ))}
          </div>
          <div className="info">
            {d.coverage.inventory_complete
              ? "Full official inventory collected. PDF and text coverage may still be partial."
              : "Full official inventory collection is incomplete or unverified. Search results cover collected records only."}
          </div>
          </details>
          <details className="panel collection-sources">
            <summary>Conference sources</summary>
            <p>
              Membership comes from the linked official inventory or
              analyst-supplied CSV evidence. Source retrieval timestamps and
              collection coverage are preserved separately from PDF
              availability.
            </p>
            {d.tracks.map((t: Row) => (
              <Badge key={t.id}>{t.name}</Badge>
            ))}
            {d.sources.map((s: Row) => (
              <p key={s.id}>
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.label} <ExternalLink size={14} />
                </a>
              </p>
            ))}
          </details>
          <CSVInventory editionId={d.id} />
        </>
      )}
    </State>
  );
}
function Paper() {
  const { download, id } = useApp();
  const { data: d, error } = useData("/papers/" + id);
  return (
    <State data={d} error={error}>
      {d && (
        <>
          <a
            className="back"
            href={"#" + backRoute(`/conferences/${d.edition_id}`)}
          >
            <ArrowLeft size={16} /> Conference papers
          </a>
          <div className="page-heading">
            <div>
              <Badge tone={d.review_status === "confirmed" ? "green" : "amber"}>
                {d.review_status}
              </Badge>
              <h1>{d.title}</h1>
            </div>
            <button
              disabled={!d.downloads.some((x: Row) => x.status === "available")}
              className="primary"
              onClick={() => download(`/papers/${id}/pdf`, `${id}.pdf`)}
            >
              <FileText size={18} /> Open PDF
            </button>
          </div>
          <div className="detail-grid">
            <section className="panel">
              <h2>Abstract</h2>
              <p className="abstract">{d.abstract}</p>
              <h2>Authors & affiliations</h2>
              <ol className="authors-list">
                {d.authors.map((a: Row) => (
                  <li key={a.id}>
                    <a href={`#/authors/${a.id}`}>{a.name}</a>
                    {a.affiliation_assertions?.length ? (
                      <div className="tags">
                        {a.affiliation_assertions.map((claim: Row) => (
                          <span key={claim.id}>
                            {claim.value} <StatusBadge status={claim.status} />
                          </span>
                        ))}
                        <button
                          className="text-button"
                          onClick={() =>
                            document
                              .getElementById("paper-enrichment")
                              ?.scrollIntoView()
                          }
                        >
                          Evidence & review
                        </button>
                      </div>
                    ) : (
                      <p>
                        {a.has_affiliation_assertions
                          ? "No active affiliation assertion. Inspect review history."
                          : a.organizations.length
                            ? `${a.organizations.map((o: Row) => o.name).join(" · ")} · Legacy metadata — needs evidence review`
                            : "Affiliation unknown — no supporting evidence yet"}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            </section>
            <section className="panel">
              <h2>Supporting evidence</h2>
              {d.evidence.map((ev: Row) => (
                <div className="evidence" key={ev.id}>
                  <Badge>{ev.field}</Badge>
                  <blockquote>{ev.quote}</blockquote>
                  <a href={ev.url} target="_blank" rel="noreferrer">
                    {ev.label} <ExternalLink size={14} />
                  </a>
                </div>
              ))}
              <h2>PDF status</h2>
              {d.downloads.map((x: Row) => (
                <p key={x.id}>
                  {x.status === "available"
                    ? "Available in local storage"
                    : "PDF not collected"}
                  {x.error && ` · ${x.error}`}
                </p>
              ))}
            </section>
          </div>
          <section className="panel">
            <LASExtraction
              paperId={d.id}
              parsed={!!d.parsed_pdf_pages}
              available={d.downloads.some((x: Row) => x.status === "available")}
            />
          </section>
          <PaperEnrichment paperId={d.id} />
          <PaperSources paper={d} />
          <section className="panel">
            <h2>Review history</h2>
            {d.history.length ? (
              d.history.map((h: Row) => (
                <p key={h.id}>
                  <strong>{h.action}</strong> ·{" "}
                  {new Date(h.created * 1000).toLocaleString()}
                  <br />
                  {h.old_title !== h.new_title &&
                    `${h.old_title} → ${h.new_title}`}{" "}
                  {h.note}
                </p>
              ))
            ) : (
              <p>No manual reviews recorded.</p>
            )}
          </section>
        </>
      )}
    </State>
  );
}
function Authors() {
  const { id } = useApp();
  const [search, setSearch] = useSearchURL({
    q: "",
    organization: "",
    country: "",
    review: "",
  });
  const q = search.q,
    organization = search.organization,
    country = search.country,
    review = search.review;
  const setQ = (q: string) => setSearch({ q }, true);
  const setOrganization = (organization: string) => setSearch({ organization });
  const setCountry = (country: string) => setSearch({ country });
  const setReview = (review: string) => setSearch({ review });
  const { data, error } = useData(
    id
      ? `/authors/${id}`
      : `/authors?${queryParams({ q, organization, country, review })}`,
  );
  const filters = useData("/author-filters");
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">PEOPLE BEHIND THE PAPERS</div>
          <h1>{id ? data?.name || "Author" : "Authors"}</h1>
          <p>Paper-time affiliations, with evidence you can inspect.</p>
        </div>
      </div>
      {!id && (
        <div className="toolbar author-filters">
          <input
            aria-label="Search authors"
            placeholder="Search author names…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            aria-label="Filter authors by organization"
            value={organization}
            onChange={(e) => setOrganization(e.target.value)}
          >
            <option value="">All extracted organizations</option>
            {filters.data?.organizations.map((v: string) => (
              <option key={v}>{v}</option>
            ))}
          </select>
          <select
            aria-label="Filter authors by verified organization country"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
          >
            <option value="">All verified organization countries</option>
            {filters.data?.countries.map((v: string) => (
              <option key={v}>{v}</option>
            ))}
          </select>
          <select
            aria-label="Filter authors by review status"
            value={review}
            onChange={(e) => setReview(e.target.value)}
          >
            <option value="">All review statuses</option>
            <option value="extracted">Extracted</option>
            <option value="verified">Verified</option>
            <option value="needs_review">Needs review</option>
          </select>
        </div>
      )}
      <State data={data} error={error}>
        {id ? (
          data && <AuthorEvidenceDetail author={data} />
        ) : (
          <div className="author-directory">
            {data?.map((a: Row) => (
              <a
                className="panel author-directory-row"
                href={`#/authors/${a.id}`}
                key={a.id}
              >
                <div className="avatar">
                  <Users size={23} />
                </div>
                <div>
                  <h2>{a.name}</h2>
                  <p>
                    {a.organizations.length
                      ? a.organizations.join(" · ")
                      : "Affiliation evidence not yet available"}
                  </p>
                  <small>
                    {a.paper_count} papers · {a.member_ids.length} original{" "}
                    {a.member_ids.length === 1 ? "identity" : "identities"}
                    {a.verified_countries.length
                      ? ` · Verified organization country: ${a.verified_countries.join(", ")}`
                      : " · Organization country unverified / unknown"}
                  </small>
                </div>
                <StatusBadge status={a.review_status} />
                <ArrowRight size={18} />
              </a>
            ))}
            {data?.length === 0 && (
              <div className="state">
                <Users />
                <h3>No authors match these filters</h3>
              </div>
            )}
          </div>
        )}
      </State>
      <p className="collection-note">
        Names and original author order are preserved. Organization location
        does not establish nationality or residence.
      </p>
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      tone={
        status === "verified"
          ? "green"
          : status === "extracted"
            ? "blue"
            : "amber"
      }
    >
      {(
        {
          verified: "Verified",
          extracted: "Extracted",
          needs_review: "Needs review",
          no_evidence: "Evidence missing",
          failed: "Retry needed",
          not_started: "Not started",
        } as Record<string, string>
      )[status] || status.replaceAll("_", " ")}
    </Badge>
  );
}

function AssertionCard({
  assertion: a,
  reviewable = false,
}: {
  assertion: Row;
  reviewable?: boolean;
}) {
  const { api, refresh, setNotice } = useApp();
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [value, setValue] = useState(a.value);
  const [quote, setQuote] = useState(a.excerpt);
  const [source, setSource] = useState(a.source_url);
  async function review(action: string) {
    setBusy(true);
    try {
      const body: Row = { action, note };
      if (action === "correct")
        body.replacement = {
          kind: a.kind,
          value,
          organization:
            a.kind === "affiliation" || a.kind === "current_affiliation"
              ? value
              : a.organization || null,
          paper_id: a.paper_id,
          source_url: source,
          excerpt: quote,
          page: a.page,
          corroborating_paper_id: a.corroborating_paper_id,
        };
      const result = await api(`/assertions/${a.id}/review`, body);
      setNotice(result.message);
      refresh();
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="assertion-card">
      <div className="assertion-heading">
        <div>
          <small>
            {a.kind.replaceAll("_", " ")} · {a.author_name}
          </small>
          <h3>{a.value}</h3>
        </div>
        <StatusBadge status={a.status} />
      </div>
      <p>
        {a.time_context === "paper"
          ? `${a.paper_year} · ${a.paper_title}`
          : a.time_context === "current"
            ? "Current affiliation · separate from paper-time history"
            : "Identity evidence"}
        {a.organization && a.kind !== "affiliation"
          ? ` · ${a.organization}`
          : ""}
      </p>
      <details className="assertion-evidence">
        <summary>Inspect assertion evidence</summary>
        <blockquote>{a.excerpt}</blockquote>
        <a href={a.source_url} target="_blank" rel="noreferrer">
          Source URL <ExternalLink size={13} />
        </a>
        <dl>
          <div>
            <dt>Page</dt>
            <dd>{a.page ?? "Not available"}</dd>
          </div>
          <div>
            <dt>Method</dt>
            <dd>{a.method.replaceAll("_", " ")}</dd>
          </div>
          <div>
            <dt>Extracted</dt>
            <dd>{new Date(a.created * 1000).toLocaleString()}</dd>
          </div>
          <div>
            <dt>Verification</dt>
            <dd>
              {a.status === "verified"
                ? "Explicitly verified by analyst"
                : a.status.replaceAll("_", " ")}
            </dd>
          </div>
        </dl>
        {a.reviews?.map((h: Row) => (
          <p className="review-event" key={h.id}>
            <strong>{h.action}</strong> · {h.note}
            <br />
            {h.old_status} → {h.new_status} ·{" "}
            {new Date(h.created * 1000).toLocaleString()}
          </p>
        ))}
      </details>
      {reviewable && a.status !== "superseded" && (
        <div className="assertion-review">
          <label>
            Review note
            <input
              value={note}
              required
              onChange={(e) => setNote(e.target.value)}
              placeholder="What did you verify or reject?"
            />
          </label>
          <div className="toolbar">
            <button
              disabled={busy || !note.trim()}
              onClick={() => review("confirm")}
            >
              Verify assertion
            </button>
            <button
              disabled={busy || !note.trim()}
              onClick={() => review("reject")}
            >
              Reject assertion
            </button>
            <button
              onClick={() => setEditing(!editing)}
              aria-expanded={editing}
            >
              Correct with new evidence
            </button>
          </div>
          {editing && (
            <div className="correction-form">
              <label>
                Corrected value
                <input
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              </label>
              <label>
                Supporting source URL
                <input
                  type="url"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                />
              </label>
              <label>
                Replacement evidence excerpt
                <textarea
                  value={quote}
                  onChange={(e) => setQuote(e.target.value)}
                />
              </label>
              <button
                disabled={busy || !note.trim() || !quote.trim()}
                onClick={() => review("correct")}
              >
                Save correction for verification
              </button>
              <p>
                The original assertion remains in history. The replacement needs
                separate verification.
              </p>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function AuthorEvidenceDetail({ author: a }: { author: Row }) {
  const [showHistory, setShowHistory] = useState(false);
  return (
    <>
      <div className="detail-grid">
        <section className="panel">
          <h2>Affiliations over time</h2>
          <p>
            Each entry uses the paper year, not today’s date. Missing evidence
            stays unknown.
          </p>
          {a.paper_time_affiliations.length ? (
            a.paper_time_affiliations.map((claim: Row) => (
              <AssertionCard assertion={claim} key={claim.id} reviewable />
            ))
          ) : (
            <p>No evidence-backed paper-time affiliations extracted yet.</p>
          )}
          <h2>Verified current affiliation</h2>
          {a.verified_current_affiliations.length ? (
            a.verified_current_affiliations.map((claim: Row) => (
              <AssertionCard assertion={claim} key={claim.id} />
            ))
          ) : (
            <p>
              Unknown. A recent paper is not proof of a current affiliation.
            </p>
          )}
          <p className="info">{a.unsupported_fields_status}</p>
        </section>
        <section className="panel">
          <h2>Identity & profile evidence</h2>
          <p>
            {a.member_ids.length} original author record(s); original paper
            associations remain intact.
          </p>
          {a.members.map((m: Row) => (
            <p key={m.id}>
              {m.name}
              <br />
              <small className="record-id">{m.id}</small>
            </p>
          ))}
          <h3>Google Scholar</h3>
          {a.verified_profiles.map((p: Row) => (
            <p key={p.id}>
              <a href={p.value} target="_blank" rel="noreferrer">
                Verified Scholar profile <ExternalLink size={13} />
              </a>
            </p>
          ))}
          {!a.verified_profiles.length && (
            <p>
              No verified profile link. Missing or blocked lookup does not
              affect paper collection.
            </p>
          )}
          <a href={a.scholar_search_url} target="_blank" rel="noreferrer">
            Search Scholar manually <ExternalLink size={13} />
          </a>
          <p className="diagnostic-help">
            Supply the actual profile URL and an excerpt corroborating a known
            publication or verified ORCID. A same-name result is insufficient.
          </p>
          <ManualAssertion author={a} />
          <IdentityProposalForm author={a} />
        </section>
      </div>
      <section className="panel">
        <h2>Other assertions & review history</h2>
        {a.assertions
          .filter(
            (claim: Row) =>
              !["affiliation", "current_affiliation"].includes(claim.kind) &&
              !["rejected", "superseded"].includes(claim.status),
          )
          .map((claim: Row) => (
            <AssertionCard key={claim.id} assertion={claim} reviewable />
          ))}
        <button
          onClick={() => setShowHistory(!showHistory)}
          aria-expanded={showHistory}
        >
          {showHistory ? "Hide" : "Show"} all assertions, including rejected and
          superseded
        </button>
        {showHistory &&
          a.assertions.map((claim: Row) => (
            <AssertionCard key={claim.id} assertion={claim} reviewable />
          ))}
        {a.assertions
          .filter(
            (claim: Row) =>
              claim.kind === "current_affiliation" &&
              claim.status !== "verified" &&
              !["rejected", "superseded"].includes(claim.status),
          )
          .map((claim: Row) => (
            <AssertionCard key={claim.id} assertion={claim} reviewable />
          ))}
        {a.legacy_affiliations.length > 0 && (
          <details>
            <summary>
              Legacy affiliation metadata · evidence not retained
            </summary>
            {a.legacy_affiliations.map((l: Row, i: number) => (
              <p key={i}>
                {l.year} · {l.name} · {l.title}
                <br />
                <StatusBadge status="needs_review" /> No supporting assertion
                excerpt was retained; this is not a verified affiliation.
              </p>
            ))}
          </details>
        )}
      </section>
      <section className="panel">
        <h2>Publications</h2>
        <PaperList papers={a.papers} />
      </section>
      <IdentityReviews authorId={a.id} />
    </>
  );
}

function ManualAssertion({ author }: { author: Row }) {
  const { api, refresh, setNotice } = useApp();
  const [kind, setKind] = useState("affiliation");
  const [member, setMember] = useState(author.id);
  const [busy, setBusy] = useState(false);
  return (
    <details className="manual-assertion">
      <summary>Add an assertion with evidence</summary>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          try {
            const paper = String(f.get("paper") || "");
            const body = {
              kind,
              value: f.get("value"),
              organization: f.get("organization") || null,
              paper_id: kind === "current_affiliation" ? null : paper || null,
              source_url: f.get("source"),
              excerpt: f.get("excerpt"),
              page: f.get("page") ? Number(f.get("page")) : null,
              corroborating_paper_id:
                kind === "scholar_profile" ? paper || null : null,
            };
            const r = await api(`/authors/${member}/assertions`, body);
            setNotice(r.message);
            refresh();
          } catch (e) {
            setNotice((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Original author identity
          <select
            aria-label="Original author identity"
            value={member}
            onChange={(e) => setMember(e.target.value)}
          >
            {author.members.map((m: Row) => (
              <option value={m.id} key={m.id}>
                {m.name} · {m.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Assertion type
          <select
            aria-label="Assertion type"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="affiliation">Paper-time affiliation</option>
            <option value="organization_country">
              Organization country in paper
            </option>
            <option value="organization_city">
              Organization city in paper
            </option>
            <option value="orcid">ORCID</option>
            <option value="scholar_profile">Google Scholar profile link</option>
            <option value="current_affiliation">
              Separately evidenced current affiliation
            </option>
          </select>
        </label>
        {kind !== "current_affiliation" && (
          <label>
            Paper / corroborating publication
            <select
              name="paper"
              aria-label="Paper / corroborating publication"
              required={[
                "affiliation",
                "organization_country",
                "organization_city",
                "scholar_profile",
              ].includes(kind)}
            >
              <option value="">Select paper when applicable</option>
              {author.papers
                .filter((p: Row) => p.authors.some((a: Row) => a.id === member))
                .map((p: Row) => (
                  <option key={p.id} value={p.id}>
                    {p.year} · {p.title}
                  </option>
                ))}
            </select>
          </label>
        )}
        <label>
          Literal value or actual profile URL
          <input name="value" required maxLength={500} />
        </label>
        {kind.startsWith("organization_") && (
          <label>
            Exact organization name
            <input name="organization" required maxLength={300} />
          </label>
        )}
        <label>
          Evidence source URL
          <input name="source" type="url" required />
        </label>
        <label>
          Supporting excerpt
          <textarea name="excerpt" required minLength={3} maxLength={6000} />
        </label>
        {kind !== "current_affiliation" && (
          <label>
            Page, if available
            <input name="page" type="number" min="1" max="500" />
          </label>
        )}
        <button disabled={busy}>Save assertion · needs review</button>
        <p>
          Verification is a separate analyst action. Never supply nationality or
          residence inferred from an organization.
        </p>
      </form>
    </details>
  );
}

function IdentityProposalForm({ author }: { author: Row }) {
  const { api, setNotice } = useApp();
  const [busy, setBusy] = useState(false);
  return (
    <details className="identity-proposal-form">
      <summary>Propose an identity match</summary>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          try {
            const r = await api("/identity/proposals", {
              left_author_id: author.id,
              right_author_id: f.get("other"),
              source_url: f.get("source"),
              excerpt: f.get("excerpt"),
            });
            setNotice(r.message);
          } catch (e) {
            setNotice((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Other original author ID
          <input name="other" required />
        </label>
        <label>
          Corroborating source URL
          <input name="source" type="url" required />
        </label>
        <label>
          Evidence linking publications and identity
          <textarea name="excerpt" required minLength={3} maxLength={6000} />
        </label>
        <button disabled={busy}>Save proposal without merging</button>
        <p>
          Confirmation requires matching verified ORCID evidence, or verified
          affiliation overlap plus corroborating publication evidence. Names
          alone cannot be merged.
        </p>
      </form>
    </details>
  );
}

function IdentityReviews({ authorId }: { authorId?: string }) {
  const { api, refresh, setNotice } = useApp();
  const { data, error } = useData("/identity/proposals");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  return (
    <State data={data} error={error}>
      <section className="panel">
        <div className="results-heading">
          <h2>Identity match review</h2>
          <button
            onClick={async () => {
              try {
                const r = await api("/identity/discover", {});
                setNotice(r.message);
                refresh();
              } catch (e) {
                setNotice((e as Error).message);
              }
            }}
          >
            Find verified ORCID matches
          </button>
        </div>
        {data
          ?.filter(
            (p: Row) =>
              !authorId ||
              [p.left_author_id, p.right_author_id].includes(authorId),
          )
          .map((p: Row) => (
            <article className="identity-review" key={p.id}>
              <h3>
                {p.left_name} ↔ {p.right_name}
              </h3>
              <Badge>{p.status}</Badge>
              <p>{p.eligibility || p.reason}</p>
              <details>
                <summary>Inspect identity evidence & history</summary>
                <a href={p.source_url} target="_blank" rel="noreferrer">
                  Evidence source
                </a>
                <blockquote>{p.excerpt}</blockquote>
                {p.supporting_assertions.map((a: Row) => (
                  <AssertionCard assertion={a} key={a.id} />
                ))}
                {p.history.map((h: Row) => (
                  <p key={h.id}>
                    {h.action} · {h.note} ·{" "}
                    {new Date(h.created * 1000).toLocaleString()}
                  </p>
                ))}
              </details>
              <label>
                Identity review note
                <input
                  value={notes[p.id] || ""}
                  onChange={(e) =>
                    setNotes((n) => ({ ...n, [p.id]: e.target.value }))
                  }
                />
              </label>
              <div className="toolbar">
                {(p.status === "confirmed"
                  ? ["undo"]
                  : p.status === "pending"
                    ? ["confirm", "reject"]
                    : []
                ).map((action) => (
                  <button
                    key={action}
                    disabled={
                      busy === p.id ||
                      !notes[p.id]?.trim() ||
                      (action === "confirm" && !p.can_confirm)
                    }
                    onClick={async () => {
                      setBusy(p.id);
                      try {
                        const r = await api(
                          `/identity/proposals/${p.id}/review`,
                          { action, note: notes[p.id] },
                        );
                        setNotice(r.message);
                        refresh();
                      } catch (e) {
                        setNotice((e as Error).message);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    {action === "undo"
                      ? "Undo identity merge"
                      : action === "confirm"
                        ? "Confirm identity link"
                        : "Reject identity match"}
                  </button>
                ))}
              </div>
            </article>
          ))}
        {data?.length === 0 && (
          <p>No identity proposals. Identical names remain separate.</p>
        )}
      </section>
    </State>
  );
}

function PaperEnrichment({ paperId }: { paperId: string }) {
  const { api, refresh, setNotice } = useApp();
  const { data, error } = useData(`/papers/${paperId}/enrichment`);
  const [busy, setBusy] = useState(false);
  async function run(use_las: boolean) {
    setBusy(true);
    try {
      const result = await api(`/papers/${paperId}/enrich`, { use_las });
      setNotice(result.message);
      refresh();
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2 id="paper-enrichment">Author & organization enrichment</h2>
      <p>
        Deterministic metadata and explicit affiliation markers come first. LAS
        is used only when requested and needed. Paper content is treated as
        untrusted data.
      </p>
      <div className="toolbar">
        <button disabled={busy} onClick={() => run(false)}>
          Extract affiliations locally
        </button>
        <button disabled={busy} onClick={() => run(true)}>
          Enrich with LAS if needed
        </button>
      </div>
      <State data={data} error={error}>
        {data && (
          <>
            <StatusBadge status={data.state.status} />
            <p>
              Attempts: {data.state.attempts}.{" "}
              {data.state.error ||
                "Every extracted assertion requires evidence and separate verification."}
            </p>
            {data.state.retryable > 0 && (
              <p>
                Retryable failure. Paper browsing, full-text search, and
                previous assertions remain available.
              </p>
            )}
            {data.assertions.map((a: Row) => (
              <AssertionCard assertion={a} key={a.id} reviewable />
            ))}
            <details>
              <summary>Extraction run history</summary>
              {data.runs.map((r: Row) => (
                <p key={r.id}>
                  {r.method} · {r.status} ·{" "}
                  {new Date(r.started * 1000).toLocaleString()}
                  <br />
                  {r.error}
                </p>
              ))}
            </details>
          </>
        )}
      </State>
    </section>
  );
}

function AssertionReviews() {
  const { data, error } = useData("/assertions");
  return (
    <State data={data} error={error}>
      {data?.length > 0 && (
        <section className="panel">
          <h2>Author & organization assertions</h2>
          <p>
            Verify only what the excerpt supports. Verify an affiliation before
            verifying its location.
          </p>
          {data.map((a: Row) => (
            <AssertionCard assertion={a} key={a.id} reviewable />
          ))}
        </section>
      )}
    </State>
  );
}

function DiscoveryCard({ source }: { source: Row }) {
  const { api } = useApp();
  const [check, setCheck] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  async function inspect() {
    setBusy(true);
    setCheck(null);
    try {
      setCheck(await api("/discovery/inspect", { source_url: source.source_url }));
    } catch (e) {
      setCheck({ ok: false, message: (e as Error).message });
    } finally { setBusy(false); }
  }
  const year = check?.year || source.year;
  return (
    <article className="conference-card discovery-card">
      <div className="results-heading">
        <Badge tone="blue">{source.publisher}</Badge>
        <Badge tone={check?.ok ? "green" : check ? "amber" : ""}>
          {check?.ok ? "Inventory accessible" : check ? "Source unavailable" : "Collector available"}
        </Badge>
      </div>
      <h2>{source.name}</h2>
      <p className="discovery-year">{year || "Edition year needs checking"} · {source.track}</p>
      <a className="discovery-source" href={source.source_url} target="_blank" rel="noreferrer">
        {source.source_url} <ExternalLink size={14} />
      </a>
      <p className="diagnostic-help">Found in {source.origin.toLowerCase()}.</p>
      {check ? (
        <div className="discovery-check" role={check.ok ? "status" : "alert"}>
          {check.ok && <strong>{check.official_count?.toLocaleString() ?? "Unknown total"} listed papers</strong>}
          <p>{check.message}</p>
          {check.checked_at && <small>Checked {new Date(check.checked_at * 1000).toLocaleString()} · PDFs not checked</small>}
          {check.sample_titles?.length > 0 && (
            <details><summary>Preview paper titles</summary><ul>{check.sample_titles.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul></details>
          )}
        </div>
      ) : <p className="discovery-check">Check the official listing to see its paper count. PDF availability has not been checked.</p>}
      <div className="toolbar discovery-actions">
        <button onClick={inspect} disabled={busy}>
          <RefreshCw size={16} /> {busy ? "Checking source…" : check ? "Check again" : "Check source"}
        </button>
        {source.existing_edition_id ? (
          <button className="primary" onClick={() => navigate(`/conferences/${source.existing_edition_id}?collection=real`)}>Open in Real collection <ArrowRight size={16} /></button>
        ) : (
          <button className="primary" disabled={!check?.ok || !year} onClick={() => navigate("/add?" + queryParams({
            collection: "real", name: source.name.slice(0, 180), year: String(year), track: source.track,
            source_url: check?.source_url || source.source_url, adapter: source.adapter, from: location.hash.slice(1),
          }))}>Add to Real collection <ArrowRight size={16} /></button>
        )}
      </div>
      {check?.ok && !year && <p className="error">The listing does not establish an edition year. Add it manually with the correct event year.</p>}
    </article>
  );
}

function Discover() {
  const { refresh } = useApp();
  const [search, setSearch] = useSearchURL({ q: "", year: "", publisher: "all", directory: "starter", page: "1", page_size: "12" });
  const { data, error } = useData("/discovery/conferences?" + queryParams(search));
  const [input, setInput] = useState(search.q);
  useEffect(() => setInput(search.q), [search.q]);
  return (
    <>
      <a className="back" href={"#" + backRoute("/")}><ArrowLeft size={16} /> Back to Explore</a>
      <div className="page-heading">
        <div><div className="eyebrow">GROW YOUR COLLECTION</div><h1>Find conferences</h1>
          <p>Discover official proceedings with collectors available in endless tuna.</p></div>
        <button onClick={() => navigate("/add")}><Plus size={17} /> Add a source manually</button>
      </div>
      <form className="search-panel discovery-search" onSubmit={e => {
        e.preventDefault(); setSearch({ q: input.trim(), directory: "official", page: "1" });
      }}>
        <label className="search-field"><Search size={21} /><input aria-label="Search conference sources" placeholder="Conference name or subject, e.g. CoRL, robotics, learning…" value={input} maxLength={200} onChange={e => setInput(e.target.value)} /></label>
        <button className="primary" type="submit">Search official directory</button>
      </form>
      <p className="search-guidance">Search conference names, abbreviations and known subjects. Paper-content search is in Explore after collection. No LAS or search-provider setup needed.</p>
      <div className="discovery-filters">
        <label>Edition year<input aria-label="Discovery edition year" type="number" min="1900" max="2100" placeholder="Any year" value={search.year} onChange={e => setSearch({ year: e.target.value, page: "1" }, true)} /></label>
        <label>Proceedings source<select aria-label="Proceedings source" value={search.publisher} onChange={e => setSearch({ publisher: e.target.value, page: "1" })}>
          <option value="all">All supported sources</option><option value="PMLR">PMLR</option><option value="RSS">RSS</option><option value="NeurIPS">NeurIPS</option><option value="CVF">CVF / WACV</option>
        </select></label>
        <button onClick={() => { setInput(""); setSearch({ q: "", year: "", publisher: "all", page: "1" }); }}>Clear filters</button>
      </div>
      <div className="info">A collector can enumerate the published paper listing and attempt accessible PDFs. It cannot guarantee every PDF is downloadable. Source checks add no papers; adding a conference lets you choose a 10-paper sample or explicitly request the full edition in Real collection.</div>
      {error ? <div className="state error" role="alert"><h2>Couldn’t search conference sources</h2><p>{error}</p><button onClick={refresh}>Try again</button></div> : !data ? <div className="state" role="status"><span className="spinner" /> Searching conference sources…</div> : <>
        {data.warning && <p className="info" role="status">{data.warning}</p>}
        <div className="results-heading"><p><strong>{data.total}</strong> conference editions · {search.directory === "official" ? "Official directory + starter sources" : "Starter sources"}</p>
          {data.fetched_at && <small>PMLR directory retrieved {new Date(data.fetched_at * 1000).toLocaleString()} · cached up to 1 hour</small>}
        </div>
        {data.items.length ? <div className="conference-grid">{data.items.map((s: Row) => <DiscoveryCard key={s.source_url} source={s} />)}</div> : <div className="state"><Search size={30} /><h2>No matching conference sources</h2><p>Try a conference abbreviation or a broader subject. This searches supported official sources, not the entire web.</p><a href="#/add">Add another official source or CSV inventory</a></div>}
        <Pagination result={data} onPage={page => setSearch({ page: String(page) })} onSize={page_size => setSearch({ page_size, page: "1" })} />
        <p className="diagnostic-help">Directory coverage: <a href="https://proceedings.mlr.press/" target="_blank" rel="noreferrer">published PMLR volumes</a>, RSS 2025, WACV 2026, NeurIPS 2024 main proceedings and the NeurIPS 2026 paper listing. Other websites need an adapter or a CSV inventory. Older PMLR layouts may need adapter updates; use Check source before adding.</p>
      </>}
    </>
  );
}

function Add() {
  const { api, query, collection } = useApp();
  useEffect(() => {
    if (collection !== "real") {
      const target = new URLSearchParams(query); target.set("collection", "real");
      navigate("/add?" + target.toString());
    }
  }, [collection]);
  const [url, setURL] = useState(new URLSearchParams(query).get("source_url") || "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [all, setAll] = useState(false);
  const [name, setName] = useState("");
  const [year, setYear] = useState("");
  async function collect(value = url) {
    setBusy(true); setError("");
    try {
      const response = await api("/intake/collect", { url: value, full_collection: all, ...(result?.needs_details ? {preview_id: result.preview_id, name: name || undefined, year: year ? Number(year) : undefined} : {}) }, "real");
      if (response.ok) { navigate(`/conferences/${response.id}?collection=real`); return; }
      setResult(response);setName(response.name || "");setYear(response.year ? String(response.year) : "");
    } catch(e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <>
    <a className="back" href="#/"><ArrowLeft size={16} /> Explore conferences</a>
    <div className="page-heading"><div><div className="eyebrow">GROW YOUR RESEARCH COLLECTION</div><h1>Add conference</h1><p>Paste a link. We’ll collect the papers and find their free PDFs.</p></div></div>
    <form className="panel link-intake automatic-intake" onSubmit={e => {e.preventDefault();collect();}}>
      <label htmlFor="conference-link">Conference or proceedings link</label>
      <div className="link-entry"><input id="conference-link" type="text" inputMode="url" required autoFocus maxLength={2500} disabled={busy} value={url} placeholder="Paste a conference link…" onChange={e => {setURL(e.target.value);setResult(null);setError("");}}
        onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault();setURL(e.dataTransfer.getData("text/uri-list").split("\n").find(s => !s.startsWith("#")) || e.dataTransfer.getData("text/plain"));setResult(null);setError("");}} />
        <button className="primary" disabled={busy}>{busy ? "Finding the conference…" : "Collect papers"}<ArrowRight size={17} /></button></div>
      <div className="collection-scope"><label>Collection scope<select aria-label="Collection scope" disabled={busy} value={all ? "all" : "sample"} onChange={e => setAll(e.target.value === "all")}><option value="sample">First 10 papers · quick test</option><option value="all">Entire conference</option></select></label><p>Titles and available PDFs appear together. Collection continues in the background.</p></div>
      {result?.needs_details && <div className="intake-feedback"><h2>A quick clarification</h2><p>{result.message}</p><div className="form-columns"><label>Conference name<input required value={name} minLength={2} maxLength={180} onChange={e => setName(e.target.value)} /></label><label>Edition year<input required type="number" min="1900" max="2100" value={year} onChange={e => setYear(e.target.value)} /></label></div></div>}
      {error && <p className="error" role="alert">{error}</p>}
      {result && !result.needs_details && <div className="intake-feedback" role="alert"><h2>We need a paper-list link</h2><p>{result.message}</p>{result.suggestions?.length > 0 && <div className="suggested-sources">{result.suggestions.map((s: Row) => <button type="button" key={s.url} disabled={busy} onClick={() => {setURL(s.url);collect(s.url);}}>{s.label}<small>{s.url}</small><ArrowRight size={16} /></button>)}</div>}<p><a href="#/discover?collection=real">Find a published source</a> · <a href="#/add/advanced?collection=real">Import a paper list</a></p></div>}
      <p className="diagnostic-help">Uses Real collection. Free copies only; uncertain matches are flagged for review.</p>
    </form>
    <p className="diagnostic-help"><a href="#/discover?collection=real">Browse conference sources</a> · <a href="#/add/advanced?collection=real">Advanced import</a></p>
  </>;
}

function ManualAdd() {
  const { api, query, collection } = useApp();
  useEffect(() => {
    if (collection !== "real") {
      const target = new URLSearchParams(query); target.set("collection", "real");
      navigate("/add/manual?" + target.toString());
    }
  }, [collection]);
  const params = new URLSearchParams(query);
  const [url, setURL] = useState(params.get("source_url") || "");
  const [result, setResult] = useState<Row | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [year, setYear] = useState("");
  const [all, setAll] = useState(false);
  async function preview(value = url) {
    setBusy("preview"); setError(""); setResult(null);
    try {
      const valueResult = await api("/intake/preview", { url: value }, "real");
      setResult(valueResult);
      if (valueResult.ok) { setName(valueResult.name); setYear(String(valueResult.year || "")); }
    } catch(e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy("save"); setError("");
    try {
      const saved = await api("/intake/start", { preview_id: result?.preview_id, name, year: Number(year), full_collection: all, paper_limit: 10 }, "real");
      navigate(`/conferences/${saved.id}?collection=real`);
    } catch(e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }
  return <>
    <a className="back" href="#/"><ArrowLeft size={16} /> Explore conferences</a>
    <div className="page-heading"><div><div className="eyebrow">BUILD YOUR COLLECTION</div><h1>Add conference</h1><p>Paste a conference link. Save its paper list, then find free PDFs.</p></div></div>
    <ol className="intake-steps" aria-label="Collection workflow"><li className={!result?.ok ? "current" : ""}>1. Paste link</li><li className={result?.ok ? "current" : ""}>2. Review paper list</li><li>3. Find free PDFs</li></ol>
    <form className="panel link-intake" onSubmit={e => {e.preventDefault(); preview();}}>
      <label htmlFor="conference-link">Conference or proceedings link</label>
      <div className="link-entry"><input id="conference-link" type="text" inputMode="url" required autoFocus maxLength={2500} value={url} placeholder="https://proceedings.mlr.press/v270/" onChange={e => {setURL(e.target.value);setResult(null);setError("");}}
        onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault();setURL(e.dataTransfer.getData("text/uri-list").split("\n").find(s => !s.startsWith("#")) || e.dataTransfer.getData("text/plain"));setResult(null);}} />
        <button className="primary" disabled={!!busy}>{busy === "preview" ? "Reading paper list…" : "Preview paper list"}<ArrowRight size={17} /></button></div>
      <p className="diagnostic-help">Paste or drop a conference homepage, accepted-paper page, or proceedings link. New conferences are saved in Real collection. No downloads start here.</p>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {result && !result.ok && <section className="panel intake-feedback" role="alert"><h2>Let’s find the paper listing</h2><p>{result.message}</p>
      {result.suggestions?.length > 0 && <><p>Possible paper-list sources. Choose the one for your conference edition:</p><div className="suggested-sources">{result.suggestions.map((s: Row) => <button key={s.url} disabled={!!busy} onClick={() => {setURL(s.url);preview(s.url);}}>{s.label}<small>{s.url}</small><ArrowRight size={16} /></button>)}</div></>}
      <p><a href="#/discover?collection=real">Find a published conference</a> · <a href="#/add/advanced?collection=real">Import a custom source</a></p></section>}
    {result?.ok && <form className="panel link-intake" onSubmit={save}>
      <div className="results-heading"><h2>{result.listed_count.toLocaleString()} paper titles found</h2><Badge tone="green">Ready to save</Badge></div>
      <p className="diagnostic-help">{result.completeness} · <a href={result.source_url} target="_blank" rel="noreferrer">View source <ExternalLink size={13} /></a></p>
      <div className="form-columns"><label>Conference name<input required minLength={2} maxLength={180} value={name} onChange={e => setName(e.target.value)} /></label><label>Edition year<input required type="number" min="1900" max="2100" value={year} onChange={e => setYear(e.target.value)} /></label></div>
      <details open><summary>Preview titles</summary><ol className="title-preview">{result.titles.map((t:string,i:number) => <li key={i}>{t}</li>)}</ol>{result.listed_count > result.titles.length && <p>And {result.listed_count - result.titles.length} more titles.</p>}</details>
      <fieldset className="intake-scope"><legend>Paper list to save</legend><label><input type="radio" name="list-scope" checked={!all} onChange={() => setAll(false)} /> First {Math.min(10,result.listed_count)} titles · quick test</label><label><input type="radio" name="list-scope" checked={all} onChange={() => setAll(true)} /> All {result.listed_count.toLocaleString()} titles · no PDFs yet</label></fieldset>
      <button className="primary" disabled={!!busy || !year}>{busy === "save" ? "Saving…" : `Save ${all ? result.listed_count : Math.min(10,result.listed_count)} paper titles`}<ArrowRight size={17} /></button>
      <p className="diagnostic-help">You’ll review the saved list next and choose when to search for PDFs. Existing conferences open without creating duplicates.</p>
    </form>}
    <p className="diagnostic-help"><a href="#/discover?collection=real">Browse conference sources</a> · <a href="#/add/advanced?collection=real">Advanced import</a></p>
  </>;
}

function CollectionWorkflow({ editionId, baseline, initialStatus, sourceURL, conferenceName, conferenceYear }: { editionId: string; baseline: Row; initialStatus: string; sourceURL: string; conferenceName: string; conferenceYear: number }) {
  const { api, refresh, setNotice } = useApp();
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(false);
  useEffect(() => {
    let active = true, hadRunning = false;
    const load = async () => {
      try {
        const value = await api(`/conferences/${editionId}/workflow`);
        if (!active) return;
        setData(value); setError("");
        const running = value.jobs.some((j: Row) => ["queued", "running"].includes(j.status));
        const coverageChanged = ["inventory_records", "pdfs", "fulltext", "failed_jobs"].some(key => value.coverage[key] !== baseline[key]);
        const finishedBeforeFirstPoll = !running && value.jobs.length > 0 && ["queued", "collecting"].includes(initialStatus);
        if (coverageChanged || finishedBeforeFirstPoll || (hadRunning && !running)) { refresh(); return; }
        hadRunning = running;
      } catch(e) { if (active) setError((e as Error).message); }
    };
    load(); const timer = setInterval(load, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [editionId]);
  async function act(action: string) {
    setBusy(true);
    try {
      const latest = data?.jobs[0];
      if (action === "pause" && activeJob) await api(`/jobs/${activeJob.id}/cancel`, {});
      else if (action === "resume" && latest) await api(`/jobs/${latest.id}/resume`, {});
      else if (action === "retry" && latest && ["automatic", "pdfs"].includes(latest.kind) && ["failed", "partial"].includes(latest.status)) await api(`/jobs/${latest.id}/retry`, {});
      else if (c?.inventory_records && !unfinished && c?.missing_pdfs) await api(`/conferences/${editionId}/pdfs`, {full_collection: all});
      else {
        const response = await api("/intake/collect", {url:sourceURL,full_collection:all,name:conferenceName,year:conferenceYear});
        if (!response.ok) throw Error(response.message || "We could not read this source. Open Add conference to choose another paper-list link.");
      }
      refresh();
    } catch(e) { setNotice((e as Error).message); }
    finally { setBusy(false); }
  }
  async function run(kind: "inventory" | "pdfs") {
    setBusy(true);
    try { await api(`/conferences/${editionId}/${kind === "pdfs" ? "pdfs" : "collect"}`, {mode:kind,full_collection:all,paper_limit:10});refresh(); }
    catch(e) {setNotice((e as Error).message);} finally {setBusy(false);}
  }
  const activeJob = data?.jobs.find((j: Row) => ["queued", "running"].includes(j.status));
  const latest = data?.jobs[0];
  const c = data?.coverage;
  const paused = !activeJob && latest?.status === "cancelled";
  const attention = data?.needs_attention ?? 0;
  const unfinished = c?.official_count != null && c.inventory_records < c.official_count;
  const title = activeJob ? "Collecting papers" : paused ? "Collection paused" : attention > 0 || latest?.status === "failed" ? "Some papers need attention" : "Your papers";
  return <section className="panel collection-workflow" aria-label="Collection progress">
    <div className="results-heading"><h2>{title}</h2>{activeJob && <Badge tone="blue">Working in background</Badge>}</div>
    <div className="collection-counts"><div><strong>{c?.inventory_records ?? "…"}</strong><span>Titles found</span></div><div><strong>{c?.pdfs ?? "…"}</strong><span>PDFs downloaded</span></div><div><strong>{attention}</strong><span>Need attention</span></div></div>
    {error && <p role="alert" className="error">{error}</p>}
    {activeJob ? <div className="workflow-progress" role="status"><strong>{activeJob.progress <= 10 ? "Finding and saving paper titles…" : "Finding free PDFs…"}</strong><progress value={activeJob.progress} max={100} aria-label="Current collection progress" /><p>{activeJob.paper_limit == null ? "Entire conference" : `Up to ${activeJob.paper_limit} papers`}. You can browse below or leave this page. We’ll keep collecting.</p><button disabled={busy} onClick={() => act("pause")}>Pause collection</button></div> : <>
      <p>{paused ? "Saved papers and PDFs are kept. Resume whenever you’re ready." : latest?.status === "failed" ? latest.message : attention > 0 ? "Available PDFs are ready below. Some copies could not be found or need your review." : "Open a paper below to read its details and available PDF."}</p>
      {unfinished && <p className="diagnostic-help">{c.inventory_records} of {c.official_count} listed titles collected. The current batch does not cover the entire conference.</p>}
      <div className="toolbar">{paused ? <button className="primary" disabled={busy} onClick={() => act("resume")}>Resume collection</button> : <>
        {(unfinished || !latest || latest.kind === "inventory" || attention > 0 || c?.missing_pdfs > 0 || latest.status === "failed") && <button className="primary" disabled={busy} onClick={() => act(attention > 0 || latest?.status === "failed" ? "retry" : "continue")}>{busy ? "Starting…" : attention > 0 || latest?.status === "failed" ? "Try missing papers again" : "Continue collecting"}</button>}
        {unfinished && <label>Scope<select aria-label="Continue collection scope" value={all ? "all" : "sample"} onChange={e => setAll(e.target.value === "all")}><option value="sample">Next 10 papers</option><option value="all">Entire conference</option></select></label>}
      </>}{attention > 0 && <a href="#/review">Review possible matches</a>}</div>
    </>}
    <details className="collection-tools"><summary>Collection details & tools</summary>
      <p>{latest?.message || "No collection has run yet."}</p><p>{c?.ocr_required ?? 0} PDFs need OCR to become searchable. <a href="#/jobs">View background history</a></p>
      <label className="scope-check"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} /> Process all remaining papers instead of the next 10</label>
      <div className="toolbar"><button disabled={busy || !!activeJob || !c?.missing_pdfs} onClick={() => run("pdfs")}>Find free PDFs · next 10</button><button disabled={busy || !!activeJob} onClick={() => run("inventory")}>Refresh paper list</button></div>
    </details>
  </section>;
}

function AdvancedAdd() {
  const { api, collection, query } = useApp();
  const prefill = new URLSearchParams(query);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api("/conferences", {
        name: form.get("name"),
        year: Number(form.get("year")),
        track: form.get("track"),
        source_url: form.get("source_url"),
        adapter: form.get("adapter"),
        paper_limit: Number(form.get("paper_limit")),
        full_collection: form.get("full_collection") === "on",
      });
      navigate("/jobs");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <a className="back" href="#/">
        <ArrowLeft size={16} /> Explore conferences
      </a>
      <h1>Add conference</h1>
      <p>Start with an official accepted-paper listing or proceedings page.</p>
      <p><a href={"#/discover?" + queryParams({ collection, from: location.hash.slice(1) })}>Find conferences with supported collectors <ArrowRight size={15} /></a></p>
      {collection === "demo" && (
        <p className="info">You are adding to Demo data. For an actual conference, switch the collection selector to Real collection before submitting.</p>
      )}
      <form className="panel add-form" onSubmit={submit}>
        <button type="button" onClick={e => {
          const form = e.currentTarget.form;
          if (!form) return;
          for (const [name, value] of Object.entries({name: "NeurIPS 2026", year: "2026", track: "All published tracks", source_url: "https://neurips.cc/virtual/2026/papers.html", adapter: "auto"})) {
            const field = form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null;
            if (field) field.value = value;
          }
          const full = form.elements.namedItem("full_collection") as HTMLInputElement | null;
          if (full) full.checked = true;
        }}>Use NeurIPS 2026 · all listed papers</button>
        <button type="button" onClick={e => {
          const form = e.currentTarget.form;
          if (!form) return;
          for (const [name, value] of Object.entries({name: "NeurIPS", year: "2024", track: "Main Conference", source_url: "https://papers.nips.cc/paper_files/paper/2024", adapter: "auto"})) {
            const field = form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null;
            if (field) field.value = value;
          }
          const full = form.elements.namedItem("full_collection") as HTMLInputElement | null;
          if (full) full.checked = false;
        }}>Use supported NeurIPS 2024 example</button>
        <label>
          Conference name
          <input
            name="name"
            defaultValue={prefill.get("name") || ""}
            required
            minLength={2}
            maxLength={180}
            placeholder="e.g. Coastal Robotics Forum"
          />
        </label>
        <div className="form-columns">
          <label>
            Edition year
            <input
              name="year"
              type="number"
              min="1900"
              max="2100"
              defaultValue={prefill.get("year") || 2024}
              required
            />
          </label>
          <label>
            Track or workshop
            <input
              name="track"
              defaultValue={prefill.get("track") || "Main research track"}
              required
              maxLength={180}
            />
          </label>
        </div>
        <label>
          Official source URL
          <input
            name="source_url"
            defaultValue={prefill.get("source_url") || ""}
            type="url"
            required
            placeholder="https://conference.example/accepted-papers"
          />
        </label>
        <label>
          Source adapter
          <select name="adapter" aria-label="Source adapter" defaultValue={prefill.get("adapter") || "auto"}>
            <option value="auto">Auto: supported proceedings, .csv or .json</option>
            <option value="pmlr-volume">PMLR proceedings volume</option>
            <option value="rss-2025">RSS 2025 proceedings</option>
            <option value="wacv-2026-program">WACV 2026 official paper list</option>
            <option value="neurips-2024-main">NeurIPS 2024 main proceedings</option>
            <option value="neurips-2026-program">NeurIPS 2026 program</option>
            <option value="metadata">
              Explicit citation-metadata / JSON source
            </option>
            <option value="csv">CSV inventory file URL</option>
          </select>
        </label>
        <label>
          Sample paper limit
          <input
            name="paper_limit"
            type="number"
            min="1"
            max="100"
            defaultValue="10"
            required
          />
        </label>
        <label className="scope-check">
          <input name="full_collection" type="checkbox" />
          Collect the full edition instead of a sample (may download thousands
          of PDFs)
        </label>
        <div className="info">
          Supported live sources: WACV 2026, PMLR proceedings volumes, RSS 2025 proceedings, NeurIPS 2026 official virtual paper listing
          (published tracks kept separate) and NeurIPS 2024 main proceedings.
          Workshops outside the official paper listing are not included.
          Other conference websites are unsupported unless you supply a
          supported inventory format. A conference homepage is not a paper inventory;
          choosing CSV requires an actual CSV file URL. The 2026 example selects
          all listed papers; otherwise the default sample is 10 papers. PDFs are
          downloaded only when accessible; source access failures remain visible.
          This creates a durable
          collection job in the {collection} collection. Deterministic metadata
          and accessible PDFs can be collected without LAS. AI extraction
          requires a configured LAS model and an explicit action.
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy ? "Adding…" : "Add conference & queue job"}
          <ArrowRight size={17} />
        </button>
      </form>
    </>
  );
}
function Jobs() {
  const { api, refresh, setNotice } = useApp();
  const { data, error } = useData("/jobs");
  useEffect(() => {
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);
  const [busy, setBusy] = useState("");
  async function action(jid: string, a: string) {
    setBusy(jid);
    try {
      await api(`/jobs/${jid}/${a}`, {});
      refresh();
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">BUILD YOUR COLLECTION</div>
          <h1>Collection jobs</h1>
          <p>Durable progress, clear checkpoints, and recoverable failures.</p>
        </div>
        <button onClick={refresh}>
          <RefreshCw size={16} /> Refresh
        </button>
      </div>
      <div className="info">
        Collection runs automatically in the background. Open a conference to see its papers, available PDFs and anything that needs attention.
      </div>
      <State data={data} error={error}>
        {data?.length ? (
          data.map((j: Row) => (
            <section className="panel job" data-job-id={j.id} key={j.id}>
              <div className="results-heading">
                <h2>
                  {j.name} {j.year}
                </h2>
                <Badge tone={j.status === "failed" ? "amber" : ""}>
                  {j.status}
                </Badge>
              </div>
              <p><Badge tone="blue">{j.kind === "inventory" ? "Paper list" : j.kind === "pdfs" ? "Free PDFs" : "Papers & free PDFs"}</Badge> <a href={`#/conferences/${j.edition_id}`}>Open paper list & next steps <ArrowRight size={14} /></a></p>
              <progress
                value={j.progress}
                max={100}
                aria-label={`Collection progress for ${j.name}`}
              />
              <p>
                {j.progress}% · Attempt {j.attempts}
              </p>
              <ol className="pipeline-stages" aria-label="Collection stages">
                {j.stages?.map((stage: Row) => (
                  <li
                    key={stage.key}
                    className={
                      stage.total && stage.completed === stage.total
                        ? "stage-done"
                        : ""
                    }
                  >
                    <span>{stage.label}</span>
                    <small>
                      {stage.completed}/{stage.total}
                    </small>
                  </li>
                ))}
              </ol>
              <p>{j.message}</p>
              <p className="coverage-line">
                {j.paper_limit == null
                  ? "Full edition requested"
                  : `Sample cap: ${j.paper_limit} papers`}{" "}
                · Official total: {j.official_count ?? "unknown"}
              </p>
              {j.failures?.length > 0 && (
                <details className="paper-failures">
                  <summary>{j.failures.length} papers need attention</summary>
                  {j.failures.map((f: Row) => (
                    <div key={f.paper_id}>
                      <a href={`#/papers/${f.paper_id}`}>{f.title}</a>
                      <p>
                        {f.stage} · {f.status} · {f.error}
                      </p>
                    </div>
                  ))}
                </details>
              )}
              <div className="toolbar">
                {(["queued", "running"].includes(j.status)
                  ? ["cancel"]
                  : ["failed", "partial"].includes(j.status)
                    ? ["retry", "resume"]
                    : j.status === "cancelled"
                      ? ["resume"]
                      : []
                ).map((a) => (
                  <button
                    key={a}
                    disabled={busy === j.id}
                    onClick={() => action(j.id, a)}
                  >
                    {a[0].toUpperCase() + a.slice(1)}
                  </button>
                ))}
                <a href={`#/conferences/${j.edition_id}`}>View conference →</a>
              </div>
            </section>
          ))
        ) : (
          <div className="state">
            <Waves size={32} />
            <h3>No collection jobs yet</h3>
            <p>Add a conference to queue your first job.</p>
            <button onClick={() => navigate("/add")}>Add conference</button>
          </div>
        )}
      </State>
    </>
  );
}
function ReviewQueue() {
  const { api, refresh, setNotice, collection } = useApp();
  const { data, error } = useData("/papers?review=uncertain");
  const [busy, setBusy] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>, pid: string) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(pid);
    try {
      await api(`/papers/${pid}/review`, {
        action: form.get("action"),
        title: form.get("title"),
        note: form.get("note"),
      });
      refresh();
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">A LITTLE HUMAN JUDGMENT</div>
          <h1>Review queue</h1>
          <p>Inspect source evidence before confirming uncertain records.</p>
        </div>
        <Badge tone="amber">{data?.length ?? "…"} to review</Badge>
      </div>
      <AssertionReviews />
      <IdentityReviews />
      <PDFCandidateReviews />
      <State data={data} error={error}>
        {data?.length ? (
          data.map((p: Row) => (
            <form
              className="panel review-form"
              key={p.id}
              onSubmit={(e) => submit(e, p.id)}
            >
              <a
                href={`#/papers/${p.id}?${queryParams({ collection, from: location.hash.slice(1) })}`}
              >
                Inspect paper, affiliations & evidence{" "}
                <ExternalLink size={14} />
              </a>
              <p>
                {p.conference} {p.year}
              </p>
              <label>
                Paper title
                <input
                  name="title"
                  defaultValue={p.title}
                  required
                  maxLength={500}
                />
              </label>
              <label>
                Review note
                <textarea
                  name="note"
                  placeholder="What did you verify or correct?"
                  maxLength={2000}
                />
              </label>
              <div className="toolbar">
                <label>
                  Decision
                  <select name="action">
                    <option value="confirm">Confirm</option>
                    <option value="correct">Correct and confirm</option>
                    <option value="reject">Reject</option>
                  </select>
                </label>
                <button className="primary" disabled={busy === p.id}>
                  <Check size={17} /> Save review
                </button>
              </div>
            </form>
          ))
        ) : (
          <div className="state">
            <Check size={32} />
            <h3>You’re all caught up</h3>
            <p>No uncertain papers in this collection.</p>
          </div>
        )}
      </State>
    </>
  );
}
function CSVInventory({ editionId }: { editionId: string }) {
  const { api, setNotice } = useApp();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <section className="panel">
      <details>
        <summary>Import a CSV paper inventory</summary>
        <p>
          Required columns: title, authors (JSON array), official_url,
          inventory_url, year, track. Optional: abstract, pdf_url, doi, arxiv.
          Every row must match this edition and one track.
        </p>
        <label>
          CSV inventory file
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (file) {
                if (file.size > 10000000) {
                  setNotice("CSV exceeds 10 MB.");
                  return;
                }
                setText(await file.text());
              }
            }}
          />
        </label>
        <label>
          CSV inventory text
          <textarea
            aria-label="CSV inventory text"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <button
          disabled={busy || !text}
          onClick={async () => {
            setBusy(true);
            try {
              await api(`/conferences/${editionId}/inventory/csv`, {
                csv_text: text,
              });
              navigate("/jobs");
            } catch (e) {
              setNotice((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Import inventory & queue collection
        </button>
      </details>
    </section>
  );
}

function PaperSources({ paper }: { paper: Row }) {
  const { api, download, setNotice } = useApp();
  const [url, setUrl] = useState("");
  const [version, setVersion] = useState("analyst-supplied");
  const [pages, setPages] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <section className="panel paper-sources">
      <h2>Sources, versions & full text</h2>
      {paper.memberships?.map((m: Row) => (
        <p key={m.edition_id + m.track_id}>
          <strong>
            {m.name} {m.year} · {m.track}
          </strong>
          <br />
          <a href={m.inventory_url} target="_blank" rel="noreferrer">
            Inventory evidence
          </a>{" "}
          ·{" "}
          <a href={m.official_url} target="_blank" rel="noreferrer">
            Official paper page
          </a>
          <br />
          <small>
            Retrieved:{" "}
            {m.retrieved
              ? new Date(m.retrieved * 1000).toLocaleString()
              : "Fictional demo / legacy record"}
          </small>
        </p>
      ))}
      {paper.identifiers?.map((x: Row) => (
        <Badge key={x.namespace + x.value}>
          {x.namespace}: {x.value}
        </Badge>
      ))}
      {paper.downloads.map((d: Row) => (
        <div className="download-version" key={d.id}>
          <Badge>{d.version}</Badge>
          <p>
            {d.status} · {d.parse_status}
            {d.size_bytes ? ` · ${(d.size_bytes / 1000000).toFixed(2)} MB` : ""}
          </p>
          {d.source_url && (
            <a href={d.source_url} target="_blank" rel="noreferrer">
              PDF source URL
            </a>
          )}
          {d.sha256 && (
            <small>
              SHA-256: {d.sha256}
              <br />
              Retrieved {new Date(d.retrieved * 1000).toLocaleString()}
            </small>
          )}
          {d.error && <p>{d.error}</p>}
          {d.status === "available" && (
            <button
              onClick={() =>
                download(
                  `/papers/${paper.id}/pdf?download_id=${d.id}`,
                  `${paper.id}.pdf`,
                )
              }
            >
              Download this version
            </button>
          )}
        </div>
      ))}
      <button
        onClick={async () => {
          try {
            setPages(await api(`/papers/${paper.id}/pages`));
          } catch (e) {
            setNotice((e as Error).message);
          }
        }}
      >
        Show indexed PDF text with pages
      </button>
      {pages && (
        <details open>
          <summary>{pages.length} indexed page records</summary>
          {pages.slice(0, 100).map((p) => (
            <div className="indexed-page" key={p.download_id + p.page}>
              <strong>
                Page {p.page} · {p.version}
              </strong>
              <p>{p.text || "No text detected — OCR may be required."}</p>
            </div>
          ))}
        </details>
      )}
      <h3>Find a missing PDF</h3>
      <p>
        Web-search provider:{" "}
        {paper.search_provider?.configured ? "configured" : "not configured"}.{" "}
        <a href={paper.manual_search_url} target="_blank" rel="noreferrer">
          Search manually for this paper
        </a>
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            const r = await api(`/papers/${paper.id}/pdf-candidates`, {
              url,
              version,
            });
            setNotice(r.message);
            setUrl("");
          } catch (e) {
            setNotice((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Candidate PDF URL
          <input
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://public-source.example/paper.pdf"
          />
        </label>
        <label>
          Version
          <select value={version} onChange={(e) => setVersion(e.target.value)}>
            <option value="analyst-supplied">Analyst-supplied / unknown</option>
            <option value="proceedings">Proceedings version</option>
            <option value="arxiv">arXiv version</option>
          </select>
        </label>
        <button disabled={busy}>Submit PDF for review</button>
      </form>
    </section>
  );
}

function PDFCandidateReviews() {
  const { api, refresh, setNotice } = useApp();
  const { data, error } = useData("/pdf-candidates");
  const [busy, setBusy] = useState("");
  return (
    <State data={data} error={error}>
      {data?.length > 0 && (
        <section className="panel">
          <h2>PDF candidates requiring review</h2>
          {data.map((c: Row) => (
            <article className="candidate-review" key={c.id}>
              <h3>{c.paper_title}</h3>
              <Badge tone="amber">{c.version}</Badge>
              <p>
                Candidate title: {c.title}
                <br />
                Candidate authors: {JSON.parse(c.authors).join(" · ")}
              </p>
              <p>{c.reason}</p>
              <a href={c.url} target="_blank" rel="noreferrer">
                Inspect candidate source
              </a>
              <div className="toolbar">
                {["confirm", "reject"].map((action) => (
                  <button
                    key={action}
                    disabled={busy === c.id}
                    onClick={async () => {
                      setBusy(c.id);
                      try {
                        await api(`/pdf-candidates/${c.id}/review`, {
                          action,
                          note: "Analyst reviewed candidate source and version",
                        });
                        refresh();
                      } catch (e) {
                        setNotice((e as Error).message);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    {action === "confirm"
                      ? "Confirm PDF & queue download"
                      : "Reject candidate"}
                  </button>
                ))}
              </div>
            </article>
          ))}
        </section>
      )}
    </State>
  );
}

function LASDiagnostics({ configuration }: { configuration: Row }) {
  const { api } = useApp();
  const [models, setModels] = useState<string[] | null>(null);
  const [choice, setChoice] = useState(configuration.model || "");
  const [currentModel, setCurrentModel] = useState(configuration.model || "");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<Row | null>(null);
  async function action(kind: string) {
    setBusy(kind);
    setResult(null);
    try {
      const value = await api(
        `/las/${kind}`,
        kind === "model" ? { model: choice } : {},
      );
      setResult(value);
      if (value.ok && kind === "discover") {
        setModels(value.models);
        setChoice(value.models.includes(currentModel) ? currentModel : "");
      }
      if (value.ok && kind === "model") setCurrentModel(value.model);
    } catch (e) {
      setResult({
        ok: false,
        code: "application_error",
        message: (e as Error).message,
      });
    } finally {
      setBusy("");
    }
  }
  return (
    <section className="panel las-panel">
      <h2>LAS diagnostics</h2>
      <Badge tone={configuration.configured ? "blue" : "amber"}>
        {configuration.configured
          ? "Configured · access unverified"
          : "LAS configuration required"}
      </Badge>
      <dl>
        <div>
          <dt>Credentials</dt>
          <dd>
            {configuration.credentials_configured
              ? "Configured"
              : "Not configured"}
          </dd>
        </div>
        <div>
          <dt>Selected model</dt>
          <dd>{currentModel || "No model selected"}</dd>
        </div>
      </dl>
      <p>{configuration.message}</p>
      <p className="diagnostic-help">
        Configure the server’s local .env file, then restart. Credentials stay
        on the server. Opening Settings sends no LAS requests.
      </p>
      <div className="toolbar">
        <button disabled={!!busy} onClick={() => action("discover")}>
          <RefreshCw size={16} />
          {busy === "discover" ? "Checking…" : "Check connection"}
        </button>
      </div>
      {models !== null && (
        <div className="model-selection">
          <label htmlFor="las-model">Discovered model ID</label>
          <select
            id="las-model"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            disabled={!!busy}
          >
            <option value="">Choose a returned model ID</option>
            {models.map((model) => (
              <option value={model} key={model}>
                {model}
              </option>
            ))}
          </select>
          <button disabled={!choice || !!busy} onClick={() => action("model")}>
            {busy === "model" ? "Saving…" : "Use model"}
          </button>
          {!models.length && (
            <p>
              The gateway returned no model IDs. Check account/model
              permissions.
            </p>
          )}
        </div>
      )}
      <div className="toolbar">
        <button
          className="primary"
          disabled={!!busy || !currentModel}
          onClick={() => action("test")}
        >
          {busy === "test" ? "Testing…" : "Test model"}
        </button>
      </div>
      <p className="diagnostic-help">
        Test model explicitly sends one tiny chat completion. No automatic
        inference or provider fallback.
      </p>
      {result && (
        <div
          className={"info " + (!result.ok ? "diagnostic-error" : "")}
          role={result.ok ? "status" : "alert"}
        >
          <strong>{result.code.replaceAll("_", " ")}</strong>
          <p>{result.message}</p>
          {result.retryable && (
            <span>Retry when the service or network is available.</span>
          )}
        </div>
      )}
      <p className="diagnostic-help">
        A 403 means access was denied. Check permissions or network access; it
        does not prove the API key is wrong.
      </p>
    </section>
  );
}

function LASExtraction({
  paperId,
  parsed,
  available,
}: {
  paperId: string;
  parsed: boolean;
  available: boolean;
}) {
  const { api } = useApp();
  const [parsedLocal, setParsedLocal] = useState(parsed);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Row | null>(null);
  return (
    <div className="las-extraction">
      <h2>AI-assisted extraction</h2>
      <p>
        {parsedLocal
          ? "Create an unverified proposal from the parsed PDF. Review it against the source."
          : "A parsed text-based PDF is needed for extraction. Stored metadata and PDF access remain available."}
      </p>
      {available && !parsedLocal && (
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const value = await api(`/papers/${paperId}/pdf/parse`, {});
              setParsedLocal(true);
              setResult(value);
            } catch (e) {
              setResult({ ok: false, message: (e as Error).message });
            } finally {
              setBusy(false);
            }
          }}
        >
          Parse stored PDF locally
        </button>
      )}
      <button
        disabled={busy || !parsedLocal}
        onClick={async () => {
          setBusy(true);
          try {
            setResult(await api(`/papers/${paperId}/extract`, {}));
          } catch (e) {
            setResult({ ok: false, message: (e as Error).message });
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Extracting…" : "Extract with LAS"}
      </button>
      <p className="diagnostic-help">
        Explicitly sends document text to the configured LAS model.{" "}
        <a href="#/settings">LAS settings</a>
      </p>
      {result && (
        <div className="info" role={result.ok ? "status" : "alert"}>
          <p>{result.message}</p>
          {result.proposal && (
            <>
              <h3>{result.proposal.title}</h3>
              <p>{result.proposal.abstract}</p>
              <blockquote>{result.proposal.evidence_quote}</blockquote>
              <Badge tone="amber">Unverified · review required</Badge>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function SettingsPage() {
  const { api, collection, refresh, setNotice } = useApp();
  const { data, error } = useData("/settings");
  const [confirm, setConfirm] = useState(false);
  return (
    <>
      <h1>Settings</h1>
      <p>Local configuration and LAS diagnostics.</p>
      <State data={data} error={error}>
        {data && (
          <div className="detail-grid">
            <section className="panel">
              <h2>Application</h2>
              <dl>
                {[
                  ["Collection", data.collection],
                  ["Database", data.database],
                  ["PDF storage", data.pdf_storage],
                  ["Worker", data.worker],
                  ["Version", data.version],
                ].map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <LASDiagnostics configuration={data.las} />
            {collection === "demo" && (
              <section className="panel">
                <h2>Reset demo collection</h2>
                <p>
                  Restore the fictional sample records. This removes edits and
                  jobs in the demo collection.
                </p>
                {confirm ? (
                  <div className="toolbar">
                    <button
                      className="danger"
                      onClick={async () => {
                        try {
                          await api("/demo/reset", {});
                          setConfirm(false);
                          refresh();
                          setNotice("Demo collection restored.");
                        } catch (e) {
                          setNotice((e as Error).message);
                        }
                      }}
                    >
                      Confirm reset
                    </button>
                    <button onClick={() => setConfirm(false)}>
                      Keep my changes
                    </button>
                  </div>
                ) : (
                  <button onClick={() => setConfirm(true)}>
                    Reset demo data
                  </button>
                )}
              </section>
            )}
          </div>
        )}
      </State>
    </>
  );
}
function Library() {
  const [search, setSearch] = useSearchURL({
    q: "",
    ...blank,
    page: "1",
    page_size: "25",
  });
  const result = useData("/search/papers?" + queryParams(search));
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR INDEXED RESEARCH</div>
          <h1>Library</h1>
          <p>
            Local keyword search across conference metadata, titles, abstracts
            and indexed PDF text.
          </p>
        </div>
        <Badge>{result.data?.total ?? "…"} matching papers</Badge>
      </div>
      <input
        className="directory-search"
        aria-label="Search library"
        placeholder='Search terms or "quoted phrases"…'
        value={search.q}
        onChange={(e) => setSearch({ q: e.target.value, page: "1" }, true)}
      />
      <State {...result}>
        <PaperList papers={result.data?.items || []} />
      </State>
      <Pagination
        result={result.data}
        onPage={(n) => setSearch({ page: String(n) })}
        onSize={(n) => setSearch({ page_size: n, page: "1" })}
      />
      <ExportPanel filters={search} />
    </>
  );
}
function App() {
  const [route, setRoute] = useState(location.hash.slice(1) || "/");
  const [collection, setCollection] = useState(
    new URLSearchParams(location.hash.split("?")[1] || "").get("collection") ===
      "real"
      ? "real"
      : new URLSearchParams(location.hash.split("?")[1] || "").get(
            "collection",
          ) === "demo"
        ? "demo"
        : localStorage.getItem("tuna-collection") === "real"
          ? "real"
          : "demo",
  );
  useEffect(() => {
    const [base, raw = ""] = route.split("?");
    const params = new URLSearchParams(raw);
    const requested = params.get("collection");
    if (requested === "demo" || requested === "real") {
      localStorage.setItem("tuna-collection", requested);
      if (requested !== collection) setCollection(requested);
    } else {
      params.set("collection", collection);
      const canonical = base + "?" + params;
      history.replaceState(null, "", "#" + canonical);
      setRoute(canonical);
    }
  }, [route, collection]);
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const fn = () => setRoute(location.hash.slice(1) || "/");
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  const api = async (path: string, body?: unknown, targetCollection?: string) => {
    const r = await fetch("/api" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "X-Collection": targetCollection || collection,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      let msg = `Request failed (${r.status})`;
      try {
        const e = await r.json();
        msg =
          typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail);
      } catch {}
      throw Error(msg);
    }
    return r.json();
  };
  const download = async (path: string, name: string) => {
    try {
      const r = await fetch("/api" + path, {
        headers: { "X-Collection": collection },
      });
      if (!r.ok) throw Error("File unavailable");
      const u = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = u;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    } catch (e) {
      setNotice((e as Error).message);
    }
  };
  const refresh = () => setRevision((v) => v + 1);
  const [path, query = ""] = route.split("?");
  const segments = path.split("/").filter(Boolean);
  const section = segments[0] || "explore";
  const id = segments[1];

  return (
    <AppContext.Provider
      value={{
        api,
        download,
        refresh,
        collection,
        id,
        query,
        setNotice,
        revision,
      }}
    >
      <>
        <header>
          <a className="brand" href="#/" aria-label="endless tuna home">
            <img className="brand-mark" src="/favicon.svg" width="82" height="43" alt="" aria-hidden="true" />
            <span className="brand-wordmark">endless<em>tuna</em></span>
          </a>
          <nav aria-label="Main navigation">
            {[
              ["/", "Explore"],
              ["/library", "Library"],
              ["/authors", "Authors"],
            ].map(([url, label]) => (
              <a
                key={url}
                className={
                  (
                    url === "/"
                      ? section === "explore" || section === "conferences" || section === "discover"
                      : path.startsWith(url)
                  )
                    ? "active"
                    : ""
                }
                href={"#" + url}
              >
                {label}
              </a>
            ))}
            <details className="nav-more" key={path}
              onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.open = false; }}
              onKeyDown={e => { if (e.key === "Escape") { e.currentTarget.open = false; e.currentTarget.querySelector("summary")?.focus(); } }}>
              <summary className={section === "jobs" || section === "review" ? "active" : ""}>More <ChevronDown size={14} /></summary>
              <div className="nav-more-links">
                <a href="#/jobs" aria-current={section === "jobs" ? "page" : undefined}>Collection jobs</a>
                <a href="#/review" aria-current={section === "review" ? "page" : undefined}>Review queue</a>
              </div>
            </details>
          </nav>
          {section !== "add" && <button className="primary header-add" aria-label="Add conference" onClick={() => navigate("/add")}><Plus size={18} /><span>Add conference</span></button>}
          <a
            className={
              "settings-link " + (section === "settings" ? "active" : "")
            }
            href="#/settings"
            aria-label="Settings"
          >
            <Settings size={21} />
          </a>
        </header>
        <div className="collection-bar">
          <div>
            <span className="live-dot" />
            {collection === "demo"
              ? "Demo data · fictional research"
              : "Your collection · stored locally"}
          </div>
          <label>
            Collection
            <select
              aria-label="Collection"
              value={collection}
              onChange={(e) => {
                navigate("/?collection=" + e.target.value);
              }}
            >
              <option value="demo">Demo data</option>
              <option value="real">Real collection</option>
            </select>
          </label>
        </div>
        {notice && (
          <div className="notice" role="status">
            {notice}
            <button
              className="icon-button"
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              <X size={18} />
            </button>
          </div>
        )}
        <main key={collection + section + id}>
          {section === "explore" ? (
            <Explore />
          ) : section === "discover" ? (
            <Discover />
          ) : section === "conferences" ? (
            <Conference />
          ) : section === "papers" ? (
            <Paper />
          ) : section === "authors" ? (
            <Authors />
          ) : section === "add" ? (
            id === "advanced" ? <AdvancedAdd /> : id === "manual" ? <ManualAdd /> : <Add />
          ) : section === "jobs" ? (
            <Jobs />
          ) : section === "review" ? (
            <ReviewQueue />
          ) : section === "settings" ? (
            <SettingsPage />
          ) : section === "library" ? (
            <Library />
          ) : (
            <div className="state">
              <h1>Page not found</h1>
              <a href="#/">Back to Explore</a>
            </div>
          )}
        </main>
        <footer>
          <span>endless tuna</span>
          <span>Research, with a clearer view.</span>
          <span>Local collection · v0.1</span>
        </footer>
      </>
    </AppContext.Provider>
  );
}
export default App;
