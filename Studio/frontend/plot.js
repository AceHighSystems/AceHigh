(() => {
    "use strict";

    const CHANNEL_COUNT = 14;
    const MAX_POINTS = 15000;
    const RENDER_INTERVAL_MS = 30;

    const scopes = new Map();
    let ready = false;

    function makeChannelPanel(grid, channelIndex) {
        const signal = `ch${channelIndex}`;

        const panel = document.createElement("div");
        panel.className = "scope-channel";

        const header = document.createElement("div");
        header.className = "scope-channel-header";

        const name = document.createElement("span");
        name.className = "scope-channel-name";
        name.textContent = signal;

        const value = document.createElement("span");
        value.className = "scope-channel-value";
        value.id = `scope-value-${signal}`;
        value.textContent = "--";

        const target = document.createElement("div");
        target.className = "scope-plot";
        target.id = `scope-plot-${signal}`;

        header.append(name, value);
        panel.append(header, target);
        grid.appendChild(panel);

        return { target, value };
    }

    function createPlot(channelIndex, panel) {
        const signal = `ch${channelIndex}`;
        const { target, value } = panel;

        const x = [];
        const y = [];

        // Preserve the existing axis layout; this affects labels only.
        const showXAxis = channelIndex >= 10;

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
                    stroke: "#baff3f",
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

    function pushSamples(signal, samples) {
        const state = scopes.get(signal);

        if (!state || samples.length === 0) {
            return;
        }

        for (let i = 0; i < samples.length; i++) {
            state.x.push(state.nextX++);
            state.y.push(samples[i]);
        }

        if (state.x.length > MAX_POINTS) {
            const remove = state.x.length - MAX_POINTS;

            state.x.splice(0, remove);
            state.y.splice(0, remove);
        }

        state.value.textContent =
            Number(samples[samples.length - 1]).toLocaleString();

        state.dirty = true;
    }

    function clear() {
        for (const state of scopes.values()) {
            state.x.length = 0;
            state.y.length = 0;
            state.nextX = 0;
            state.dirty = true;
            state.value.textContent = "--";
        }
    }

    function renderDirtyPlots() {
        for (const state of scopes.values()) {
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

        const panels = Array.from(
            { length: CHANNEL_COUNT },
            (_, channel) => makeChannelPanel(grid, channel)
        );

        // Allow the browser to calculate panel dimensions first.
        requestAnimationFrame(() => {
            panels.forEach((panel, channel) => {
                createPlot(channel, panel);
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