# Speedrun Race Bot

A starter Discord bot for running casual speedrun races. It currently keeps race data in memory, which makes it ideal for development and prototyping; add a database before relying on it in production.

## Setup

1. Install Python 3.11 or newer.
2. Install [Poetry](https://python-poetry.org/docs/) and install dependencies:

   ```powershell
   poetry install
   ```

3. Copy `.env.example` to `.env`, then add your Discord bot token and set `RACE_GAME`.
4. Invite the bot to a test server with the `bot` and `applications.commands` scopes.
5. Run it:

   ```powershell
   poetry run python -m speedrun_race_bot
   ```

Set `DISCORD_GUILD_ID` in `.env` during development so slash commands are available immediately in that server.

## Voice announcements

`/race create` requires a voice channel. The bot joins it and announces each racer
with text-to-speech. The bot role needs **View Channel**, **Connect**, and **Speak**
permissions in that voice channel. Install [FFmpeg](https://ffmpeg.org/download.html)
and make sure `ffmpeg` is available on your system `PATH`; it is required to play
the generated speech audio.

## Race-start options

Edit [config/race_options.yaml](config/race_options.yaml) to configure optional `/race create`
parameters. Each entry needs a user-facing `name` and a list of selectable values;
each entry becomes its own command parameter (for example, `Randomizer preset`
becomes `randomizer_preset:`). Discord permits up to 22 configured parameters, and
each parameter may have up to 25 values. The chosen values appear
in the race tracker and are passed to the seed command as the JSON dictionary
`RACE_START_OPTIONS`.

```yaml
race_start_options:
  - name: Difficulty
    value: [normal, hard, expert]
```

## Optional randomizer seed generation

Set `SEED_GENERATOR_COMMAND` to a shell command to generate a seed when each
race is created. The command is run from the project folder. It receives these
environment variables: `RACE_GAME`, `RACE_CATEGORY`, `RACE_GUILD_ID`,
`RACE_CHANNEL_ID`, `RACE_SEEDS_DIRECTORY`, and `RACE_START_OPTIONS`.

For example, a generator command might be:

```env
SEED_GENERATOR_COMMAND=py tools/generate_seed.py
```

For a safe end-to-end test, use the included dummy generator instead:

```env
SEED_GENERATOR_COMMAND=py tools/print_seed_environment.py
```

It prints the environment values received by the command and writes a temporary
`dummy-seed.txt` file for the bot to upload.

The command must write exactly one new or changed file under `seeds/`. On success,
the bot uploads that file into the race channel and deletes the local copy. If the
command fails or no unambiguous seed file is found, the race remains in the lobby.

## Starter commands

- `/race create channel:<#race-channel> voice_channel:<voice> annotation:<text> ...` — generate a seed and create a lobby
- **Join Race** button — join the active lobby from its live tracker
- **Ready** button — mark yourself ready; all racers must be ready before starting
- **Start Race** button — start the race (host only) once everyone is ready
- `/race status` — show the active race
- `/race start` — command alternative to the Start Race button
- `/race finish` — record the current race-timer value as your finish time
- `/flag emoji:<🇺🇸>` — save a country flag shown beside your racer name

## Project layout

```text
src/speedrun_race_bot/
├── cogs/races.py       # Discord slash commands
├── config.py           # Environment configuration
├── models.py           # Domain models (including the live tracker message ID)
├── seed_generation.py  # Optional randomizer seed command support
├── services/races.py   # Race state and business rules
├── templates/          # Discord Markdown templates
└── main.py             # Bot setup and startup
```
