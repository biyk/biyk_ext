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

    async function ensureDayPlaylists(folder) {
        if (!folder) return;
        if (!game.playlists) return;
        const cal = await getCalendar();
        let created = 0;
        for (const entry of cal) {
            const name = `День ${entry.day}`;
            const existing = game.playlists.find(p => p.name === name && p.folder?.id === folder.id);
            if (existing) continue;
            const sounds = entry.music.map(p => ({ name: p.split("/").pop(), path: p }));
            try {
                await Playlist.create({ name, folder: folder.id, sounds });
                created++;
            } catch (err) {
                console.error(`${LOG_PREFIX} Failed to create playlist "${name}":`, err);
            }
        }
        if (created > 0) console.log(`${LOG_PREFIX} Created ${created} day playlist(s)`);
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
