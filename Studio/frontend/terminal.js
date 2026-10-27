/* AceLight commands only. No shell, Python evaluation or automatic retries. */
(() => {
    "use strict";

    window.createAceTerminal = ({ send, nodeId, selectNode, status }) => {
        const output = document.getElementById("terminal-output");
        const input = document.getElementById("terminal-input");
        const button = document.getElementById("terminal-send");
        const badge = document.getElementById("terminal-node");
        const suggestions = document.getElementById("terminal-suggestions");
        const names = new Map();
        const history = [];
        let historyIndex = 0;
        let draft = "";
        let connected = false;
        let pending = null;
        let sequence = 0;

        const statuses = {
            1: "OK", 2: "DATA_FOLLOWS", 3: "INVALID_PARAMETER",
            4: "INVALID_VALUE", 5: "READ_ONLY", 6: "WRITE_ONLY", 7: "NODE_BUSY",
        };

        function log(text, kind = "info") {
            const follow = output.scrollHeight - output.scrollTop - output.clientHeight < 40;
            const line = document.createElement("div");
            line.className = `terminal-line ${kind}`;
            const time = document.createElement("span");
            time.className = "terminal-time";
            time.textContent = new Date().toLocaleTimeString("en-GB", { hour12: false });
            line.append(time, document.createTextNode(text));
            output.appendChild(line);
            while (output.childElementCount > 500) output.firstElementChild.remove();
            if (follow) output.scrollTop = output.scrollHeight;
        }

        function refresh() {
            button.disabled = !connected || pending !== null;
            button.textContent = pending ? "…" : "Send";
            try { badge.textContent = `NODE ${nodeId()}`; }
            catch { badge.textContent = "CHECK NODE"; }
        }

        function finish() {
            if (pending) clearTimeout(pending.timer);
            pending = null;
            refresh();
        }

        function help() {
            log("read <parameter>\nwrite <parameter> <integer>\nnode <id>  ·  params [filter]\nhelp  ·  clear\nExamples:\n  read microstep\n  write microstep 256\n  write profile_velocity 500\n  write step_move -51200\nDecimal and hex values (0x100) accepted.\nWrites execute immediately on the selected node.");
        }

        function execute(text) {
            const parts = text.trim().split(/\s+/);
            const operation = parts[0].toLowerCase();
            if (operation === "clear" && parts.length === 1) {
                output.replaceChildren();
                return;
            }
            if (operation === "help" && parts.length === 1) { help(); return; }
            if (operation === "params" && parts.length <= 2) {
                const filter = (parts[1] || "").toLowerCase();
                const matches = [...names].filter(([name]) => name.includes(filter));
                log(matches.length ? matches.map(([name, type]) => `${name} (${type})`).join("\n") : "No matching parameters. Connect to the backend to load the parameter list.");
                return;
            }
            if (operation === "node" && parts.length === 2) {
                if (pending) throw new Error("Wait for the current command before changing node.");
                if (!/^\d+$/.test(parts[1])) throw new Error("Node ID must be an integer from 0 to 127.");
                selectNode(Number(parts[1]));
                refresh();
                log(`Selected node ${nodeId()}.`, "success");
                return;
            }
            if (!((operation === "read" && parts.length === 2) ||
                  (operation === "write" && parts.length === 3))) {
                throw new Error("Use read <parameter> or write <parameter> <integer>. Type help for examples.");
            }
            if (!connected) throw new Error("Backend disconnected. Reload to reconnect; commands are not queued.");
            if (pending) throw new Error("A command is still awaiting its reply.");
            const parameter = parts[1].toLowerCase();
            if (!names.has(parameter)) throw new Error(`Unknown parameter: ${parameter}. Type params for the available names.`);
            const command = { type: operation, node: nodeId(), param: parameter };
            if (operation === "write") {
                if (!/^[+-]?(?:\d+|0x[0-9a-f]+)$/i.test(parts[2])) {
                    throw new Error("Value must be an integer, e.g. 256, -1000 or 0x100.");
                }
                const token = parts[2];
                const sign = token.startsWith("-") ? -1 : 1;
                command.value = sign * Number(token.replace(/^[+-]/, ""));
                const type = names.get(parameter);
                const bits = Number(type.slice(1));
                const signed = type.startsWith("I");
                const min = signed ? -(2 ** (bits - 1)) : 0;
                const max = 2 ** (signed ? bits - 1 : bits) - 1;
                if (!Number.isSafeInteger(command.value) || command.value < min || command.value > max) {
                    throw new Error(`${parameter} is ${type}: allowed range ${min}…${max}.`);
                }
            }
            command.request_id = `terminal-${++sequence}`;
            log(`[node ${command.node}] > ${text}`, "command");
            const started = performance.now();
            pending = { ...command, started, timer: setTimeout(() => {
                log(`No reply for ${operation} ${parameter}. Outcome unknown; read back the value before retrying a write.`, "error");
                finish();
            }, 8000) };
            refresh();
            try {
                if (!send(command)) throw new Error("Command could not be sent.");
            } catch (error) {
                finish();
                throw error;
            }
        }

        document.getElementById("terminal-form").addEventListener("submit", event => {
            event.preventDefault();
            const text = input.value.trim();
            if (!text) return;
            if (history.at(-1) !== text) history.push(text);
            if (history.length > 100) history.shift();
            historyIndex = history.length;
            draft = "";
            try { execute(text); input.value = ""; }
            catch (error) { log(error.message, "error"); status(error.message); }
            input.focus();
        });
        input.addEventListener("keydown", event => {
            if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
            event.preventDefault();
            if (historyIndex === history.length) draft = input.value;
            historyIndex = Math.max(0, Math.min(history.length,
                historyIndex + (event.key === "ArrowUp" ? -1 : 1)));
            input.value = historyIndex === history.length ? draft : history[historyIndex];
            input.setSelectionRange(input.value.length, input.value.length);
        });
        document.getElementById("terminal-clear").addEventListener("click", () => output.replaceChildren());
        document.getElementById("node-id").addEventListener("input", refresh);

        log("AceLight terminal ready. Type help for commands.");
        refresh();

        return {
            setConnected(value) {
                connected = value;
                if (!value && pending) {
                    log(`Connection lost while awaiting ${pending.type} ${pending.param}. Outcome unknown; no command was retried.`, "error");
                    finish();
                }
                refresh();
            },
            handleMessage(message) {
                if (message.type === "hello") {
                    names.clear();
                    suggestions.replaceChildren();
                    for (const { name, type } of message.parameters || []) {
                        names.set(name, type);
                        for (const operation of ["read", "write"]) {
                            const option = document.createElement("option");
                            option.value = `${operation} ${name}`;
                            suggestions.appendChild(option);
                        }
                    }
                    connected = Boolean(message.acelight_connected);
                    log(connected ? `Connected · ${names.size} parameters available.` : "AceLight backend unavailable.");
                    refresh();
                    return;
                }
                if (!String(message.request_id || "").startsWith("terminal-")) return;
                const current = pending?.request_id === message.request_id;
                const elapsed = current ? ` · ${Math.round(performance.now() - pending.started)} ms` : " · late reply";
                if (message.type === "error") {
                    log(`[node ${message.node}] ${message.message}${elapsed}`, "error");
                } else if (["read_response", "write_response"].includes(message.type)) {
                    const code = Number(message.status);
                    const hex = `0x${code.toString(16).padStart(2, "0").toUpperCase()}`;
                    const read = message.type === "read_response";
                    const ok = read ? code === 2 : code === 1;
                    const value = read && message.value != null ? ` = ${message.value}` : "";
                    log(`[node ${message.node}] ${read ? "READ" : "WRITE"} ${message.param}${value}\n${statuses[code] || "UNKNOWN_STATUS"} (${hex})${elapsed}`, ok ? "success" : "error");
                } else return;
                if (current) finish();
            },
        };
    };
})();
