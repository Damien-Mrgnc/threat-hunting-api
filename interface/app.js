document.addEventListener('DOMContentLoaded', () => {
    // --- State & Config ---
    const state = {
        apiBase: '/api', // Relative path via Nginx
        token: localStorage.getItem('access_token') || null
    };

    // --- UI Elements ---
    const els = {
        apiUrl: document.getElementById('api-url'),
        apiStatus: document.getElementById('api-status'),
        navBtns: document.querySelectorAll('.nav-item'), // Changed selector class
        panels: document.querySelectorAll('.panel'),     // Changed selector class

        // Workload 1
        btnSearch: document.getElementById('btn-search'),
        w1Results: document.getElementById('w1-results'),
        w1Inputs: {
            srcip: document.getElementById('w1-srcip'),
            limit: document.getElementById('w1-limit'),
            proto: document.getElementById('w1-proto')
        },

        // Workload 2
        btnStats: document.getElementById('btn-stats'),
        w2Results: document.getElementById('w2-results'),
        w2Inputs: {
            hours: document.getElementById('w2-hours')
        },

        // Workload 3
        btnTop: document.getElementById('btn-top'),
        w3Results: document.getElementById('w3-results'),
        w3Inputs: {
            limit: document.getElementById('w3-limit')
        },

        // Workload 4
        btnReport: document.getElementById('btn-report'),
        btnRefreshJobs: document.getElementById('btn-refresh-jobs'),
        w4Results: document.getElementById('jobs-table').querySelector('tbody'),
        w4Inputs: {
            year: document.getElementById('w4-year'),
            month: document.getElementById('w4-month')
        },

        // Visualizer
        vizContent: document.getElementById('viz-content'),
        navViz: document.getElementById('nav-viz'),

        // Auth
        loginModal: document.getElementById('login-modal'),
        loginForm: document.getElementById('login-form'),
        loginError: document.getElementById('login-error'),
        btnLogout: document.getElementById('btn-logout')
    };

    // --- Event Listeners ---

    // Config
    els.apiUrl.addEventListener('change', (e) => {
        state.apiBase = e.target.value.replace(/\/$/, '');
        checkHealth();
    });

    // Navigation
    els.navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Update buttons
            els.navBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update panels
            const targetId = btn.dataset.target;
            els.panels.forEach(p => {
                p.classList.remove('active');
                if (p.id === targetId) p.classList.add('active');
            });
        });
    });

    // Actions
    els.btnSearch.addEventListener('click', runWorkload1);
    els.btnStats.addEventListener('click', runWorkload2);
    els.btnTop.addEventListener('click', runWorkload3);
    els.btnReport.addEventListener('click', runWorkload4);
    els.btnRefreshJobs.addEventListener('click', refreshJobsList);

    // Auto-refresh when checking tab wl4
    els.navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.target === 'wl4') {
                refreshJobsList();
            }
        });
    });


    // Auth
    els.loginForm.addEventListener('submit', handleLogin);
    // Listener is handled dynamically in checkAuth to toggle Login/Logout behavior

    // Global Action for Visualization
    window.visualizeJob = async (path) => {
        // Switch tab
        els.navViz.style.display = 'block'; // Ensure visible
        els.navViz.click();

        els.vizContent.innerHTML = '> LOADING DATASET...';

        try {
            // Note: visualizeJob needs to authenticate too usually, IF the static file is protected. 
            // Currently static files in /downloads might be public? 
            // In main.py: app.mount("/downloads", ...). StaticFiles usually serves public unless protected by middleware.
            // But if path involves API call, it needs auth.
            // For now, let's assume we fetch JSON via authenticated fetch if needed, BUT previously it was just URL.
            // The previous code: `const res = await fetch(url);` 
            // We should use apiCall if it's an API, or fetch with headers.

            // Let's use apiCall but we need to handle full URL or path.
            // The path passed is like "/downloads/..."
            const data = await apiCall(path); // Update apiCall to handle this
            renderVisualization(data);
        } catch (err) {
            renderError(els.vizContent, "FAILED TO LOAD JSON: " + err.message);
        }
    };

    // Initial Health Check & Auth Check
    checkHealth();
    checkAuth();


    // --- Logic functions ---

    async function checkHealth() {
        els.apiStatus.innerHTML = 'ESTABLISHING...';
        const dot = document.querySelector('.status-dot');
        dot.className = 'status-dot';

        try {
            const res = await fetch(`${state.apiBase}/health`);
            if (res.ok) {
                els.apiStatus.textContent = 'SYSTEM ONLINE';
                dot.classList.add('active');
            } else {
                throw new Error('Status not OK');
            }
        } catch (err) {
            els.apiStatus.textContent = 'CONNECTION REFUSED';
            dot.classList.add('error');
            console.error(err);
        }
    }

    async function runWorkload1() {
        setLoading(els.w1Results);
        const isAsync = document.getElementById('w1-async').checked;

        const params = new URLSearchParams({
            srcip: els.w1Inputs.srcip.value,
            limit: els.w1Inputs.limit.value,
        });
        if (els.w1Inputs.proto.value) params.append('proto', els.w1Inputs.proto.value);
        if (isAsync) params.append('background', 'true');

        try {
            const data = await apiCall(`/events/search?${params.toString()}`);

            if (isAsync && data.job_id) {
                // Handle Async Response
                els.w1Results.innerHTML = `
                    <div style="padding: 20px; color: var(--accent);">
                        > JOB STARTED: ${data.job_id}<br>
                        > STATUS URL: ${data.status_url}<br><br>
                        <button class="run-btn" onclick="document.querySelector('[data-target=wl4]').click()">Go to JOBS & VISUALIZER</button>
                    </div>
                `;
            } else if (data.items && data.items.length > 0) {
                renderTable(els.w1Results, data.items, ['ts', 'srcip', 'dstip', 'proto', 'service', 'attack_cat', 'label']);
            } else {
                renderEmpty(els.w1Results, '> QUERY RETURNED 0 RECORDS');
            }
        } catch (err) {
            renderError(els.w1Results, err.message);
        }
    }

    async function runWorkload2() {
        setLoading(els.w2Results);
        const params = new URLSearchParams({
            hours: els.w2Inputs.hours.value,
        });

        try {
            const data = await apiCall(`/events/stats/bytes-by-proto?${params.toString()}`);
            if (data.items && data.items.length > 0) {
                renderBarChart(els.w2Results, data.items, 'proto', 'total_sbytes');
            } else {
                renderEmpty(els.w2Results, '> NO TELEMETRY DATA');
            }
        } catch (err) {
            renderError(els.w2Results, err.message);
        }
    }

    async function runWorkload3() {
        setLoading(els.w3Results);
        const params = new URLSearchParams({
            limit: els.w3Inputs.limit.value,
        });

        try {
            const data = await apiCall(`/events/top/attack-categories?${params.toString()}`);
            if (data.items && data.items.length > 0) {
                renderTable(els.w3Results, data.items, ['attack_cat', 'cnt']);
            } else {
                renderEmpty(els.w3Results, '> NO THREAT VECTORS IDENTIFIED');
            }
        } catch (err) {
            renderError(els.w3Results, err.message);
        }
    }

    async function runWorkload4() {
        const year = els.w4Inputs.year.value;
        const month = els.w4Inputs.month.value;

        try {
            // Need to use POST method helper
            const url = `${state.apiBase}/reports/malicious-events?year=${year}&month=${month}`;

            const headers = {};
            if (state.token) headers['Authorization'] = `Bearer ${state.token}`;

            const res = await fetch(url, { method: 'POST', headers });

            if (!res.ok) {
                const txt = await res.text();
                throw new Error(`API Error ${res.status}: ${txt}`);
            }
            const data = await res.json();

            // alert(`Job Started: ${data.job_id}`);
            refreshJobsList();

        } catch (err) {
            console.error(err);
            // Quick error display in table
            els.w4Results.innerHTML = `<tr><td colspan="4" style="color:red">ERROR: ${err.message}</td></tr>`;
        }
    }

    async function refreshJobsList() {
        try {
            const jobs = await apiCall(`/jobs/?limit=20`);

            if (!jobs || jobs.length === 0) {
                els.w4Results.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px;">> No jobs recorded.</td></tr>`;
                return;
            }

            els.w4Results.innerHTML = '';
            jobs.forEach(job => {
                const tr = document.createElement('tr');

                // Colorize status
                let statusColor = '#666';
                if (job.status === 'completed') statusColor = 'var(--accent)'; // Green
                if (job.status === 'processing') statusColor = 'orange';
                if (job.status === 'failed') statusColor = 'var(--alert)'; // Red

                // Format link
                let resultHtml = '<span style="color:#444">PENDING...</span>';
                if (job.status === 'completed' && job.result_path) {
                    // Check if JSON for Visualizer
                    if (job.result_path.endsWith('.json')) {
                        resultHtml = `
                            <button class="run-btn" style="width:auto; padding:0 8px; font-size:10px;" onclick="visualizeJob('${job.result_path}')">VISUALIZE</button>
                            <a href="${state.apiBase}${job.result_path}" target="_blank" style="margin-left:5px; color:#666; font-size:10px;">(JSON)</a>
                        `;
                    } else {
                        // Legacy TXT download
                        resultHtml = `<a href="${state.apiBase}${job.result_path}" target="_blank" style="color:var(--accent); text-decoration:none;">DOWNLOAD_REPORT</a>`;
                    }
                }
                if (job.status === 'failed') {
                    resultHtml = `<span style="color:var(--alert)">${job.error_message || 'Unknown Error'}</span>`;
                }

                tr.innerHTML = `
                    <td style="font-family:monospace; font-size:10px;">${job.job_id.substring(0, 8)}...</td>
                    <td>${new Date(job.submitted_at).toLocaleTimeString()}</td>
                    <td style="color:${statusColor}; font-weight:bold;">${job.status.toUpperCase()}</td>
                    <td>${resultHtml}</td>
                `;
                els.w4Results.appendChild(tr);
            });
        } catch (err) {
            console.error(err);
            els.w4Results.innerHTML = `<tr><td colspan="4" style="color:red">Connection Error: ${err.message}</td></tr>`;
        }
    }

    function checkAuth() {
        if (!state.token) {
            showLogin(true);
            if (els.btnLogout) {
                els.btnLogout.innerText = "LOGIN";
                els.btnLogout.style.background = "var(--accent)"; // Green
                els.btnLogout.style.color = "#000"; // Black text on green
                els.btnLogout.onclick = () => showLogin(true); // Override logout listener for login
            }
        } else {
            showLogin(false);
            if (els.btnLogout) {
                els.btnLogout.innerText = "LOGOUT";
                els.btnLogout.style.background = "var(--alert)"; // Red
                els.btnLogout.onclick = handleLogout; // Restore logout listener
            }
        }
    }

    function handleLogout() {
        state.token = null;
        localStorage.removeItem('access_token');
        window.location.reload();
    }

    function showLogin(show) {
        if (show) {
            els.loginModal.classList.add('active');
        } else {
            els.loginModal.classList.remove('active');
        }
    }

    async function handleLogin(e) {
        e.preventDefault();
        els.loginError.innerText = '> AUTHENTICATING...';

        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;

        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);

            const res = await fetch(`${state.apiBase}/auth/token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData
            });

            if (!res.ok) throw new Error("Invalid credentials");

            const data = await res.json();
            state.token = data.access_token;
            localStorage.setItem('access_token', state.token);

            els.loginError.innerText = '';
            showLogin(false);

            // Update UI state (Button -> Logout)
            checkAuth();

            // Re-check system health
            checkHealth();

        } catch (err) {
            els.loginError.innerText = '> ACCESS DENIED';
        }
    }

    // --- Helpers ---

    async function apiCall(path) {
        const url = `${state.apiBase}${path}`;

        const headers = {};
        if (state.token) {
            headers['Authorization'] = `Bearer ${state.token}`;
        }

        const res = await fetch(url, { headers });

        if (res.status === 401) {
            // Token expired or invalid
            state.token = null;
            localStorage.removeItem('access_token');
            showLogin(true);
            throw new Error("Authentication required");
        }

        if (!res.ok) {
            const txt = await res.text();
            throw new Error(`API Error ${res.status}: ${txt}`);
        }
        return res.json();
    }

    function setLoading(container) {
        container.innerHTML = '<span class="console-text">> PENDING EXECUTION...</span>';
    }

    function renderEmpty(container, msg) {
        container.innerHTML = `<span class="console-text">${msg}</span>`;
    }

    function renderError(container, msg) {
        container.innerHTML = `<span class="console-text" style="color: var(--alert)">> ERROR: ${msg}</span>`;
    }

    function renderTable(container, items, columns) {
        const table = document.createElement('table');

        // Header
        const thead = document.createElement('thead');
        const trHead = document.createElement('tr');
        columns.forEach(col => {
            const th = document.createElement('th');
            th.textContent = col.toUpperCase();
            trHead.appendChild(th);
        });
        thead.appendChild(trHead);
        table.appendChild(thead);

        // Body
        const tbody = document.createElement('tbody');
        items.forEach(item => {
            const tr = document.createElement('tr');
            columns.forEach(col => {
                const td = document.createElement('td');
                let val = item[col];

                // Formatting
                if (col === 'ts') val = new Date(val).toLocaleString();
                // Removing emoji/tag formatting, keeping it raw text

                td.innerText = val || 'N/A';
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);

        container.innerHTML = '';
        container.appendChild(table);
    }

    function renderBarChart(container, items, labelKey, valueKey) {
        container.innerHTML = '';

        // Find max for scaling
        const maxVal = Math.max(...items.map(i => i[valueKey]));

        items.forEach(item => {
            const row = document.createElement('div');
            row.className = 'bar-chart-row';

            const percent = (item[valueKey] / maxVal) * 100;

            row.innerHTML = `
                <div class="bar-label">${item[labelKey]}</div>
                <div class="bar-track">
                    <div class="bar-fill" style="width: ${percent}%"></div>
                </div>
                <div class="bar-value">${formatBytes(item[valueKey])}</div>
            `;
            container.appendChild(row);
        });
    }

    function formatBytes(bytes, decimals = 2) {
        if (!+bytes) return '0 B';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
    }

    function renderVisualization(json) {
        els.vizContent.innerHTML = '';

        // Meta Header
        const metaDiv = document.createElement('div');
        metaDiv.style.marginBottom = '20px';
        metaDiv.style.paddingBottom = '10px';
        metaDiv.style.borderBottom = '1px dashed #444';
        metaDiv.innerHTML = `
            <h3 style="color:var(--accent)">DATASET: ${json.meta?.type.toUpperCase()}</h3>
            <span style="color:#666; font-size:12px;">JOB_ID: ${json.meta?.job_id} | GENERATED: ${new Date(json.meta?.generated_at).toLocaleString()}</span>
        `;
        els.vizContent.appendChild(metaDiv);

        const type = json.meta?.type;
        const data = json.data;

        if (!data || data.length === 0) {
            renderEmpty(els.vizContent, '> DATASET IS EMPTY');
            return;
        }

        if (type === 'event_search') {
            renderTable(els.vizContent, data, ['ts', 'srcip', 'dstip', 'proto', 'service', 'attack_cat']);
        }
        else if (type === 'monthly_report') {
            // Summary style
            const summaryDiv = document.createElement('div');
            summaryDiv.innerHTML = '<h4>TOP MALICIOUS SOURCES (By Volume)</h4>';
            renderTable(summaryDiv, data, ['srcip', 'total_events', 'total_bytes']);
            els.vizContent.appendChild(summaryDiv);
        }
        else {
            // Fallback generic table
            const keys = Object.keys(data[0]);
            renderTable(els.vizContent, data, keys.slice(0, 6));
        }
    }
});
