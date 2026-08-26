# Speedrun Race Bot

A Discord bot for organizing casual speedrun races. Race state is stored in memory, so restarting the bot clears active races and their current results.

New contributors should start with the [developer onboarding guide](docs/onboarding.md).

## Setup

1. Install Python 3.11 or newer.
2. Install [Poetry](https://python-poetry.org/docs/) and dependencies:

   ```powershell
   poetry install
   npm install
   ```

3. Copy `.env.example` to `.env`, then set `DISCORD_TOKEN`, `RACE_GAME`,
   `API_BASE_URL`, and `API_KEY`.
4. Invite the bot with the `bot` and `applications.commands` scopes.
5. Run the bot:

   ```powershell
   npm run start
   ```

Set `DISCORD_GUILD_ID` during development for immediate slash-command updates in that server. Restart the bot after changing `config/race_options.yaml` so Discord can register the updated `/race create` fields.

## Race flow

1. Create a lobby with `/race create`.
2. Players use **Join Race** to join or leave the lobby, then **Ready** to toggle their ready state.
3. Any joined participant can start once every racer is ready and the seed is available.
4. Starting plays a random audio cue, then shows a 0.8-second-per-step 🔴, 🔵, 🟡 countdown. The race begins on 🟢, then changes to 🏁.
5. During the race, players use **Finish** to record the timer automatically or **Forfeit** to record a loss.
6. The race completes only after every participant has finished or forfeited. A completed race can be replaced with a new lobby in the same channel.

Each racer starts at 1200 Elo. When a race completes, the bot applies a pairwise Elo update
with a K-factor of 50 and stores each player's updated rating in `user_data`. Finish order
determines wins and losses; forfeiting racers rank behind finishers and tie one another.
After the local update, each player's absolute rating is sent to the private Elo API for the
race's selected randomizer preset.

Creating a Discord race also creates the API's current race with the selected randomizer
preset and adds the race creator as its first racer.
At the end of the countdown, the API race is started immediately before the local timer.
Finishes are sent to the API in milliseconds. Forfeits are sent with a null finish time and
the forfeited flag set to true.
After every result and Elo update is synchronized, the bot finalizes the API's current race.
Pressing Finish or Forfeit again retries incomplete finalization after a temporary API failure.

When a racer joins, the bot looks up their Discord user ID in the SotN Rando API. If the
lookup returns 404, it registers them with their Discord username and user ID before adding
them to the API's current race and the local lobby.
Leaving the lobby removes the racer from the API before removing them locally.

Finish times use `HH:MM:SS.mmm` and the tracker sorts completed racers by time. Forfeits are shown with 🪦 and placed after racers who are still running.

## Commands and controls

- `/race create channel:<#race-channel> voice_channel:<voice> annotation:<text> ...` — creates a lobby. `annotation:` is optional.
- `/race close` — closes the current channel's race; restricted to the race host or administrators.
- `/flag emoji:<🇺🇸>` — saves a Unicode country flag for your racer name.
- `/stream link:<Twitch URL>` — saves a Twitch channel link for your racer name.
- `/replay replay:<file>` — after a race finishes, participants can upload a `.sotnr` replay up to 100 KB; a clickable VHS replay link appears beside their result.
- `/replays raceid:<id>` — downloads a ZIP of the replay folder for a race in an ephemeral response.
- `/eloadjust raceid:<id> players:<mentions-or-ids>` — administrator-only; reverses a completed race's Elo changes and reapplies them using every racer in the supplied finish order. Races are available by ID for the lifetime of the current bot session.
- `/newseason` — administrator-only; backs up `user_data` to CSV and resets every Elo to 1200.
- `/playerkick player:<member>` — removes a racer; restricted to the race host or administrators.
- **Join Race** — joins the lobby; press again to leave.
- **Ready** — toggles ready/unready.
- **Start Race** — starts the countdown when all racers are ready.
- **Finish** — records the current race timer.
- **Forfeit** — records a forfeit and an automatic loss.

The tracker is an embed with a yellow lobby stripe, green running stripe, and grey completed stripe. It displays the race creation interaction ID for use with `/replays`. Racer information uses three inline fields: Racer, Result, and ELO. Each player's flag and stream link appear beside their name in the Racer field. Result shows the finish time or forfeit status, and ELO includes any non-zero rating change in brackets. The tracker's Markdown layout is defined in [race_tracker.md](src/speedrun_race_bot/templates/race_tracker.md).

## Race options

Edit [config/race_options.yaml](config/race_options.yaml) to add optional enum parameters to `/race create`:

```yaml
race_start_options:
  - name: Randomizer preset
    value: [safe, lycan, nimble]
  - name: Tournament Mode
    value: [true, false]
```

Each entry becomes an optional command parameter. For example, `Randomizer preset` becomes `randomizer_preset:`. Discord supports up to 22 configured parameters and 25 values for each parameter. The Randomizer preset, when selected, is shown beneath the race annotation.

## Seed generation

Set `SEED_GENERATOR_COMMAND` to run a seed generator when a lobby is created:

```env
SEED_GENERATOR_COMMAND=py tools/generate_race_seed.py
```

Generation runs in the background. The lobby appears immediately, shows the configured `alycardwalkcycle` custom emoji while generating, and cannot be started until the seed succeeds. The generated seed is uploaded as a follow-up message; its download link is shown at the bottom of the tracker.

The command runs from the project directory and must create or update exactly one file under `seeds/`. The bot passes these environment variables:

- `RACE_GAME`
- `RACE_CATEGORY` (currently empty because `/race create` has no category field)
- `RACE_GUILD_ID`
- `RACE_CHANNEL_ID`
- `RACE_INTERACTION_ID`
- `RACE_SEEDS_DIRECTORY`
- `RACE_START_OPTIONS` — JSON dictionary of the selected race options

For example, `RACE_START_OPTIONS` can be:

```json
{ "Randomizer preset": "safe", "Tournament Mode": "true" }
```

`tools/generate_race_seed.py` generates the SotN patch using the race options supplied by the bot.

On startup, the bot populates `seedbank/` in the background without delaying bot readiness. Missing
files are generated until at least three exist, using the `beyond-confirmed-sum26te` preset with
Music Rando and Tournament Mode enabled. Seed-bank generation does not create replay metadata.
Creating a race with that preset claims a random banked seed instead of generating one directly,
then queues a background refill back to three files.

## Voice and audio

The bot needs **View Channel**, **Connect**, and **Speak** in the selected voice channel. Install [FFmpeg](https://ffmpeg.org/download.html) and ensure `ffmpeg` is available on `PATH`.

- [audio/player_joined.mp3](audio/player_joined.mp3) plays when a racer joins.
- [audio/ready_error.mp3](audio/ready_error.mp3) plays for readiness failures and unexpected slash-command errors during an active race.
- Put `.mp3`, `.ogg`, `.wav`, or `.m4a` start cues in [audio/countdown](audio/countdown). One file is chosen randomly when **Start Race** is pressed.

The bot disconnects from the voice channel after the countdown ends.

## Local data

User data is stored in the SQLite database `database/bot.sqlite3`. The `/flag` and `/stream`
commands store the selected flag and Twitch link in each user's record, alongside their Elo
rating. The local database
is ignored by Git. The SQLite schema and pragmas are defined in `database/schema.sql`.

## Project layout

The Python package is organized by responsibility. Domain entities do not know about Discord
or storage, race workflows own one lifecycle concern each, and Discord command/view modules stay
thin. Object construction is centralized in `discord_ui/extension.py`.

```text
config/
└── race_options.yaml       # Dynamic /race create option groups
database/
├── backups/                # Timestamped season CSV backups (ignored)
├── bot.sqlite3             # Local user database (ignored)
└── schema.sql              # SQLite schema and pragmas
src/speedrun_race_bot/
├── bot.py                  # Bot startup and command synchronization
├── settings.py             # Environment-backed application settings
├── domain/                 # Race and player entities
├── race/                   # Lifecycle, countdown, results, Elo, replay, and seed workflows
├── persistence/            # SQLite repositories
├── integrations/           # Randomizer API, seed process, and Discord voice adapters
├── discord_ui/
│   ├── commands/           # Commands grouped by race, profile, replay, and admin use
│   ├── controls.py         # Persistent race message buttons
│   ├── race_tracker.py     # Tracker embed rendering and updates
│   ├── tracker_template.py # Markdown template parser
│   └── extension.py        # Dependency composition and Discord registration
└── templates/
    └── race_tracker.md     # Tracker copy and field fragments
tools/
├── generate_race_seed.py   # Stable executable entry point used by .env
└── seed_generator/         # Config, naming, process, SotN, and CLI modules
```
