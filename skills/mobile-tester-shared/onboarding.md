# Onboarding

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Runs once per project folder: on the first test request when `.mobile-tester/config.yaml` is missing, or when the user asks to redo it.
One config serves both platforms: a project that already has it only adds what a new app or platform needs.

The aim is one longer conversation up front and then sessions that run without stopping.
So ask little, infer the rest from the answers, and show it all back once in the session plan, where the user can still change anything.
Ask with your question tool (AskUserQuestion in Claude Code) or in chat; open questions are free text, choices have the recommended option first.

## 1. Detect, don't ask

Before the first question, find out what the tools and the machine already know:
- `dt doctor` and `dt devices`: which devices are connected, and how the user's device list (`~/.config/mobile-tester/devices.yaml`) knows each one: test device, personal device, or not saved yet.
- `dt -s DEVICE info` for the chosen device: navigation, keyboard, locale (for the report; nothing to ask).
- Tester name: `git config user.name`, else the system user name.
- When the request names the app: `dt app find "<name>"`, and whether a profile exists in `.mobile-tester/apps/`.
- Jira: whether Atlassian or Jira tools are available in this session.
- Whether the project has a `.gitignore`.

Defaults that are never asked: reports folder `reports/`, report language = the language the user writes in, severity scale from [report-standard.md](report-standard.md), autopilot on with the standard defaults from [autopilot.md](autopilot.md), telemetry off.

## 2. Three open questions

Ask all three in one message; each is free text, and the user may paste docs or links:

1. **"What is your app about?"** What it is for, who uses it, the main things people do in it, the rules it must follow, account types.
2. **"How do you want it tested?"** What to focus on, how long, on which device, any extra checks (offline, font sizes and dark mode, the app killed in the background, permissions taken away), Jira or not, and how hands-off it should be.
3. **"What must never happen?"** Actions a test must never take (for example placing an order, messaging real people, changing the account), and anything normally off-limits that is fine in this app (for example logging out and back in).

When the request already answers one of them (an app description pasted with the request, "explore everything for 30 minutes"), don't ask it again.

## 3. Fill in from the answers

| From | Fills |
|---|---|
| 1. The app | `about.description` in the user's own words (don't summarise it away); `about.users`, `main_flows`, `rules`, `roles`, `integrations`, `glossary`; `about.not_in_scope` and `outside_scope.not_ready` for areas they call unfinished or off-limits; `risky_areas`; `login.method` (guest, account) |
| 2. Testing | the first session's mode, charter and time box; the device; extra checks; Jira; `autopilot.enabled` (off only when they want to approve each step); telemetry when they want numbers |
| 3. Never | `forbidden` (their list on top of the standard one in [autopilot.md](autopilot.md)) and `grants` (what they explicitly allow) |
| Login method | `reset.strategy`: `clear-data` when the login can be redone without the user (guest, secrets file, login hook), otherwise `restart` |

Use the app's own terms; never add flows, rules or checks the user didn't mention.
`reset.after` (what a fresh start shows: intro screens, region choice) is learned at the first reset in the first session: write it into the profile then and say so at wrap-up.
`outside_scope.report` defaults to true: problems noticed outside the charter get their own report section.

## 4. One round for the gaps

Ask only what neither the answers nor the detection settle, in one round of at most four questions, recommended option first:
- A physical device that isn't saved yet: a short name, and test device or personal phone. Save it with `dt devices --save <serial or UDID> --name "<name>" --test` (or `--personal`).
- The login, when the answers leave it open (guest, an account from `secrets.local.yaml` the user fills in themselves, or the user logs in on the device). Never ask for passwords in chat.
- Anything the answers contradict or leave ambiguous enough to change what gets tested.

Never ask about the report language, severity rules, the expected signer (only when installing a build from a file), hook scripts (offer them later when a setup repeats), the `.gitignore` (it's a line in the plan), or the autopilot catalog (the plan shows what autopilot will do).

## 5. Write everything, then plan

1. Write `.mobile-tester/config.yaml` from `templates/config.yaml` and `.mobile-tester/apps/<package>/profile.yaml` and `notes.md` from the templates, all at once.
   `notes.md` is for what testers learn over time (screen map, quirks); the app's purpose and rules belong in `about`.
   `secrets.local.yaml` only when the login method is `secrets`; the user fills it in.
2. Go straight on to the session plan ([session-plan.md](session-plan.md)): the answers above already fill it, so it asks nothing new.
   The plan includes the `.gitignore` lines (`.mobile-tester/state/`, `.mobile-tester/**/secrets.local.yaml`, and `reports/` when screenshots may show personal data); they are added when the user picks Go.

The same app on both platforms gets two profiles (package and bundle id usually differ); the second can copy the first one's `about` after the user confirms the apps behave the same.
