(() => {
    "use strict";

    const WINDOW_SECONDS = 300;
    const GROUPS = { angle: ["angle"], temperature: ["temperature"], power: ["voltage", "current"], fineangle: ["fine_angle"] };
    const signals = new Map(Object.values(GROUPS).flat().map(name => [name, { seen: null, error: false }]));
    const element = id => document.getElementById(id);
    let ready = false, active = false;
    let temperaturePlot, powerPlot, fineAnglePlot;
    let temperatureData = [[], []], powerData = [[], [], []], fineAngleData = [[], []];
    let lastVoltage = null, lastCurrent = null, lastWrapped = null;
    let needleRotation = 0, dirtyTemperature = false, dirtyPower = false, dirtyFineAngle = false;

    function state(group, text) {
        element(`${group}-state`).textContent = text;
        element(`${group}-card`).dataset.state = text.toLowerCase();
    }

    function refreshStates() {
        if (!active) return;
        const now = performance.now();
        for (const [group, names] of Object.entries(GROUPS)) {
            const entries = names.map(name => signals.get(name));
            const valid = entries.filter(entry => entry.seen !== null && !entry.error);
            if (entries.some(entry => entry.error)) state(group, valid.length ? "Partial" : "Unavailable");
            else if (valid.length !== entries.length) state(group, "Waiting");
            else if (entries.some(entry => now - entry.seen > 3000)) state(group, "Stale");
            else state(group, "Live");
        }
    }

    function drawAngle(raw) {
        const degrees = ((raw % 360) + 360) % 360;
        // Never display 360.00 when rounding near the wrap.
        const displayed = (Math.round(degrees * 100) % 36000) / 100;
        element("angle-value").textContent = displayed.toFixed(2);
        if (lastWrapped === null) needleRotation = degrees;
        else needleRotation += ((degrees - lastWrapped + 540) % 360) - 180;
        lastWrapped = degrees;
        element("angle-needle").style.transform = `rotate(${needleRotation}deg)`;
        const dial = element("angle-dial");
        dial.dataset.hasValue = "true";
        dial.dataset.angle = String(degrees);
        dial.setAttribute("aria-label", `Computed angle ${displayed.toFixed(2)} degrees`);
    }

    function append(data, seconds, ...values) {
        data[0].push(seconds);
        values.forEach((value, index) => data[index + 1].push(value));
        let remove = 0;
        while (remove < data[0].length && data[0][remove] < seconds - WINDOW_SECONDS) remove++;
        const maxPoints = data === fineAngleData ? 15000 : 2000;
        remove = Math.max(remove, data[0].length - maxPoints);
        if (remove > 0) data.forEach(series => series.splice(0, remove));
    }

    function handleMessage(message) {
        if (!ready || !active || !signals.has(message.signal)) return;
        const entry = signals.get(message.signal);
        if (message.type === "metric_error") {
            entry.error = true;
            const group = Object.keys(GROUPS).find(group => GROUPS[group].includes(message.signal));
            element(`${group}-state`).title = `${message.signal}: ${message.message}`;
            refreshStates();
            return;
        }
        const raw = Number(message.value), seconds = Number(message.elapsed_s);
        if (!Number.isFinite(seconds) || seconds < 0) return;
        if (message.signal === "angle") {
            if (!Number.isFinite(raw) || message.unit !== "deg" || message.source !== "pcap14") return;
        } else if (!Number.isSafeInteger(raw)) return;
        if (message.signal === "fine_angle" &&
            (message.unit !== "urad" || message.source !== "ranger" || message.parameter !== "angle")) return;
        entry.seen = performance.now();
        entry.error = false;
        switch (message.signal) {
            case "angle": drawAngle(raw); break;
            case "fine_angle": {
                // Firmware publishes signed radians * 1,000,000. Preserve
                // the wraps; this is neither unwrapped nor divided by three.
                const radians = raw / 1_000_000;
                element("fineangle-value").textContent = radians.toFixed(6);
                append(fineAngleData, seconds, radians);
                dirtyFineAngle = true;
                window.dispatchEvent(new CustomEvent("ace-parameter-sample", {
                    detail: { parameter: "angle", value: raw },
                }));
                break;
            }
            case "temperature":
                const temperatureC = raw / 1000;
                element("temperature-value").textContent = temperatureC.toFixed(1);
                append(temperatureData, seconds, temperatureC);
                dirtyTemperature = true;
                break;
            case "voltage":
                lastVoltage = raw / 1000;
                element("dashboard-voltage").textContent = lastVoltage.toFixed(3);
                append(powerData, seconds, lastVoltage, lastCurrent);
                dirtyPower = true;
                break;
            case "current":
                lastCurrent = raw / 1000;
                element("dashboard-current").textContent = lastCurrent.toFixed(3);
                append(powerData, seconds, lastVoltage, lastCurrent);
                dirtyPower = true;
                break;
        }
        refreshStates();
    }

    function start() {
        active = true;
        temperatureData = [[], []];
        powerData = [[], [], []];
        fineAngleData = [[], []];
        lastVoltage = lastCurrent = lastWrapped = null;
        needleRotation = 0;
        signals.forEach(entry => { entry.seen = null; entry.error = false; });
        ["angle-value", "temperature-value", "dashboard-voltage", "dashboard-current", "fineangle-value"].forEach(id => element(id).textContent = "—");
        element("angle-dial").dataset.hasValue = "false";
        element("angle-dial").setAttribute("aria-label", "Angle awaiting data");
        Object.keys(GROUPS).forEach(group => { state(group, "Waiting"); element(`${group}-state`).title = ""; });
        dirtyTemperature = dirtyPower = dirtyFineAngle = true;
    }

    function pause(label = "Paused") {
        active = false;
        Object.keys(GROUPS).forEach(group => state(group, label));
    }

    function axis(scale, side, digits) {
        return {
            scale, side, size: 45, stroke: "#9dafc4", font: "10px sans-serif",
            values: (_plot, values) => values.map(value => value.toFixed(digits)),
            grid: { show: side !== 1, stroke: "rgba(255,255,255,.065)" },
            ticks: { stroke: "rgba(255,255,255,.08)" },
        };
    }

    function createPlot(id, series, axes) {
        const target = element(id);
        const plot = new uPlot({
            width: Math.max(220, target.clientWidth), height: Math.max(130, target.clientHeight),
            legend: { show: false }, cursor: { show: false },
            scales: { x: { time: false }, temperature: { auto: true }, voltage: { auto: true }, current: { auto: true }, fineangle: { auto: true } },
            series: [{}, ...series],
            axes: [{
                stroke: "#9dafc4", font: "10px sans-serif", size: 32,
                values: (_plot, values) => values.map(value => `${Number(value.toFixed(1))}s`),
                grid: { stroke: "rgba(255,255,255,.065)" }, ticks: { stroke: "rgba(255,255,255,.08)" },
            }, ...axes],
        }, Array.from({ length: series.length + 1 }, () => []), target);
        const observer = new ResizeObserver(() => plot.setSize({
            width: Math.max(220, target.clientWidth), height: Math.max(130, target.clientHeight),
        }));
        observer.observe(target);
        return plot;
    }

    function initialize() {
        if (typeof uPlot !== "function") return;
        const ticks = element("dial-ticks");
        for (let degrees = 0; degrees < 360; degrees += 5) {
            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
            const radians = degrees * Math.PI / 180, inner = degrees % 30 === 0 ? 92 : 97;
            for (const [name, value] of Object.entries({
                x1: 120 + Math.sin(radians) * inner, y1: 120 - Math.cos(radians) * inner,
                x2: 120 + Math.sin(radians) * 102, y2: 120 - Math.cos(radians) * 102,
            })) line.setAttribute(name, value);
            line.setAttribute("class", degrees % 30 === 0 ? "dial-tick major" : "dial-tick");
            ticks.appendChild(line);
        }
        requestAnimationFrame(() => {
            temperaturePlot = createPlot("temperature-plot", [
                { label: "Temperature (°C)", scale: "temperature", stroke: "#baff3f", width: 1.8, points: { show: false } },
            ], [axis("temperature", 3, 1)]);
            powerPlot = createPlot("power-plot", [
                { label: "Voltage (V)", scale: "voltage", stroke: "#3ebbff", width: 1.8, points: { show: false } },
                { label: "Current (A)", scale: "current", stroke: "#ffc06b", width: 1.8, points: { show: false } },
            ], [axis("voltage", 3, 1), axis("current", 1, 2)]);
            fineAnglePlot = createPlot("fineangle-plot", [
                { label: "Fine angle (rad)", scale: "fineangle", stroke: "#3ebbff", width: 1.8, points: { show: false } },
            ], [{ ...axis("fineangle", 3, 2), label: "rad", size: 65 }]);
            ready = true;
            window.setInterval(() => {
                if (dirtyTemperature) { temperaturePlot.setData(temperatureData); dirtyTemperature = false; }
                if (dirtyPower) { powerPlot.setData(powerData); dirtyPower = false; }
                if (dirtyFineAngle) { fineAnglePlot.setData(fineAngleData); dirtyFineAngle = false; }
                refreshStates();
            }, 100);
        });
    }

    window.aceDashboard = { start, pause, handleMessage, get ready() { return ready; } };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
    else initialize();
})();
