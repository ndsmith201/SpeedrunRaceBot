# Speedrun Race Bot

A Discord bot for organizing casual speedrun races. Race state is stored in memory, so restarting the bot clears active races and their current results.

## Setup

1. Install Python 3.11 or newer.
2. Install [Poetry](https://python-poetry.org/docs/) and dependencies:

   ```powershell
   poetry install
   ```

3. Copy `.env.example` to `.env`, then set `DISCORD_TOKEN` and `RACE_GAME`.
4. Invite the bot with the `bot` and `applications.commands` scopes.
5. Run the bot:

   ```powershell
   poetry run python -m speedrun_race_bot
   ```

Set `DISCORD_GUILD_ID` during development for immediate slash-command updates in that server. Restart the bot after changing `config/race_options.yaml` so Discord can register the updated `/race create` fields.

## Race flow

1. Create a lobby with `/race create`.
2. Players use **Join Race** to join or leave the lobby, then **Ready** to toggle their ready state.
3. Any joined participant can start once every racer is ready and the seed is available.
4. Starting plays a random audio cue, then shows a 0.8-second-per-step 🔴, 🔵, 🟡 countdown. The race begins on 🟢, then changes to 🏁.
5. During the race, players use **Finish** to record the timer automatically or **Forfeit** to record a loss.
6. The race completes only after every participant has finished or forfeited. A completed race can be replaced with a new lobby in the same channel.

Finish times use `HH:MM:SS.mmm` and the tracker sorts completed racers by time. Forfeits are shown with 💩 and placed after racers who are still running.

## Commands and controls

- `/race create channel:<#race-channel> voice_channel:<voice> annotation:<text> ...` — creates a lobby. `annotation:` is optional.
- `/race start` — starts the countdown; any joined participant may use it.
- `/race finish` — records the current race timer as your finish time.
- `/race status` — posts the current tracker.
- `/flag emoji:<🇺🇸>` — saves a Unicode country flag for your racer name.
- **Join Race** — joins the lobby; press again to leave.
- **Ready** — toggles ready/unready.
- **Start Race** — starts the countdown when all racers are ready.
- **Finish** — records the current race timer.
- **Forfeit** — records a forfeit and an automatic loss.

The tracker is an embed with a yellow lobby stripe, green running stripe, and grey completed stripe. Flags appear to the left of racer names. The tracker's Markdown layout is defined in [race_tracker.md](src/speedrun_race_bot/templates/race_tracker.md).

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
SEED_GENERATOR_COMMAND=py tools/print_seed_environment.py
```

Generation runs in the background. The lobby appears immediately, shows the configured `alycardwalkcycle` custom emoji while generating, and cannot be started until the seed succeeds. The generated seed is uploaded as a follow-up message; its download link is shown at the bottom of the tracker.

The command runs from the project directory and must create or update exactly one file under `seeds/`. The bot passes these environment variables:

- `RACE_GAME`
- `RACE_CATEGORY` (currently empty because `/race create` has no category field)
- `RACE_GUILD_ID`
- `RACE_CHANNEL_ID`
- `RACE_SEEDS_DIRECTORY`
- `RACE_START_OPTIONS` — JSON dictionary of the selected race options

For example, `RACE_START_OPTIONS` can be:

```json
{"Randomizer preset":"safe","Tournament Mode":"true"}
```

`tools/print_seed_environment.py` is a safe test generator: it prints all `RACE_` variables and creates a dummy seed file.

## Voice and audio

The bot needs **View Channel**, **Connect**, and **Speak** in the selected voice channel. Install [FFmpeg](https://ffmpeg.org/download.html) and ensure `ffmpeg` is available on `PATH`.

- [audio/player_joined.mp3](audio/player_joined.mp3) plays when a racer joins.
- [audio/ready_error.mp3](audio/ready_error.mp3) plays for readiness failures and unexpected slash-command errors during an active race.
- Put `.mp3`, `.ogg`, `.wav`, or `.m4a` start cues in [audio/countdown](audio/countdown). One file is chosen randomly when **Start Race** is pressed.

The bot disconnects from the voice channel after the countdown ends.

## Local data

`/flag` saves a user-to-flag mapping in `data/user_flags.json`. This local file is ignored by Git.

## Project layout

```text
audio/
├── countdown/              # Random race-start audio files
├── player_joined.mp3
└── ready_error.mp3
config/
└── race_options.yaml       # Dynamic /race create option groups
src/speedrun_race_bot/
├── cogs/races.py           # Commands, buttons, countdown, and tracker rendering
├── models.py               # Race and entrant state
├── seed_generation.py      # Background seed-generator command support
├── services/               # Race, voice, and local flag services
└── templates/race_tracker.md
tools/
└── print_seed_environment.py
```
