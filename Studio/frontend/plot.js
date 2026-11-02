(() => {
    "use strict";

    const CHANNEL_COUNT = 14;
    const MAX_POINTS = 15000;
    const RENDER_INTERVAL_MS = 30;
    const WINDOW_SECONDS = 300;

    // Firmware I32 fine_angle keeps the existing fixed-point representation.
    // Change this divisor if the firmware's fixed-point format changes.
    const FINE_ANGLE_UNITS_PER_RADIAN = 1_000_000;
    // Entry order determines the vertical order of the parameter plots.
    const PARAMETERS = new Map([
        ["angle", { title: "Angle", unit: "deg", wireUnit: "mdeg", divisor: 1000,
            min: -2147483648, max: 2147483647, color: "#e62525" }],
        ["fine_angle", { title: "Fine angle", unit: "rad", wireUnit: "urad",
            divisor: FINE_ANGLE_UNITS_PER_RADIAN, min: -2147483648,
            max: 2147483647, color: "#3ebbff" }],
        ["sector", { title: "Sector", unit: "count", wireUnit: "count", divisor: 1,
            min: 0, max: 255, color: "#baff3f" }],
    ]);

    const scopes = new Map();
    let ready = false;

    function makeChannelPanel(grid, signal) {
        const parameter = PARAMETERS.get(signal);
        const panel = document.createElement("div");
        panel.className = parameter ? "scope-channel parameter-scope" : "scope-channel";
        panel.dataset.signal = signal;

        const header = document.createElement("div");
        header.className = "scope-channel-header";

        const name = document.createElement("span");
        name.className = "scope-channel-name";
        name.textContent = parameter ? `${parameter.title} (${parameter.unit})` : signal;

        const value = document.createElement("span");
        value.className = "scope-channel-value";
        value.id = `scope-value-${signal}`;
        value.textContent = "--";

        const target = document.createElement("div");
        target.className = "scope-plot";
        target.id = `scope-plot-${signal}`;
        target.setAttribute("aria-label", parameter
            ? `${parameter.title} in ${parameter.unit} versus elapsed seconds`
            : `${signal} versus sample index`);

        let status = null;
        if (parameter) {
            status = document.createElement("span");
            status.className = "metric-state";
            status.textContent = "Ready";
            status.id = `scope-state-${signal}`;
        }

        header.append(name, value);
        if (status) header.appendChild(status);
        panel.append(header, target);
        grid.appendChild(panel);

        return { panel, target, value, status };
    }

    function createPlot(signal, panel, channelIndex = 0) {
        const parameter = PARAMETERS.get(signal);
        const { target, value } = panel;

        const x = [];
        const y = [];

        // Preserve the existing axis layout; this affects labels only.
        const showXAxis = Boolean(parameter) || channelIndex >= 10;

        const options = {
            width: Math.max(200, target.clientWidth),
            height: Math.max(80, target.clientHeight),

            legend: {
                show: false,
            },

            cursor: {
                show: false,
            },

            scales: {
                x: {
                    time: false,
                },
                y: {
                    auto: true,
                },
            },

            series: [
                {},
                {
                    label: signal,
                    stroke: parameter?.color || (["ch0", "ch7"].includes(signal) ? "#ff69b4" : "#baff3f"),
                    width: 1.25,
                },
            ],

            axes: [
                {
                    show: showXAxis,
                    stroke: "#8295ad",
                    size: showXAxis ? 24 : 0,
                    grid: {
                        stroke: "rgba(255,255,255,0.065)",
                    },
                    ticks: {
                        stroke: "rgba(255,255,255,0.08)",
                    },
                    font: "9px sans-serif",
                },
                {
                    stroke: "#8295ad",
                    size: 54,
                    grid: {
                        stroke: "rgba(255,255,255,0.065)",
                    },
                    ticks: {
                        stroke: "rgba(255,255,255,0.08)",
                    },
                    font: "9px sans-serif",
                },
            ],
        };

        if (parameter) {
            options.series[1].points = { show: false };
            options.axes[0].values = (_plot, values) => values.map(value => `${Number(value.toFixed(1))}s`);
            options.axes[1].size = 66;
            // Angle and fine_angle use the same automatic Y range and numeric
            // ticks as the raw channels, so small position noise stays visible.
            if (signal === "sector") {
                options.axes[1].incrs = [1, 2, 5, 10, 20, 50, 100, 200];
                options.axes[1].values = (_plot, values) => values.map(value => String(Math.round(value)));
                options.series[1].paths = uPlot.paths.stepped({ align: 1 });
            }
        }

        const plot = new uPlot(options, [x, y], target);

        const state = {
            signal,
            target,
            value,
            plot,
            x,
            y,
            nextX: 0,
            dirty: false,
            panel: panel.panel,
            status: panel.status,
            seen: null,
            active: false,
        };

        scopes.set(signal, state);

        const resizeObserver = new ResizeObserver(() => {
            const width = Math.max(200, target.clientWidth);
            const height = Math.max(80, target.clientHeight);

            if (plot.width !== width || plot.height !== height) {
                plot.setSize({ width, height });
            }
        });

        resizeObserver.observe(target);
        state.resizeObserver = resizeObserver;
    }

    function pushSamples(signal, samples, elapsedSeconds = null) {
        const state = scopes.get(signal);

        if (!state || samples.length === 0) {
            return;
        }

        for (let i = 0; i < samples.length; i++) {
            state.x.push(elapsedSeconds === null ? state.nextX++ : elapsedSeconds);
            state.y.push(samples[i]);
        }

        if (state.x.length > MAX_POINTS) {
            const remove = state.x.length - MAX_POINTS;

            state.x.splice(0, remove);
            state.y.splice(0, remove);
        }

        if (elapsedSeconds !== null) {
            let remove = 0;
            while (remove < state.x.length && state.x[remove] < elapsedSeconds - WINDOW_SECONDS) remove++;
            if (remove) { state.x.splice(0, remove); state.y.splice(0, remove); }
        }

        const latest = Number(samples[samples.length - 1]);
        state.value.textContent = signal === "fine_angle"
            ? `${latest.toFixed(6)} rad`
            : `${latest.toLocaleString()}${signal === "angle" ? "°" : ""}`;

        state.dirty = true;
    }

    function setState(state, label) {
        state.status.textContent = label;
        state.panel.dataset.state = label.toLowerCase();
    }

    function handleParameterMessage(message) {
        const definition = PARAMETERS.get(message.signal);
        const state = scopes.get(message.signal);
        if (!definition || !state?.active || message.source !== "ranger" ||
            message.parameter !== message.signal || message.unit !== definition.wireUnit) return;
        if (message.type === "metric_error") {
            setState(state, "Unavailable");
            state.status.title = message.message;
            return;
        }
        const raw = message.value, seconds = message.elapsed_s;
        if (message.type !== "metric_sample" || !Number.isSafeInteger(raw) ||
            raw < definition.min || raw > definition.max ||
            !Number.isFinite(seconds) || seconds < 0) return;

        const plottedValue = raw / definition.divisor;
        pushSamples(message.signal, [plottedValue], seconds);
        state.seen = performance.now();
        state.status.title = "";
        setState(state, "Live");
        // One event per validated firmware read, keeping the raw integer for
        // export alongside the plotted value and its physical unit.
        window.dispatchEvent(new CustomEvent("ace-parameter-sample", {
            detail: { parameter: message.signal, value: raw, plottedValue, unit: definition.unit },
        }));
    }

    function pause(label = "Paused") {
        for (const state of scopes.values()) {
            if (!state.status) continue;
            state.active = false;
            setState(state, label);
        }
    }

    function clear() {
        for (const state of scopes.values()) {
            state.x.length = 0;
            state.y.length = 0;
            state.nextX = 0;
            state.dirty = true;
            state.value.textContent = "--";
            if (state.status) {
                state.active = true;
                state.seen = null;
                state.status.title = "";
                setState(state, "Waiting");
            }
        }
    }

    function renderDirtyPlots() {
        for (const state of scopes.values()) {
            if (state.active && state.status?.textContent === "Live" &&
                performance.now() - state.seen > 3000) setState(state, "Stale");
            if (!state.dirty) {
                continue;
            }

            state.plot.setData([state.x, state.y]);
            state.dirty = false;
        }
    }

    window.acePlot = {
        pushSamples,
        clear,
        handleParameterMessage,
        pause,

        get ready() {
            return ready;
        },
    };

    function initialize() {
        const grid = document.getElementById("scope-grid");

        if (!grid) {
            console.error("plot.js: missing #scope-grid element.");
            return;
        }

        if (typeof uPlot !== "function") {
            console.error("plot.js: load uPlot before plot.js.");
            return;
        }

        grid.innerHTML = "";
        const parameterGrid = document.getElementById("parameter-scope-grid");
        if (!parameterGrid) {
            console.error("plot.js: missing #parameter-scope-grid element.");
            return;
        }
        parameterGrid.innerHTML = "";
        const parameterPanels = [...PARAMETERS.keys()].map(signal =>
            [signal, makeChannelPanel(parameterGrid, signal)]);

        const panels = Array.from(
            { length: CHANNEL_COUNT },
            (_, channel) => makeChannelPanel(grid, `ch${channel}`)
        );

        // Allow the browser to calculate panel dimensions first.
        requestAnimationFrame(() => {
            parameterPanels.forEach(([signal, panel]) => createPlot(signal, panel));
            panels.forEach((panel, channel) => {
                createPlot(`ch${channel}`, panel, channel);
            });

            ready = true;

            window.setInterval(
                renderDirtyPlots,
                RENDER_INTERVAL_MS
            );
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initialize,
            { once: true }
        );
    } else {
        initialize();
    }
})();
