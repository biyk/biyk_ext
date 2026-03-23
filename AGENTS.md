# AGENTS.md - Biyk Extensions Framework

## Project Overview
This is a FoundryVTT module that provides a modular extension loader with dynamic activation. The framework loads extensions from the `extensions/` directory based on settings in `registry.js`.

## Project Structure
```
biyk_ext/
├── main.mjs          # Main entry point - initializes extension loader
├── settings.mjs      # Registers module settings for each extension
├── registry.js       # Registry of all available extensions
├── module.json       # FoundryVTT module manifest
├── release.ps1       # PowerShell script for releasing new versions
├── AGENTS.md         # This file
└── extensions/       # Individual extension modules
    └── <extension>/
        └── index.js  # Extension implementation with init() function
```

## Build/Lint/Test Commands
- **No build system**: This is a vanilla JavaScript module, no compilation required
- **No tests**: No test framework configured
- **No linting**: No linting configured

### Release Commands
To release a new version:
```powershell
powershell -File release.ps1
```

This script will:
1. Increment the patch version in `module.json`
2. Create a ZIP archive (module.zip)
3. Create a git commit, tag, and push
4. Create a GitHub release

## Code Style Guidelines

### File Organization
- Main framework files use `.mjs` extension (main.mjs, settings.mjs)
- Extension files use `.js` extension
- Each extension lives in its own folder under `extensions/`
- Each extension must export an `init()` function

### Naming Conventions
- Extensions: lowercase with hyphens (e.g., `currency-watcher`, `sanctuary`)
- Folder names match extension IDs exactly
- Registry keys match folder names
- Effect labels and status IDs use camelCase or descriptive names

### Extension Structure
```javascript
// extensions/<name>/index.js
export function init() {
    Hooks.on("hook-name", async (args) => {
        // Implementation
    });
}
```

### Import Style
- Framework files: ES modules with `.mjs` extension
- Extension files: CommonJS-compatible (no imports in extensions)
- Access global `game`, `canvas`, `ui`, `Hooks`, `CONST` objects
- Use dynamic import in main.mjs to load extensions: `import(\`./extensions/${ext}/index.js\`)`

### FoundryVTT API Patterns
```javascript
// Settings registration (handled by settings.mjs)
game.settings.register('biyk_ext', key, {
    name: "Extension Label",
    hint: "Enable this extension",
    scope: "world",
    config: true,
    default: false,
    requiresReload: true,
    type: Boolean
});

// Hook registration
Hooks.on("hook-name", async (args) => { /* handler */ });
Hooks.once("hook-name", async (args) => { /* one-time handler */ });

// Scene flags
canvas.scene.getFlag("world", "flagName");
await canvas.scene.setFlag("world", "flagName", value);
await tokenDoc.unsetFlag("world", "flagName");

// Actor modifications
await actor.update({ "system.attribute": value });
await actor.createEmbeddedDocuments("ActiveEffect", [effectData]);

// Chat messages
ChatMessage.create({
    content: "Message text",
    speaker: { alias: "Speaker Name" },
    whisper: [game.user.id]  // for GM-only messages
});

// Notifications
ui.notifications.info("Message");
ui.notifications.warn("Warning");
ui.notifications.error("Error");

// User checks
game.user.isGM  // Check if current user is GM
```

### Error Handling
- Wrap async operations in try/catch blocks
- Log errors with `console.error()`
- Show user-friendly errors via `ui.notifications.error()`
- Example:
```javascript
try {
    await someAsyncOperation();
} catch (error) {
    console.error("ExtensionName | Error description:", error);
    ui.notifications.error("Failed to perform action");
}
```

### Code Comments
- Use Russian comments for localized D&D 5e content (most extensions are Russian-localized)
- Use English for generic framework code
- Comment complex logic and calculations
- Document magic numbers and constants

### Active Effects
When creating active effects, use this structure:
```javascript
{
    label: "Effect Name",
    icon: "icons/svg/example.svg",
    origin: sourceItem.uuid,
    duration: { 
        seconds: convertToSeconds(duration, unit), 
        startTime: game.time.worldTime 
    },
    flags: { 
        core: { statusId: "id" }, 
        dnd5e: { effectType: "spell" } 
    },
    changes: [
        { 
            key: "flags.dnd5e.advantage.ability.save.str",
            mode: CONST.ACTIVE_EFFECT_MODES.ADD, 
            value: 1, 
            priority: 20 
        }
    ]
}

// Helper for duration conversion
function convertToSeconds(duration, unit) {
    if (duration === 0) return 0;
    switch(unit.toLowerCase()) {
        case "round": return duration * 6;
        case "minute": return duration * 60;
        case "hour": return duration * 3600;
        case "day": return duration * 86400;
        default: return duration;
    }
}
```

### Common Hooks Used
- `midi-qol.preAttackRoll` - Before attack roll (for damage modifiers)
- `dnd5e.useItem` - When an item is used
- `combatTurn` - When combat turn starts
- `preUpdateToken` - Before token movement
- `preUpdateCombat` - Before combat changes (round changes, combat ends)
- `renderActorSheet` - When actor sheet is rendered

### Adding New Extensions
1. Create folder in `extensions/<name>/`
2. Add `index.js` with exported `init()` function
3. Add entry to `registry.js`:
   ```javascript
   "<name>": { label: "Extension Name", reload: true }
   ```
4. The extension will automatically appear in FoundryVTT settings

### Important Notes
- All extensions run on both `init` and `ready` hooks via main.mjs
- Extensions are only loaded if their setting is enabled
- Extensions can use `game.user.isGM` to check GM permissions
- Combat tracking uses `game.combat` and `combat.combatants`
- Token data accessed via `tokenDoc.actor` or `token.actor`
- Use `workflow` object from midi-qol hooks for attack/damage data
- Always check if required objects exist before using them