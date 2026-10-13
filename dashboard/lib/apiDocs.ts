// apiDocs.ts - the data behind /docs/api. Mirrors api/routes/*.py and api/models.py; when an endpoint
// changes there, change it here. Example values are illustrative (the shapes are exact).

export interface Param {
  name: string;
  in: "path" | "query" | "body";
  type: string;
  required?: boolean;
  default?: string;
  desc: string;
}

export interface Endpoint {
  id: string;
  method: "GET" | "POST";
  path: string;
  summary: string;
  notes?: string[];
  params?: Param[];
  /** What follows {base} in the curl example. */
  call: string;
  /** Replaces the whole curl command (POST examples). */
  curl?: string;
  response: string;
}

export interface Group {
  id: string;
  title: string;
  blurb: string;
  endpoints: Endpoint[];
}

const DAYS = (def: string, max: string): Param => ({ name: "days", in: "query", type: "integer", default: def, desc: `Number of UTC days, 1 to ${max}.` });
const LIMIT = (def: string, desc: string): Param => ({ name: "limit", in: "query", type: "integer", default: def, desc });
const PROJECT_ID: Param = { name: "project_id", in: "path", type: "string", required: true, desc: "Project slug, e.g. the id field of /projects." };

const PROJECT_EXAMPLE = `{
  "id": "example-project",
  "name": "Example Project",
  "category": "token",
  "segment": "token",
  "tier": "discovered",
  "score": null,
  "tvl_usd": null,
  "usdc_gas_7d": 412.307,
  "unique_users_7d": 1893,
  "tx_count_7d": 51210,
  "failed_tx_7d": 604,
  "failed_rate_7d": 0.0118,
  "computed_at": "2026-10-12T04:00:12+00:00",
  "market": {
    "price_usd": 0.0412,
    "fdv_usd": null,
    "market_cap_usd": null,
    "liquidity_usd": 6200,
    "volume_24h_usd": 18400,
    "price_change_24h_pct": 4.7,
    "volume_7d_usd": 90100,
    "quality": "thin",
    "listed_on_coingecko": false,
    "source": "geckoterminal",
    "fetched_at": "2026-10-12T11:02:44+00:00"
  },
  "holders": 5120,
  "socials": [{ "kind": "website", "url": "https://example.org", "curated": false }]
}`;

export const GROUPS: Group[] = [
  {
    id: "status",
    title: "Status",
    blurb: "Check freshness before trusting anything marked latest.",
    endpoints: [
      {
        id: "health",
        method: "GET",
        path: "/health",
        summary: "Liveness probe. Never rate limited, safe for uptime monitors. HEAD is accepted too.",
        call: "/health",
        response: `{ "status": "ok" }`,
      },
      {
        id: "status",
        method: "GET",
        path: "/metrics/status",
        summary: "How fresh the data is: the last block ingestion applied and how far behind now that is.",
        notes: [
          "status is live when the lag is under 10 minutes, behind when ingestion is catching up or stalled, unknown before the first batch.",
          "Days after data_through are incomplete in every daily series.",
        ],
        call: "/metrics/status",
        response: `{
  "status": "live",
  "last_block_number": 25537874,
  "data_through": "2026-10-12T06:16:36+00:00",
  "lag_seconds": 7,
  "checkpoint_updated_at": "2026-10-12T06:16:37.946836+00:00"
}`,
      },
    ],
  },
  {
    id: "network",
    title: "Network",
    blurb: "Chain-wide activity, one row per UTC day.",
    endpoints: [
      {
        id: "stats",
        method: "GET",
        path: "/stats",
        summary: "Headline totals across tracked projects, for a stat strip.",
        call: "/stats",
        response: `{
  "total_projects": 876,
  "total_scored": 29,
  "total_tvl_usd": 1520000.5,
  "avg_score": 0.41,
  "total_volume_7d": 18200.4,
  "total_tx_7d": 9120000,
  "total_unique_users_7d": 154000,
  "computed_at": "2026-10-12T04:00:12+00:00"
}`,
      },
      {
        id: "network-daily",
        method: "GET",
        path: "/metrics/network/daily",
        summary: "Chain-wide daily totals: transactions, failures, USDC gas, deployments, blocks, transfers, active senders.",
        notes: [
          "Oldest first. A day the pipeline did not cover is absent, never zero-filled.",
          "partial is true for days still accruing. source is raw_backfill for early days that predate failure, deployment and block tracking (those fields are null).",
          "failed_rate and avg_gas_per_tx_usdc are derived: failed / transactions and gas / transactions.",
        ],
        params: [DAYS("30", "90")],
        call: "/metrics/network/daily?days=7",
        response: `[
  {
    "day": "2026-10-11",
    "tx_count": 1028753,
    "failed_tx_count": 3086,
    "failed_rate": 0.003,
    "usdc_gas_paid": 4210.55,
    "avg_gas_per_tx_usdc": 0.0041,
    "contract_creations": 412,
    "blocks": 170112,
    "token_transfer_count": 2201455,
    "active_addresses": 98211,
    "source": "rollup",
    "partial": false
  }
]`,
      },
      {
        id: "tokens-daily",
        method: "GET",
        path: "/metrics/tokens/daily",
        summary: "Daily transfer count and volume for the tracked tokens (USDC, EURC, USYC), each in its own 6-decimal units.",
        notes: [
          "USDC volume is gross movement taken once from Arc's native system log: every transfer counts, including hops through routers, and mint and burn are excluded. It is not economic volume.",
          "Volumes of different tokens are never added together.",
        ],
        params: [
          DAYS("30", "90"),
          { name: "token", in: "query", type: "string", desc: "USDC, EURC, USYC or a tracked token address. Omit for all three." },
        ],
        call: "/metrics/tokens/daily?days=7&token=USDC",
        response: `[
  {
    "day": "2026-10-11",
    "token_address": "0x3600000000000000000000000000000000000000",
    "symbol": "USDC",
    "transfer_count": 2201455,
    "volume": 205800000.12,
    "avg_transfer_size": 93.48
  }
]`,
      },
      {
        id: "contracts-top",
        method: "GET",
        path: "/metrics/contracts/top",
        summary: "Top contracts by USDC gas over a window, with each one's share of all network gas and its project when tracked.",
        params: [DAYS("7", "30"), LIMIT("20", "How many contracts, 1 to 100.")],
        call: "/metrics/contracts/top?days=7&limit=5",
        response: `[
  {
    "contract_address": "0x0000000000000000000000000000000000000001",
    "project_id": "example-project",
    "project_name": "Example Project",
    "category": "dex",
    "tx_count": 900000,
    "failed_tx_count": 9000,
    "failed_rate": 0.01,
    "usdc_gas": 1500.0,
    "gas_share": 0.12
  }
]`,
      },
    ],
  },
  {
    id: "projects",
    title: "Projects",
    blurb: "Everything Isogram tracks, with the metrics that apply to each type.",
    endpoints: [
      {
        id: "projects",
        method: "GET",
        path: "/projects",
        summary: "Every tracked project with its latest figures. Market data, holders and links are included where known.",
        notes: [
          "segment decides which fields mean something: score and tvl_usd exist for defi only and are null elsewhere (null means not applicable, never 0).",
          "tier is curated for hand-checked projects and discovered for automatically promoted ones. Discovered is not an endorsement.",
          "market is third-party (GeckoTerminal) and null when there is no fresh price. FDV and market cap are withheld unless quality is ok.",
          "The response is not paginated (a few hundred rows).",
        ],
        call: "/projects",
        response: `[
${PROJECT_EXAMPLE.split("\n").map((l) => "  " + l).join("\n")}
]`,
      },
      {
        id: "project",
        method: "GET",
        path: "/projects/{project_id}",
        summary: "One project, with its contract addresses.",
        params: [PROJECT_ID],
        call: "/projects/example-project",
        response: PROJECT_EXAMPLE.replace(/\n}$/, `,\n  "contracts": ["0x0000000000000000000000000000000000000001"],\n  "created_at": "2026-10-04T09:12:00+00:00"\n}`),
      },
      {
        id: "by-address",
        method: "GET",
        path: "/projects/by-address/{address}",
        summary: "Which tracked project owns a contract address. 404 when none does, 400 when the address is malformed.",
        params: [{ name: "address", in: "path", type: "string", required: true, desc: "A 0x-prefixed, 40-hex-character address (any case)." }],
        call: "/projects/by-address/0x3600000000000000000000000000000000000000",
        response: `{ "id": "usdc", "name": "USDC" }`,
      },
      {
        id: "project-daily",
        method: "GET",
        path: "/projects/{project_id}/daily",
        summary: "One project's daily transactions, failures, USDC gas and unique senders.",
        notes: ["unique_users is null for days before the contract was tracked, not 0."],
        params: [PROJECT_ID, DAYS("30", "90")],
        call: "/projects/example-project/daily?days=14",
        response: `[
  {
    "day": "2026-10-11",
    "tx_count": 7210,
    "failed_tx_count": 84,
    "failed_rate": 0.0117,
    "usdc_gas": 58.2,
    "unique_users": 312
  }
]`,
      },
    ],
  },
  {
    id: "rankings",
    title: "Rankings",
    blurb: "Pre-sorted views of the same project objects returned by /projects.",
    endpoints: [
      {
        id: "scores-top",
        method: "GET",
        path: "/scores/top",
        summary: "Projects by Arc Native Score, highest first. Only DeFi protocols are scored.",
        params: [LIMIT("10", "How many projects.")],
        call: "/scores/top?limit=5",
        response: "[ { …project object… } ]",
      },
      {
        id: "scores-project",
        method: "GET",
        path: "/scores/{project_id}",
        summary: "One project's current score and its inputs.",
        params: [PROJECT_ID],
        call: "/scores/example-project",
        response: "{ …project object… }",
      },
      {
        id: "scores-history",
        method: "GET",
        path: "/scores/{project_id}/history",
        summary: "A project's score over time, one point per scoring run (every four hours), newest first.",
        params: [PROJECT_ID, LIMIT("100", "How many points, 1 to 500.")],
        call: "/scores/example-project/history?limit=30",
        response: `[
  {
    "computed_at": "2026-10-12T04:00:12+00:00",
    "score": 0.62,
    "tvl_usd": 1200000.0,
    "usdc_gas_7d": 833.1,
    "unique_users_7d": 2401
  }
]`,
      },
      {
        id: "tvl",
        method: "GET",
        path: "/tvl/top",
        summary: "DeFi protocols by TVL, highest first. /tvl/{project_id} returns one project.",
        params: [LIMIT("10", "How many projects.")],
        call: "/tvl/top?limit=5",
        response: "[ { …project object… } ]",
      },
      {
        id: "gas",
        method: "GET",
        path: "/gas/top",
        summary: "Projects by trailing 7-day USDC gas, highest first. /gas/{project_id} returns one project.",
        params: [LIMIT("10", "How many projects.")],
        call: "/gas/top?limit=5",
        response: "[ { …project object… } ]",
      },
    ],
  },
  {
    id: "venues",
    title: "DEX volume",
    blurb: "Per-venue 24 hour volume (GeckoTerminal, third-party, refreshed hourly).",
    endpoints: [
      {
        id: "venues",
        method: "GET",
        path: "/venues",
        summary: "DEXes and launch platforms with 24h volume, biggest first.",
        notes: [
          "Anomalous pools (fewer than 10 traders in 24h, or volume above 25x reserves) are left out. The amount left out is reported in excluded_volume_usd, never hidden.",
          "truncated means the venue has more pools than the scan covers, so volume is a lower bound.",
          "share is relative to all venues, even when filtered by kind. 503 when the data is temporarily unavailable (never an empty list that would look like no trading).",
        ],
        params: [{ name: "kind", in: "query", type: "string", desc: "dex or launchpad. Omit for both." }],
        call: "/venues?kind=dex",
        response: `[
  {
    "dex_id": "example-dex",
    "name": "Example DEX",
    "kind": "dex",
    "volume_24h_usd": 250000.0,
    "share": 0.1,
    "active_pools": 270,
    "sample_pools": 300,
    "excluded_volume_usd": 0.0,
    "excluded_pools": 0,
    "truncated": false,
    "top_pool_name": "WETH / USDC",
    "top_pool_volume_usd": 90000.0,
    "source": "geckoterminal",
    "fetched_at": "2026-10-12T11:02:44+00:00"
  }
]`,
      },
    ],
  },
  {
    id: "write",
    title: "Writes",
    blurb: "The only two public routes that create anything. Both are rate limited.",
    endpoints: [
      {
        id: "keys",
        method: "POST",
        path: "/keys",
        summary: "Create a free API key. The key is returned once and cannot be recovered; only its hash is stored.",
        notes: ["Limited to 5 new keys per address per day, and 3 active keys per email (409 beyond that). Use the form above, or call it directly."],
        params: [
          { name: "name", in: "body", type: "string", required: true, desc: "What you are building, 2 to 60 characters." },
          { name: "email", in: "body", type: "string", required: true, desc: "Contact address, up to 254 characters. Used only to reach you about API changes, limits and abuse. Not verified, never shown publicly, never returned by the API." },
        ],
        call: "/keys",
        curl: `curl -X POST "{base}/keys" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Acme portfolio tracker", "email": "dev@acme.io"}'`,
        response: `{
  "api_key": "isg_Zk3…",
  "id": 12,
  "name": "Acme portfolio tracker",
  "tier": "registered",
  "rate_limit_per_minute": 600,
  "created_at": "2026-10-13T09:00:00+00:00",
  "note": "Store this key now. It is shown once and cannot be recovered. Send it as the X-API-Key header."
}`,
      },
      {
        id: "submit",
        method: "POST",
        path: "/submit",
        summary: "Propose a contract for listing. It goes to a human review queue and is never listed automatically.",
        notes: ["Limited to 5 submissions per address per hour."],
        params: [
          { name: "contract_address", in: "body", type: "string", required: true, desc: "0x address of the contract." },
          { name: "proposed_name", in: "body", type: "string", desc: "Up to 500 characters." },
          { name: "proposed_category", in: "body", type: "string", desc: "Up to 500 characters." },
          { name: "socials", in: "body", type: "object", desc: "Links, for the reviewer." },
          { name: "submitter_contact", in: "body", type: "string", desc: "How to reach you." },
          { name: "note", in: "body", type: "string", desc: "Anything the reviewer should know." },
        ],
        call: "/submit",
        curl: `curl -X POST "{base}/submit" \\
  -H "Content-Type: application/json" \\
  -d '{"contract_address": "0x0000000000000000000000000000000000000001", "proposed_name": "Example"}'`,
        response: `{ "id": 41, "contract_address": "0x0000000000000000000000000000000000000001", "status": "pending", "created_at": "2026-10-13T09:00:00+00:00" }`,
      },
    ],
  },
  {
    id: "badge",
    title: "Badge",
    blurb: "An embeddable SVG. See the badges guide for copy-paste snippets.",
    endpoints: [
      {
        id: "badge",
        method: "GET",
        path: "/badge/{project_id}.svg",
        summary: "An SVG badge with the project's Arc Native Score. DeFi protocols show a score or insufficient data; every other type says not scored.",
        notes: ["Cached for one hour (Cache-Control: max-age=3600). Has its own, larger rate limit so README images are not throttled."],
        params: [PROJECT_ID],
        call: "/badge/example-project.svg",
        response: "<svg …>  (image/svg+xml)",
      },
    ],
  },
];

export const RATE_LIMITS = [
  { tier: "Anonymous", id: "anonymous", limit: "60 / minute", scope: "per IP address", how: "No key needed." },
  { tier: "Registered", id: "registered", limit: "600 / minute", scope: "per key", how: "Free. Send X-API-Key." },
  { tier: "Badge images", id: "badge", limit: "300 / minute", scope: "per IP address", how: "Automatic for GET /badge/*. READMEs load in bursts." },
];
