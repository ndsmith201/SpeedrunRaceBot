# Developer onboarding

Welcome to the Speedrun Race Bot. This guide gets a new contributor from a fresh checkout to a
working development bot, then explains where code belongs and how to verify changes safely.

## What the bot does

The bot coordinates Symphony of the Night races in Discord. It creates race lobbies, manages
readiness and countdowns, generates or claims randomizer seeds, records results, calculates Elo,
stores replays, and synchronizes race state with the SotN race API.

Active race state and RaceID lookup are held in memory. Compact race history, racer membership,
user profiles, and Elo ratings are stored in SQLite. Restarting the bot clears active workflows.

## Prerequisites

Install or obtain:

- Python 3.11 or newer.
- [Poetry](https://python-poetry.org/docs/) for the Python environment.
- Node.js 18 or newer and npm 9 or newer for shared developer commands and Git hooks.
- A Discord application and bot token.
- Access credentials for the SotN race API.
- A local SotN Randomizer checkout with its Node dependencies installed.
- Node.js, used by the bundled seed-generation callback.
- FFmpeg on `PATH`, required for voice playback.

Invite the Discord bot with the `bot` and `applications.commands` scopes. In its race channels it
needs View Channel, Send Messages, Embed Links, Attach Files, and Read Message History. In the
selected voice channel it needs View Channel, Connect, and Speak.

## First-time setup

Run all commands from the repository root. Several paths intentionally resolve from the current
working directory.

1. Install dependencies:

   ```powershell
   poetry install
   npm install
   ```

2. Create your local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Fill in `.env`. Never commit this file.

   | Variable                 | Purpose                                                            |
   | ------------------------ | ------------------------------------------------------------------ |
   | `DISCORD_TOKEN`          | Secret Discord bot token.                                          |
   | `RACE_GAME`              | Game name displayed by the tracker.                                |
   | `SEED_GENERATOR_COMMAND` | Seed callback launched from the repository root.                   |
   | `DISCORD_GUILD_ID`       | Optional development server for immediate command synchronization. |
   | `RANDO_PATH`             | SotN Randomizer directory containing `randomize`.                  |
   | `PATCH_FOLDER`           | Persistent location for generated PPF files.                       |
   | `REPLAYS_FOLDER`         | Root directory for per-race replay folders.                        |
   | `API_BASE_URL`           | Base URL of the SotN race API.                                     |
   | `API_KEY`                | Secret authorization value for private API endpoints.              |

4. Start the bot:

   ```powershell
   npm run start
   ```

Set `DISCORD_GUILD_ID` while developing. Guild command updates appear immediately; global Discord
command updates can take significantly longer.

## Verify the checkout

Before making changes, run the same checks expected after a change:

```powershell
poetry run pytest -q
poetry run ruff check src tools tests
poetry run python -m compileall -q src tools tests
```

Format changed Python files with:

```powershell
npm run prettier
```

The npm command formats Markdown, YAML, and JSON with Prettier, then formats Python with Ruff.

## Developer npm commands

| Command                  | Purpose                                                               |
| ------------------------ | --------------------------------------------------------------------- |
| `npm run start`          | Start the Discord bot through Poetry.                                 |
| `npm run prettier`       | Format supported repository files with Prettier and Python with Ruff. |
| `npm run prettier:check` | Check formatting without modifying files.                             |
| `npm run lint`           | Run Ruff and all formatting checks.                                   |
| `npm test`               | Run pytest.                                                           |
| `npm run check`          | Run lint, formatting checks, and tests.                               |
| `npm run commit`         | Create a Conventional Commit through Commitizen prompts.              |

`npm install` activates the Husky hooks:

- `pre-commit` runs lint and formatting checks.
- `commit-msg` enforces the Conventional Commits format used for semantic versioning.
- `pre-push` runs the complete test suite.

Use `npm run commit` instead of `git commit` when possible. Feature commits use `feat:`, fixes use
`fix:`, and breaking changes use `!` or a `BREAKING CHANGE:` footer. These categories provide the
major, minor, and patch signals needed by semantic-versioning release tools.

## Continuous integration

GitHub Actions runs the same `npm run check` command for pull requests, pushes to `master`, and
manual workflow runs. The test matrix covers Python 3.11 (the minimum supported version) and Python
3.14, with Node.js 18 supplying the npm developer tools. Dependencies are installed from
`poetry.lock` and `package-lock.json` before lint, formatting, and tests run.

The workflow lives in `.github/workflows/ci.yml`. Husky is disabled in CI because the workflow
invokes the checks directly; local hooks remain the fast feedback path before code reaches GitHub.

## Repository map

### Application package

| Path                                  | Responsibility                                                                                                        |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `src/speedrun_race_bot/bot.py`        | Process startup, initial seed-bank task, extension loading, and Discord command synchronization.                      |
| `src/speedrun_race_bot/settings.py`   | `.env` loading and application setting validation.                                                                    |
| `src/speedrun_race_bot/domain/`       | Discord-independent `Race`, `RaceStatus`, and `Player` entities.                                                      |
| `src/speedrun_race_bot/race/`         | Race workflows: lifecycle coordination, countdowns, results, Elo, replay storage, seed delivery, and in-memory state. |
| `src/speedrun_race_bot/persistence/`  | SQLite-backed repositories.                                                                                           |
| `src/speedrun_race_bot/integrations/` | SotN API client, external seed command runner, and Discord voice announcements.                                       |
| `src/speedrun_race_bot/discord_ui/`   | Slash commands, persistent buttons, tracker rendering, error handling, and dependency composition.                    |
| `src/speedrun_race_bot/templates/`    | Markdown fragments used to render the race tracker embed.                                                             |

### Supporting files

| Path                          | Responsibility                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------ |
| `config/race_options.yaml`    | Selectable `/race create` options.                                             |
| `database/schema.sql`         | SQLite schema and connection pragmas.                                          |
| `tools/generate_race_seed.py` | Stable executable entry point configured in `.env`.                            |
| `tools/seed_generator/`       | Seed callback config, naming, process execution, and SotN artifact generation. |
| `tests/`                      | Fast unit and structural tests.                                                |
| `audio/`                      | Join, error, and random countdown audio.                                       |

Runtime files under `patches/`, `replays/`, `seedbank/`, `seeds/`, and `database/` are ignored by
Git. Their `.gitkeep` files preserve the empty directories in a fresh checkout.

## How the application is assembled

`bot.py` loads `speedrun_race_bot.discord_ui.extension`. The extension is the composition root: it
constructs a shared race-state service, race and user repositories, API client, and coordinator,
then registers the command cogs and persistent views.

Keep dependency construction in `discord_ui/extension.py`. Feature modules should receive their
dependencies through constructors rather than creating additional repositories or API clients.

At startup the bot also schedules a background seed-bank check. Startup does not wait for seed
generation to finish.

## Race lifecycle

The main flow is:

1. `/race create` validates Discord channels and the selected randomizer preset.
2. The host is stored locally and checked through the API, and the bot joins the selected voice
   channel.
3. `RaceCoordinator` creates the live race, stores its compact history record, and publishes the
   tracker.
4. `SeedDelivery` generates a seed in the background or claims one from the seed bank.
5. Players join, toggle readiness, and start the countdown.
6. `RaceCountdown` starts the API race and the local timer on Go.
7. `RaceResults` records finishes or forfeits and synchronizes each result.
8. When every player has a result, `EloService` updates SQLite and the API race is finalized.

The `beyond-confirmed-sum26te` preset uses pre-generated files from `seedbank/`. Claiming one queues
a background refill. The `Custom` preset skips automatic seed generation.

## Where to make a change

| Change                                           | Start here                                                   |
| ------------------------------------------------ | ------------------------------------------------------------ |
| Add or change a slash command                    | `discord_ui/commands/`                                       |
| Change lobby or running buttons                  | `discord_ui/controls.py`                                     |
| Change tracker layout or copy                    | `templates/race_tracker.md` and `discord_ui/race_tracker.py` |
| Change race transitions or validation            | `race/state.py`                                              |
| Change create/join/close orchestration           | `race/coordinator.py`                                        |
| Change countdown behavior                        | `race/countdown.py`                                          |
| Change finish, forfeit, or API result behavior   | `race/results.py`                                            |
| Change Elo math or correction behavior           | `race/elo.py`                                                |
| Change replay validation or storage              | `race/replay_storage.py`                                     |
| Change seed-bank claims or Discord seed delivery | `race/seed_delivery.py`                                      |
| Change seed subprocess environment handling      | `integrations/seed_generator.py`                             |
| Change the SotN randomizer command itself        | `tools/seed_generator/sotn.py`                               |
| Change environment settings                      | `settings.py` and `.env.example`                             |
| Change API endpoints                             | `integrations/rando_api.py`                                  |
| Change stored user fields                        | `database/schema.sql` and `persistence/user_repository.py`   |
| Change stored race or player-link fields         | `database/schema.sql` and `persistence/race_repository.py`   |

## Adding a slash command

Put the command in the cog matching its audience:

- `race.py` for race and host actions.
- `player_profile.py` for racer profile metadata.
- `replays.py` for replay transfer.
- `admin.py` for administrator-only maintenance.

If a new category does not fit, create a focused cog and register it in
`discord_ui/extension.py`. Keep command methods thin: validate Discord input, defer when work can
take more than a moment, call a workflow, and send the result.

`/race create` is generated dynamically from `config/race_options.yaml`. Discord supports at most
25 choices per option, and this project reserves enough command parameters to allow at most 22
configured option groups. Restart the bot after editing the YAML.

## Seed-generation boundary

The bot launches `SEED_GENERATOR_COMMAND` as a subprocess and passes race details through `RACE_*`
environment variables. The callback must create or update exactly one file beneath
`RACE_SEEDS_DIRECTORY`; otherwise the bot treats the generation as failed.

The stable callback is `tools/generate_race_seed.py`. Keep this wrapper small because `.env` files
refer to it directly. Put callback implementation changes inside `tools/seed_generator/`.

Subprocess stdout and stderr are echoed live and retained for error reporting. Do not replace this
with buffered-only logging; seeing the randomizer output is important for diagnosing failures.

## State and persistence rules

- `RaceState` owns live lifecycle rules, active channel lookup, and in-process RaceID history.
- `RaceRepository` stores only the race interaction ID, start and end timestamps, and JSON result.
- `race_players` links races to `user_data` through a many-to-many relationship.
- Closing a race removes it from active channel lookup while leaving the compact database record.
- `RaceRepository` and `UserRepository` own SQLite access and always close their connections.
- `EloService.adjust` reverses the race's stored deltas before applying a corrected order.
- A corrected Elo order must contain every original racer exactly once.
- Replay folders use the race interaction ID as their directory name.

When changing a workflow that touches both local state and the API, preserve the existing retry
behavior. Local results may already be recorded when an API call fails, so repeated button presses
must synchronize missing work without recording a second finish or applying Elo twice.

## Async and Discord conventions

- Defer interactions before seed generation, archive creation, or network work that could exceed
  Discord's initial response window.
- Do not run blocking HTTP, filesystem-heavy, or subprocess work directly on the event loop.
- Use `asyncio.to_thread` for blocking libraries and the asyncio subprocess APIs for commands.
- Update the shared race tracker after a visible state change.
- Persistent button `custom_id` values are compatibility identifiers; changing them invalidates
  buttons on previously posted messages.
- Catch integration-specific failures at the workflow boundary and return a useful ephemeral
  message instead of discarding locally recorded state.

## Common troubleshooting

### Slash commands are missing

Set `DISCORD_GUILD_ID` to the numeric ID of the development server, restart the bot, and confirm it
was invited with the `applications.commands` scope. Global synchronization is slower.

### `Unknown interaction` from Discord

The command did not acknowledge the interaction quickly enough. Defer the response before slow API,
filesystem, archive, or subprocess work, then respond with `interaction.followup`.

### Seed command exits with code 1

Read the live child-process output immediately above the exception. Verify `RANDO_PATH`, Node.js,
the randomizer's installed dependencies, and that the selected preset exists in that checkout.

### No seed file is detected

The callback must change exactly one file under `RACE_SEEDS_DIRECTORY`. Writing only to
`PATCH_FOLDER`, changing multiple files, or leaving an unchanged output filename will fail the
artifact check.

### Voice playback fails

Confirm FFmpeg is installed, the bot has Connect and Speak permissions, and the chosen audio file is
one of the supported formats in `audio/countdown/`.

### SQLite reports a locked database

Stop duplicate bot processes and inspect whether another tool has `database/bot.sqlite3` open for
writing. Repository code should use the repository `connect()` context managers so transactions
close reliably.

## Before opening a pull request

- Keep modules focused on one responsibility and use descriptive filenames.
- Update `.env.example` when adding or renaming an environment variable.
- Update `README.md` and this guide when behavior or architecture changes.
- Add or update tests for state transitions, Elo math, parsing, or configuration changes.
- Run formatting, Ruff, pytest, and compilation checks.
- Confirm `.env`, generated seeds, patches, replays, database files, and API keys are not included.

## First contribution checklist

- [ ] The bot starts in a development guild.
- [ ] `/race create` appears with the configured options.
- [ ] You can create, join, ready, and close a test lobby.
- [ ] The test suite and Ruff checks pass locally.
- [ ] You know which workflow owns the feature you plan to change.
