# AGENTS.md - Biyk Extensions Framework

## Architecture Overview
- **2 ESModules**: `main.mjs` (loader) + `settings.mjs` (settings registration). Both in `esmodules`.
- **Extension patterns**: Most extensions use Midi-QOL hooks (`midi-qol.preAttackRoll`, `midi-qol.RollComplete`). Others use Foundry hooks directly (`combatTurn`, `preUpdateToken`, etc.).
- **deepVoyager**: Complex AI-powered subsystem (see `extensions/deepVoyager/`). Orchestrates combat via `localhost:9999` API. Actions: `move`, `target`, `use`, `api`. Utilities: `combat`, `dm`, `help`, `logger`, `messageBox`, `prompt`, `tokenInfo`.

## Project Structure
```
biyk_ext/
├── main.mjs           # Extension loader - calls loadExtensions() on ready hook
├── settings.mjs       # Registers module settings, calls init hook
├── registry.js        # Extension registry (label, reload flag)
├── module.json        # FoundryVTT manifest
├── info.js            # Socket/IPC documentation
└── extensions/        # One folder per extension
    ├── <name>/index.js  # Must export init()
    └── deepVoyager/    # Special: has actions/ and utils/ subdirs
```

## Extension Registration
```javascript
// registry.js
"<name>": { label: "Extension Label", reload: true }
```
Extensions auto-appear in settings. No build step needed.

## Key Patterns

### Midi-QOL Hooks (most extensions)
```javascript
Hooks.on("midi-qol.preAttackRoll", async (workflow) => { /* */ });
Hooks.on("midi-qol.RollComplete", async (workflow) => { /* */ });
```

### Foundry Hooks
```javascript
Hooks.on("combatTurn", async (combat, token, turn) => { /* */ });
Hooks.on("preUpdateToken", async (tokenDoc, changes) => { /* */ });
Hooks.on("dnd5e.useItem", async (item, config, options) => { /* */ });
```

### Active Effects
```javascript
function convertToSeconds(duration, unit) {
    switch(unit.toLowerCase()) {
        case "round": return duration * 6;
        case "minute": return duration * 60;
        case "hour": return duration * 3600;
        case "day": return duration * 86400;
        default: return duration;
    }
}
```

### GM Checks & Chat
```javascript
if (!game.user.isGM) return;
ChatMessage.create({ content: "...", whisper: [game.user.id] });
```

### Settings
```javascript
game.settings.register('biyk_ext', key, {
    name: "Label", hint: "Desc", scope: "world", config: true,
    type: Boolean, default: false, requiresReload: true
});
```

## Release
```powershell
powershell -File release.ps1  # increments version, creates zip, git tag, GitHub release
```

## graphify

Knowledge graph at `graphify-out/` (135 nodes, 144 edges, 38 communities).

Before reading source files, run `/graphify query "<question>"` or check `graphify-out/GRAPH_REPORT.md`.

God nodes (integration hubs):
- `convertToSeconds()` (7 edges) - shared utility
- `log` (6 edges) - deepVoyager logger
- `getAction()` (5 edges) - AI API bridge
- `getStatus()` (5 edges) - token/combat status

Known gaps: `combat`, `combatant`, `damageHP`, `newHP` are weakly connected (isolated nodes).

Run `graphify update .` after code changes (AST-only, no API cost).
