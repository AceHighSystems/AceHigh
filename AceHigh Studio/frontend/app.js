(() => {
    "use strict";

    function initialize() {
        const CHANNEL_COUNT = 14;
        const SAMPLE_RATE_HZ = 50;

        // Must match the backend packet format.
        // Increasing the channel count does not change the header size.
        //
        // Offset  Size  Field
        // 0       1     Packet type
        // 1       1     Node
        // 2       2     Signal ID
        // 4       4     Sample count
        // 8       4     Sequence
        // 12      ...   uint32 samples, little-endian
        const HEADER_BYTES = 12;
        const SAMPLE_BYTES = 4;

        const CHANNELS = Array.from(
            { length: CHANNEL_COUNT },
            (_, index) => `ch${index}`
        );

        // Must match backend/telemetry.py:
        // ch0=1, ch1=2, ... ch13=14.
        const SIGNAL_BY_ID = new Map(
            CHANNELS.map((signal, index) => [index + 1, signal])
        );

        const nodeInput = document.getElementById("node-id");
        const statusLine = document.getElementById("status-line");
        const connectionDot = document.getElementById("connection-dot");
        const connectionText = document.getElementById("connection-text");

        const protocol = location.protocol === "https:" ? "wss" : "ws";
        const ws = new WebSocket(`${protocol}://${location.host}/ws`);

        ws.binaryType = "arraybuffer";

        let subscribedCount = 0;
        let scopeRunning = false;
        let runId = 0;

        function nodeId() {
            const value = Number(nodeInput.value);
            if (!nodeInput.value.trim() || !Number.isInteger(value) || value < 0 || value > 127) {
                throw new Error("Node ID must be an integer from 0 to 127.");
            }
            return value;
        }

        function statusHex(status) {
            return `0x${Number(status)
                .toString(16)
                .padStart(2, "0")
                .toUpperCase()}`;
        }

        function send(object) {
            if (ws.readyState !== WebSocket.OPEN) {
                statusLine.textContent = "WebSocket is not connected.";
                return false;
            }

            ws.send(JSON.stringify(object));
            return true;
        }

        const terminal = window.createAceTerminal({
            send, nodeId,
            selectNode(value) {
                if (!Number.isInteger(value) || value < 0 || value > 127) {
                    throw new Error("Node ID must be an integer from 0 to 127.");
                }
                if (scopeRunning) throw new Error("Stop the scope before changing its node.");
                nodeInput.value = value;
            },
            status(text) { statusLine.textContent = text; },
        });

        ws.addEventListener("open", () => {
            connectionDot.classList.add("online");
            connectionText.textContent = "Backend connected";
        });

        ws.addEventListener("close", () => {
            window.aceDashboard?.pause("Disconnected");
            terminal.setConnected(false);
            nodeInput.disabled = false;
            connectionDot.classList.remove("online");
            connectionText.textContent = "Disconnected";

            scopeRunning = false;
            subscribedCount = 0;

            statusLine.textContent =
                "WebSocket disconnected. Reload to reconnect.";
        });

        ws.addEventListener("error", () => {
            statusLine.textContent =
                "WebSocket error. Check the backend and browser console.";
        });

        ws.addEventListener("message", (event) => {
            try {
                if (typeof event.data === "string") {
                    handleJson(JSON.parse(event.data));
                } else {
                    handleBinary(event.data);
                }
            } catch (error) {
                console.error(
                    "Failed to process WebSocket message:",
                    error
                );

                statusLine.textContent =
                    `Telemetry error: ${error.message}`;
            }
        });

        function handleJson(message) {
            terminal.handleMessage(message);
            if (["metric_sample", "metric_error"].includes(message.type)) {
                if (scopeRunning && message.run_id === runId && message.node === nodeId()) {
                    window.aceDashboard?.handleMessage(message);
                }
                return;
            }
            switch (message.type) {
                case "hello":
                    connectionText.textContent =
                        message.acelight_connected
                            ? "AceLight connected"
                            : "GUI connected / AceLight not loaded";
                    break;

                case "read_response":
                    if (
                        message.param === "voltage" &&
                        message.value != null
                    ) {
                        voltageValue.textContent =
                            `${(Number(message.value) / 1000).toFixed(3)} V`;
                    }

                    statusLine.textContent =
                        `READ ${message.param}: ` +
                        statusHex(message.status);
                    break;

                case "write_response":
                    statusLine.textContent =
                        `WRITE ${message.param}: ` +
                        statusHex(message.status);
                    break;

                case "subscribed":
                    if (!scopeRunning) {
                        break;
                    }

                    subscribedCount += 1;

                    if (subscribedCount >= CHANNEL_COUNT) {
                        statusLine.textContent =
                            `Streaming ch0-ch${CHANNEL_COUNT - 1} ` +
                            `@ ${SAMPLE_RATE_HZ} Hz/channel`;
                    } else {
                        statusLine.textContent =
                            `Starting raw scope ` +
                            `${subscribedCount}/${CHANNEL_COUNT}...`;
                    }
                    break;

                case "unsubscribed":
                    break;

                case "error":
                    statusLine.textContent =
                        `Error: ${message.message}`;

                    console.error("Backend error:", message);
                    break;
            }
        }

        function handleBinary(buffer) {
            if (!(buffer instanceof ArrayBuffer)) {
                console.warn(
                    "Unexpected telemetry data type:",
                    buffer
                );
                return;
            }

            if (buffer.byteLength < HEADER_BYTES) {
                console.warn(
                    "Telemetry packet is shorter than its header."
                );
                return;
            }

            const view = new DataView(buffer);

            const packetType = view.getUint8(0);
            const node = view.getUint8(1);
            const signalId = view.getUint16(2, true);
            const count = view.getUint32(4, true);
            const sequence = view.getUint32(8, true);

            if (packetType !== 1) {
                return;
            }

            const signal = SIGNAL_BY_ID.get(signalId);

            if (!signal) {
                console.warn(
                    "Unknown telemetry signal ID:",
                    signalId
                );
                return;
            }

            const expectedBytes =
                HEADER_BYTES + count * SAMPLE_BYTES;

            if (buffer.byteLength !== expectedBytes) {
                const detail =
                    `${buffer.byteLength} != ${expectedBytes}`;

                console.warn(
                    `Bad telemetry packet length for ${signal}: ${detail}`,
                    { node, signalId, count, sequence }
                );

                statusLine.textContent =
                    `Packet format mismatch for ${signal}: ${detail}. ` +
                    "Check backend header size.";

                return;
            }

            if (!scopeRunning || !window.acePlot?.ready) {
                return;
            }

            // Explicit little-endian decoding avoids alignment problems.
            const samples = new Uint32Array(count);

            for (let i = 0; i < count; i++) {
                samples[i] = view.getUint32(
                    HEADER_BYTES + i * SAMPLE_BYTES,
                    true
                );
            }

            window.acePlot.pushSamples(signal, samples);
        }
        

        document.getElementById("start-scope")
            .addEventListener("click", () => {
                if (scopeRunning) {
                    return;
                }

                if (ws.readyState !== WebSocket.OPEN) {
                    statusLine.textContent =
                        "WebSocket is not connected.";
                    return;
                }

                if (!window.acePlot?.ready) {
                    statusLine.textContent =
                        "Plots are not ready. " +
                        "Check that uPlot and plot.js loaded.";
                    return;
                }

                if (!window.aceDashboard?.ready) {
                    statusLine.textContent = "Dashboard plots are not ready. Check dashboard.js and uPlot.";
                    return;
                }

                if (!nodeInput.reportValidity() || !nodeInput.value.trim()) return;
                window.acePlot.clear();
                window.aceDashboard.start();
                runId += 1;

                subscribedCount = 0;
                scopeRunning = true;
                nodeInput.disabled = true;

                statusLine.textContent = "Starting raw scope...";

                const node = nodeId();

                for (const signal of CHANNELS) {
                    send({
                        type: "subscribe",
                        node,
                        signal,
                        rate_hz: SAMPLE_RATE_HZ,
                    });
                }
                send({ type: "metrics_start", node, run_id: runId });
            });

        document.getElementById("stop-scope")
            .addEventListener("click", () => {
                if (!scopeRunning) {
                    return;
                }

                for (const signal of CHANNELS) {
                    send({
                        type: "unsubscribe",
                        signal,
                    });
                }
                send({ type: "metrics_stop" });
                window.aceDashboard.pause("Paused");

                scopeRunning = false;
                nodeInput.disabled = false;
                subscribedCount = 0;

                statusLine.textContent = "Raw scope stopped";
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
