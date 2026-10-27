/* AceHigh Studio CSV export.
 * Captures the latest 20000 received samples per signal, ch0–ch13 and angle.
 * Load after plot.js and app.js.
 *
 * Timestamps describe browser receipt of a WebSocket batch,
 * not the actual sensor conversion time.
 */

(() => {
    "use strict";

    const CHANNELS = [...Array.from(
        { length: 14 },
        (_, index) => `ch${index}`
    ), "angle"];

    // CSV history is independent of the plots' display history.
    const MAX_POINTS = 20000;

    const plot = window.acePlot;
    const actions = document.querySelector(".scope-actions");

    if (
        !plot ||
        !actions ||
        document.getElementById("export-csv")
    ) {
        return;
    }

    const buffers = new Map(
        CHANNELS.map(channel => [channel, []])
    );

    const counters = new Map(
        CHANNELS.map(channel => [channel, 0])
    );

    let firstReceivedMs = null;

    // Add the export button beside Run and Stop.
    const exportButton = document.createElement("button");

    exportButton.id = "export-csv";
    exportButton.className = "secondary";
    exportButton.textContent = "Export CSV";
    exportButton.title =
        "Download ch0–ch13 and angle, up to 20000 samples per signal";

    exportButton.disabled = true;

    actions.appendChild(exportButton);

    function capture(signal, samples) {
        const buffer = buffers.get(signal);

        if (!buffer || !samples.length) {
            return;
        }

        const receivedMs =
            performance.timeOrigin + performance.now();

        if (firstReceivedMs === null) {
            firstReceivedMs = receivedMs;
        }

        let nextIndex = counters.get(signal);

        for (let i = 0; i < samples.length; ++i) {
            buffer.push({
                index: nextIndex++,
                value: Number(samples[i]),
                receivedMs,
            });
        }

        counters.set(signal, nextIndex);

        if (buffer.length > MAX_POINTS) {
            buffer.splice(
                0,
                buffer.length - MAX_POINTS
            );
        }

        exportButton.disabled = false;

    }

    // Preserve the existing raw plotting function and capture its input.
    const originalPush = plot.pushSamples;

    plot.pushSamples = function (signal, samples, ...rest) {
        const result = originalPush.call(this, signal, samples, ...rest);
        capture(signal, samples);
        return result;
    };

    // Capture only validated, active-run firmware angle samples. Export the
    // signed parameter unchanged, rather than the displayed radians or dial.
    window.addEventListener("ace-parameter-sample", event => {
        const sample = event.detail;
        if (sample?.parameter === "angle" && Number.isSafeInteger(sample.value)) {
            capture("angle", [sample.value]);
        }
    });

    // Clear the CSV buffers whenever the existing scope is cleared.
    const originalClear = plot.clear;

    plot.clear = function (...args) {
        const result = originalClear.apply(this, args);

        for (const channel of CHANNELS) {
            buffers.get(channel).length = 0;
            counters.set(channel, 0);
        }

        firstReceivedMs = null;
        exportButton.disabled = true;

        return result;
    };

    exportButton.addEventListener("click", () => {
        const rows = [
            "channel,sample_index,raw_value," +
            "host_receive_elapsed_s,host_receive_utc",
        ];

        for (const channel of CHANNELS) {
            for (const sample of buffers.get(channel)) {
                const elapsedSeconds =
                    (sample.receivedMs - firstReceivedMs) / 1000;

                rows.push([
                    channel,
                    sample.index,
                    sample.value,
                    elapsedSeconds.toFixed(6),
                    new Date(sample.receivedMs).toISOString(),
                ].join(","));
            }
        }

        if (rows.length === 1) {
            return;
        }

        const blob = new Blob(
            [rows.join("\r\n") + "\r\n"],
            { type: "text/csv;charset=utf-8" }
        );

        const url = URL.createObjectURL(blob);

        const timestamp = new Date()
            .toISOString()
            .replace(/[:.]/g, "-");

        const link = document.createElement("a");

        link.href = url;
        link.download = `AceHigh-PCAP-A-${timestamp}.csv`;

        document.body.appendChild(link);
        link.click();
        link.remove();

        setTimeout(() => {
            URL.revokeObjectURL(url);
        }, 10000);

        const statusLine =
            document.getElementById("status-line");

        if (statusLine) {
            statusLine.textContent =
                `Exported ${rows.length - 1} samples from ch0–ch13 and angle.`;
        }
    });
})();
