# laravel_map.py

One Python script that reads a Laravel codebase and its Docker dev environment, then writes a set of linked HTML pages that explain and map the application. It needs no `pip install`, doesn't boot the app, and works on Laravel 8 through 12, including Sail, plain docker compose, Livewire / Volt, Filament and Inertia.

```bash
# inside a Laravel repo: writes ./laravel-map/ (git-ignored automatically)
python3 laravel_map.py

# point it at a project: writes ./shop-app-map/ in the directory you run it from
python3 laravel_map.py ~/code/shop-app

# then open the index page
open laravel-map/index.html        # macOS  (xdg-open on Linux)
```

## Where the output goes

| You run | Output |
|---|---|
| `python3 laravel_map.py` inside the repo | `<repo>/laravel-map/` |
| `python3 laravel_map.py /path/to/shop-app` | `./shop-app-map/` in your current directory, named after the app folder. A generic folder name such as `html`, `app` or `src` falls back to the composer package name. |
| `... -o some/dir` | wherever you say |

The output folder always gets its own `.gitignore` containing `*`, so git ignores it without any change to your tracked files. Re-running writes to the same folder and compares against the previous run.

## What you get

| Page | What it answers |
|---|---|
| **Overview** | What is this app? Stack, a plain-English summary, an architecture sketch, and where to start reading. |
| **Getting started** | How do I run it? Ordered setup commands for *this* project (Sail, docker compose or local), URLs and ports to open, everyday commands, composer/npm/Makefile scripts, CI checks, test setup, the rendered README, and who knows which area of the code. It also shows **your machine's state**: missing `.env` keys, `APP_KEY`, `vendor/` and `node_modules/` out of sync with the lock files, which containers are running, and how far behind upstream you are. |
| **What changed** | What's different since I last looked? Commits, authors, PRs and files by area, plus a structural diff of routes, models, tables and columns, migrations, classes, env keys, composer/npm packages, Docker services and Dockerfiles, schedule and listeners. Ends with a **catch-up checklist**: pull, rebuild containers, `composer install`, `npm install`, new `.env` keys, `migrate`, `optimize:clear`, restart queue workers. |
| **Routes** | Every route with handler, middleware, name and the file and line it's defined on. Also a URL tree, routes per controller, middleware usage and broadcast channels. Package routes (Horizon, Sanctum, Livewire…) and Filament panel routes are included. |
| **HTTP layer** | Request-lifecycle diagram, global and group middleware and aliases, and, per controller action, what it validates, which models and services it touches, what it dispatches and what it returns. Form requests, API resources and policies too. |
| **Models** | Relationship map, and per model: table, fillable/guarded/hidden, casts, scopes, accessors, observers, policy, factory, model events and who references it. |
| **Database** | The schema rebuilt by replaying migrations (create/alter/rename/drop, foreign keys, morphs, schema dumps). Includes an ER diagram, columns per table with a mini-diagram of each table's neighbours, and the migration history. |
| **Events & jobs** | Who dispatches what: events → listeners (and how each is registered), jobs, mail, notifications, observers, scheduled tasks with human-readable frequencies, and artisan commands. |
| **Frontend** | Blade views and components (extends/include/x-components), Inertia pages and who renders them, the Vite/Mix setup, and an interactive view graph. |
| **Livewire** | Shown when Livewire is used. Class and Volt components (both styles) with state, actions, `#[On]` listeners, dispatched events, routes and where each is embedded, plus an event-flow diagram. |
| **Filament** | Shown when Filament is used. Panels (path, auth features, discovery, plugins), resources with model, form fields, table columns, filters, relation managers and the **URLs they create**, plus custom pages and widgets. |
| **Classes** | Every class classified by role (model, controller, job, Livewire, Filament, action, service…), with an interactive dependency graph and the most depended-upon classes. |
| **Docker** | Services and what each one is for, how they connect (env vars like `DB_HOST=mysql`, nginx `fastcgi_pass`, `depends_on`), ports as clickable URLs, volumes, Dockerfiles (PHP version, extensions, Xdebug), supervisor programs, `php.ini` settings. |
| **Config & packages** | Every env var mapped to the config keys it feeds (and its default), what's missing from `.env.example` or your `.env`, config files, and every composer/npm package with a one-line explanation. |
| **Insights** | Leads worth checking: routes pointing at missing code, Inertia pages or views that don't exist, relationships with no FK column, `env()` outside `config/`, raw SQL built from variables, `{!! !!}`, unguarded models, events without listeners, unused controllers and components, large classes and methods, `latest` image tags, change hotspots, ownership, and TODO/FIXME comments. |
| `data.json` | Everything above as JSON, for your own scripts or to paste into an LLM. |

## The three situations it is built for

**New to the codebase.** Run it, read *Overview*, then follow *Getting started* top to bottom. The "Where to start reading" list and the dependency graph show which files matter.

**Someone else changed things / reviewing a branch.**

```bash
python3 laravel_map.py --since main      # on a feature branch: compares with the point it forked from main
python3 laravel_map.py --since v2.4.0    # or a tag / sha
```

**Back from leave.**

```bash
git fetch
python3 laravel_map.py --since 2026-09-01     # or: --since "6 weeks ago"
```

Then work through the catch-up checklist on *What changed*. Without `--since`, each run compares with the previous run of the same output folder, or with the last 30 days of git history on the first run. The comparison includes uncommitted work.

## Options

```text
--since REF_OR_DATE   baseline for "What changed": branch, tag, sha, or a date
--artisan [auto|CMD]  add live data from artisan: exact route:list (incl. package routes),
                      `about`, and pending migrations. "auto" finds a running Sail/compose app
                      container or a local PHP install. Or pass a prefix, e.g.
                      --artisan "docker compose exec -T app php artisan"
--db                  with --artisan: real column types from your database (artisan model:show)
--editor NAME         file references open in your editor: auto (default: detects .idea / VS Code),
                      vscode, cursor, phpstorm, idea, sublime, zed, none, or a URL template
                      containing {path} and {line}
--offline             copy Mermaid and d3 next to the pages so diagrams work with no internet
                      (downloaded once into ~/.cache/laravel_map)
--no-snapshot         don't record this run as the next run's baseline
--open                open index.html when done
-o, --out DIR         output directory
```

## Requirements

- Python 3.8+ on the machine where the code is. Nothing else. PyYAML is used for compose files if it happens to be installed; there is a built-in reader otherwise.
- `git` for history, change tracking and ownership (optional).
- `docker` for container status and `--artisan auto` (optional).
- A browser. Diagrams and graphs load Mermaid and d3 from a CDN, or from local copies with `--offline`. Tables and text work without either.

If Python isn't on your host, run it from a container:

```bash
docker run --rm -v "$PWD":/app -w /app python:3.12-slim python laravel_map.py --editor none
```

## How it works, and its limits

It reads source code. It tokenises PHP and follows the same paths Laravel does: `bootstrap/app.php` → `withRouting()` or `RouteServiceProvider` → route files → groups, prefixes, names and middleware → `Route::resource()` expansion → `require`d files. Classes are classified by parent class, interfaces, traits and namespace. Migrations are replayed in order to rebuild the schema.

Things only the running app knows, such as routes registered dynamically by packages, macros, or columns added by raw SQL, can be missing or approximate. `--artisan auto` (and `--db`) close most of that gap when your containers are up. Treat *Insights* as leads to check, not verdicts.

## Privacy

- Values from your `.env` are never read into the output; only key names are compared.
- `.env.example` and compose values whose names look secret (`*PASSWORD*`, `*SECRET*`, `*KEY*`, `*TOKEN*`…) are masked.
- Git author names, not emails, appear on the ownership tables. Remote URLs are stripped of credentials.
- The pages are static files on your disk. They request Google Fonts and the Mermaid/d3 libraries from public CDNs unless you use `--offline`.
