export function init() {
    if (!game.user?.isGM) return;

    const LOG_PREFIX = "[WeatherByDayTime]";

    async function ensurePlaylistFolder() {
        if (!game.folders) return;
        let folder = game.folders.find(f => f.name === "Дорога" && f.type === "Playlist");
        if (!folder) {
            console.log(`${LOG_PREFIX} Creating "Дорога" playlist folder...`);
            try {
                folder = await Folder.create({ name: "Дорога", type: "Playlist" });
                console.log(`${LOG_PREFIX} Created playlist folder "${folder.name}" (${folder.id})`);
            } catch (err) {
                console.error(`${LOG_PREFIX} Failed to create playlist folder:`, err);
                return null;
            }
        } else {
            console.log(`${LOG_PREFIX} Playlist folder "${folder.name}" found (${folder.id})`);
        }
        return folder;
    }

    function getDayTracks(entry) {
        if (entry?.tracks && Array.isArray(entry.tracks)) return entry.tracks;
        if (Array.isArray(entry)) return entry;
        return [];
    }

    function soundPath(path) {
        return path.replace(/&/g, '%26');
    }

    function soundName(path) {
        return path.split("/").pop();
    }

    async function getPlaylists() {
        const resp = await fetch("modules/biyk_ext/extensions/weather_by_day_time/data/playlist.json");
        return await resp.json();
    }

    async function syncPlaylistSounds(playlist, wantedPaths) {
        const wanted = new Map(wantedPaths.map(p => [soundName(p), soundPath(p)]));
        const validExts = ["mp3", "ogg", "wav", "flac", "m4a", "webm"];
        let changed = false;
        for (const sound of playlist.sounds || []) {
            const ext = sound.path?.split(".").pop()?.toLowerCase();
            const keep = wanted.has(sound.name) && ext && validExts.includes(ext);
            if (!keep) {
                console.log(`${LOG_PREFIX}  Removing "${sound.name || sound.path}" from "${playlist.name}"`);
                await sound.delete();
                changed = true;
            }
        }
        const remaining = new Set((playlist.sounds || []).map(s => s.name));
        for (const [name, path] of wanted) {
            if (!remaining.has(name)) {
                console.log(`${LOG_PREFIX}  Adding "${name}" to "${playlist.name}"`);
                await playlist.createEmbeddedDocuments("PlaylistSound", [{ name, path }]);
                changed = true;
            }
        }
        // Log constructed URLs for debug
        for (const s of playlist.sounds || []) {
            const src = s.path;
            if (src && src.includes('&')) {
                console.log(`${LOG_PREFIX}  WARNING: path contains raw &: "${src}" - may cause fetch errors`);
            }
        }
        return changed;
    }

    async function ensureDayPlaylists(folder) {
        if (!folder) return;
        if (!game.playlists) return;
        const pl = await getPlaylists();
        for (const [day, entry] of Object.entries(pl)) {
            const tracks = getDayTracks(entry);
            if (tracks.length === 0) continue;
            const name = `День ${day}`;
            let playlist = game.playlists.find(p => p.name === name && p.folder?.id === folder.id);
            if (!playlist) {
                const sounds = tracks.map(p => ({ name: soundName(p), path: soundPath(p) }));
                try {
                    await Playlist.create({ name, folder: folder.id, sounds });
                    console.log(`${LOG_PREFIX} Created playlist "${name}" with ${sounds.length} tracks`);
                } catch (err) {
                    console.error(`${LOG_PREFIX} Failed to create playlist "${name}":`, err);
                }
            } else {
                const changed = await syncPlaylistSounds(playlist, tracks);
                if (changed) console.log(`${LOG_PREFIX} Synced playlist "${name}"`);
            }
        }
    }

    async function initPlaylists() {
        const folder = await ensurePlaylistFolder();
        await ensureDayPlaylists(folder);
    }
    initPlaylists();

    const START_YEAR = 1489, START_MONTH = 2, START_DAY = 22, START_HOUR = 6;

    let lastKey = "";
    let calendar = null;

    async function getCalendar() {
        if (calendar) return calendar;
        const resp = await fetch("modules/biyk_ext/extensions/weather_by_day_time/data/calendar.json");
        calendar = await resp.json();
        return calendar;
    }

    // Harptos cumulative days before each month (1-indexed, non-leap)
    function monthOffset(month, leap) {
        const off = [0, 0, 31, 61, 91, 122, 152, 182, 213, leap ? 244 : 243, leap ? 274 : 273, leap ? 304 : 303, leap ? 335 : 334];
        return off[month] ?? 0;
    }

    function isLeap(y) { return y % 4 === 0; }

    function totalDays(y, m, d) {
        let t = 0;
        for (let i = 0; i < y; i++) t += isLeap(i) ? 366 : 365;
        t += monthOffset(m, isLeap(y)) + d;
        return t;
    }

    function getTimeOfDay(h) {
        if (h < 6) return "night";
        if (h < 12) return "morning";
        if (h < 18) return "day";
        return "evening";
    }

    Hooks.on("simple-calendar-date-time-change", async (data) => {
        if (!game.user?.isGM) return;
        if (!data?.date) return;

        const { year, month, hour } = data.date;
        if (year == null || month == null) return;

        const currentDay = await SimpleCalendar.api.getCurrentDay();
        if (!currentDay) return;
        const day = currentDay.numericRepresentation;

        console.log(`${LOG_PREFIX} Date change detected: ${year}.${month}.${day} ${hour}:00`);

        // Handle holidays: skip if month outside 1-12 (holidays use special IDs)
        if (month < 1 || month > 12) {
            console.log(`${LOG_PREFIX} Holiday month (${month}), skipping`);
            return;
        }

        const startTotal = totalDays(START_YEAR, START_MONTH, START_DAY);
        const currTotal = totalDays(year, month, day);
        const journeyDay = currTotal - startTotal + 1;

        console.log(`${LOG_PREFIX} Journey day: ${journeyDay}`);

        if (journeyDay < 1 || journeyDay > 58) {
            console.log(`${LOG_PREFIX} Outside journey range (1-58), skipping`);
            return;
        }

        const tod = getTimeOfDay(hour);
        const key = `${journeyDay}-${tod}`;
        if (key === lastKey) {
            console.log(`${LOG_PREFIX} Same key ${key}, skipping`);
            return;
        }
        lastKey = key;

        const cal = await getCalendar();
        const entry = cal.find(e => e.day === journeyDay);
        if (!entry) {
            console.log(`${LOG_PREFIX} No calendar entry for day ${journeyDay}`);
            return;
        }

        console.log(`${LOG_PREFIX} Updating weather for day ${journeyDay}, time: ${tod} (${entry.calendar_date})`);

        const todLabel = { morning: "Утро", day: "День", evening: "Вечер", night: "Ночь" }[tod] || tod;
        ChatMessage.create({
            speaker: { alias: "Погода и атмосфера" },
            content: `<article>
  <h3>${entry.calendar_date} — ${todLabel}</h3>
  <p><strong>Локация:</strong> ${entry.location || "—"}</p>
  <p><strong>Событие:</strong> ${entry.event || "—"}</p>
  <p><strong>Погода:</strong> ${entry.weather || "—"}</p>
  <hr>
  <p><em>${entry.notes || ""}</em></p>
</article>`,
            whisper: [game.user.id]
        });

        const effects = entry.weather_object?.times?.[tod] || entry.weather_object?.particles || [];
        if (effects.length > 0) {
            console.log(`${LOG_PREFIX} Applying ${effects.length} particle effect(s)`);
            Hooks.call("fxmaster.updateParticleEffects", effects);
        } else {
            console.log(`${LOG_PREFIX} No particle effects for ${journeyDay}/${tod}`);
        }

        // Also update scene darkness based on time of day
        const scene = game.scenes?.active;
        if (scene?.globalLight !== undefined) {
            let darkness;
            if (hour < 6) darkness = 0.7;
            else if (hour < 12) darkness = 0.3;
            else if (hour < 18) darkness = 0.0;
            else darkness = 0.5;
            if (Math.abs(scene.darkness - darkness) > 0.05) {
                console.log(`${LOG_PREFIX} Updating scene darkness: ${scene.darkness} -> ${darkness}`);
                scene.update({ darkness });
            }
        }

        // Update tile image on the road scene FIRST, independent of playlists,
        // so an early "return" in the music logic below can never skip it.
        const ROAD_SCENE_ID = "q2be0cq4lQvHr2KS";
        const ROAD_TILE_ID = "Y13np4o1dLgdjHpn";
        const roadScene = game.scenes?.get(ROAD_SCENE_ID);
        if (roadScene) {
            const tile = roadScene.tiles?.get(ROAD_TILE_ID);
            if (tile) {
                const defaultImg = "%D0%94%D0%BE%D1%80%D0%BE%D0%B3%D0%B0.jpeg";
                let img = defaultImg;
                if (journeyDay >= 1 && journeyDay <= 58 && entry?.image) {
                    img = entry.image;
                }
                if (tile.texture?.src !== img) {
                    console.log(`${LOG_PREFIX} Updating tile image: "${tile.texture?.src}" -> "${img}"`);
                    await tile.update({ "texture.src": img });
                    if (game.scenes.active?.id === roadScene.id) await canvas.draw();
                }
            } else {
                console.warn(`${LOG_PREFIX} Road tile "${ROAD_TILE_ID}" not found in scene "${ROAD_SCENE_ID}"`);
            }
        } else {
            console.warn(`${LOG_PREFIX} Road scene "${ROAD_SCENE_ID}" not found`);
        }

        // Handle day music: start/switch playlist
        if (!game.playlists) return;
        const folder = game.folders.find(f => f.name === "Дорога" && f.type === "Playlist");
        if (!folder) return;
        const target = game.playlists.find(p => p.name === `День ${journeyDay}`);
        if (target?.playing) {
            console.log(`${LOG_PREFIX} Playlist "${target.name}" already playing, skipping`);
            return;
        }
        // Stop all playlists in folder, then play current day's
        for (const pl of game.playlists) {
            if (pl.folder?.id === folder.id) {
                await pl.stopAll();
            }
        }
        if (target) {
            console.log(`${LOG_PREFIX} Playing playlist "${target.name}"`);
            await target.playAll();
        }
    });
}
