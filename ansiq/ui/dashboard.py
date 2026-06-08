"""AnsiQ Dashboard — Beautiful Streamlit UI for Monitoring & Control.

Design inspiration:
- 🎨 21st.dev: Glassmorphism cards, clean layouts, frosted glass effects
- 🏗️ shadcn/ui: Consistent component design system, typography, spacing
- ✨ motionsite.ai: Smooth animations, 3D hover effects, particle backgrounds

Run: streamlit run ansiq/ui/dashboard.py
"""

from __future__ import annotations

# ── Streamlit is optional — safe import ──
try:
    import streamlit as st

    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

from ansiq.ui.components import (
    AgentTimeline,
    CostChart,
    DAGVisualizer,
    MetricCard,
    StatusCard,
    ToolBrowser,
    get_base_styles,
)


class AnsiqDashboard:
    """Main Streamlit Dashboard for AnsiQ monitoring and control.

    Features:
    - Real-time agent execution monitoring
    - DAG visualization with animated nodes
    - Swarm intelligence voting results
    - Tool registry browser
    - Cost & usage analytics
    - 3D animated UI effects
    """

    def __init__(self):
        self.title = "AnsiQ Control Center"
        self.page_title = "AnsiQ — Intelligent Agent Orchestration"
        self._check_streamlit()

    def _check_streamlit(self) -> None:
        """Check if Streamlit is available."""
        if not STREAMLIT_AVAILABLE:
            print(
                "Streamlit is required for the dashboard.\n"
                "Install: pip install streamlit\n"
                "Run: streamlit run ansiq/ui/dashboard.py"
            )

    def run(self) -> None:
        """Launch the Streamlit dashboard."""
        if not STREAMLIT_AVAILABLE:
            self._check_streamlit()
            return

        # ── Page Config ──
        st.set_page_config(
            page_title=self.page_title,
            page_icon="🧠",
            layout="wide",
            initial_sidebar_state="collapsed",
        )

        # ── Inject Base Styles ──
        st.markdown(get_base_styles(), unsafe_allow_html=True)

        # ── Particle Background ──
        st.markdown('<div class="particle-bg"></div>', unsafe_allow_html=True)

        # ── Header ──
        self._render_header()

        # ── Top Stats Row ──
        self._render_stats_row()

        # ── Main Content Tabs ──
        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["🚀 Execution", "🔀 DAG Flow", "🐝 Swarm", "🔧 Tools", "📊 Analytics"]
        )

        with tab1:
            self._render_execution_tab()

        with tab2:
            self._render_dag_tab()

        with tab3:
            self._render_swarm_tab()

        with tab4:
            self._render_tools_tab()

        with tab5:
            self._render_analytics_tab()

        # ── Footer ──
        self._render_footer()

    def _render_header(self) -> None:
        """Render the dashboard header with animated title."""
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(
                """
            <div class="animate-slide-up">
                <h1 style="font-size: 2.5rem; font-weight: 800; margin: 0;">
                    <span class="gradient-text">AnsiQ</span>
                    <span style="color: rgba(255,255,255,0.8);">Control Center</span>
                </h1>
                <p style="color: rgba(255,255,255,0.4); font-size: 1rem; margin-top: 4px;">
                    Intelligent Agent Orchestration Framework — Real-time Monitoring
                </p>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with col2:
            st.markdown(
                """
            <div class="glass-card animate-scale-in" style="text-align: center; padding: 12px;">
                <div class="spinner" style="margin: 0 auto 8px;"></div>
                <div style="font-size: 0.8rem; color: rgba(255,255,255,0.5);">System Active</div>
                <div style="font-size: 0.7rem; color: rgba(255,255,255,0.3);">v0.2.0</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    def _render_stats_row(self) -> None:
        """Render top statistics row with animated metric cards."""
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown(
                MetricCard(label="Active Agents", value="4", change="+2 today", icon="🤖").render(),
                unsafe_allow_html=True,
            )

        with col2:
            st.markdown(
                MetricCard(
                    label="Tasks Completed", value="127", change="+12 today", icon="✅"
                ).render(),
                unsafe_allow_html=True,
            )

        with col3:
            st.markdown(
                MetricCard(
                    label="Avg Response",
                    value="1.2s",
                    change="-0.3s faster",
                    change_type="positive",
                    icon="⚡",
                ).render(),
                unsafe_allow_html=True,
            )

        with col4:
            st.markdown(
                MetricCard(
                    label="Tokens Used", value="45.2K", change="~$0.89 cost", icon="💰"
                ).render(),
                unsafe_allow_html=True,
            )

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    def _render_execution_tab(self) -> None:
        """Render the execution monitoring tab."""
        col1, col2 = st.columns([2, 1])

        with col1:
            # Agent Status Cards
            st.markdown(
                '<div class="section-title"><span class="icon">🤖</span> Agent Status</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="stats-grid">', unsafe_allow_html=True)

            agents_data = [
                ("Researcher", "Researching...", "running", "Searching web for AI trends", "🔬"),
                ("Analyst", "Analysis complete", "completed", "Processed 3 data sources", "📊"),
                ("Writer", "Drafting report", "running", "Generating section 2/5", "✍️"),
                ("Critic", "Reviewing output", "pending", "Waiting for writer", "🔍"),
            ]

            for name, value, status, subtitle, icon in agents_data:
                st.markdown(
                    StatusCard(
                        title=name, value=value, status=status, subtitle=subtitle, icon=icon
                    ).render(),
                    unsafe_allow_html=True,
                )

            st.markdown("</div>", unsafe_allow_html=True)

        with col2:
            # Quick Actions
            st.markdown(
                '<div class="section-title"><span class="icon">⚡</span> Quick Actions</div>',
                unsafe_allow_html=True,
            )

            st.markdown(
                """
            <div class="glass-card">
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <button class="btn-primary" onclick="alert('Starting new crew...')">
                        🚀 Launch New Crew
                    </button>
                    <button class="btn-ghost" onclick="alert('Pausing all agents...')">
                        ⏸️ Pause All Agents
                    </button>
                    <button class="btn-ghost" onclick="alert('Reloading config...')">
                        🔄 Reload Configuration
                    </button>
                </div>
            </div>
            <br>
            """,
                unsafe_allow_html=True,
            )

            # Recent Timeline
            timeline = AgentTimeline(
                [
                    {
                        "time": "2s ago",
                        "title": "Task Completed",
                        "description": "Analyst finished data processing",
                        "status": "completed",
                    },
                    {
                        "time": "5s ago",
                        "title": "Agent Started",
                        "description": "Writer began drafting report",
                        "status": "running",
                    },
                    {
                        "time": "12s ago",
                        "title": "DAG Node Executed",
                        "description": "Search node completed (3 results)",
                        "status": "completed",
                    },
                    {
                        "time": "30s ago",
                        "title": "Crew Initialized",
                        "description": "Research crew with 4 agents ready",
                        "status": "completed",
                    },
                ]
            )
            st.markdown(timeline.render(), unsafe_allow_html=True)

    def _render_dag_tab(self) -> None:
        """Render the DAG visualization tab."""
        col1, col2 = st.columns([3, 2])

        with col1:
            dag = DAGVisualizer(
                [
                    {
                        "name": "🔍 Search Web",
                        "status": "completed",
                        "class": "completed",
                        "deps": [],
                    },
                    {
                        "name": "📊 Analyze Data",
                        "status": "running",
                        "class": "running",
                        "deps": ["Search Web"],
                    },
                    {
                        "name": "✅ Verify Sources",
                        "status": "pending",
                        "class": "root",
                        "deps": ["Search Web"],
                    },
                    {
                        "name": "🧠 Synthesize",
                        "status": "pending",
                        "class": "root",
                        "deps": ["Analyze Data", "Verify Sources"],
                    },
                    {
                        "name": "📝 Write Report",
                        "status": "pending",
                        "class": "root",
                        "deps": ["Synthesize"],
                    },
                ]
            )
            st.markdown(dag.render(), unsafe_allow_html=True)

        with col2:
            st.markdown(
                '<div class="section-title"><span class="icon">⚙️</span> Execution Config</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                """
            <div class="glass-card">
                <div style="display: flex; flex-direction: column; gap: 12px;">
                    <div>
                        <div style="font-size:0.8rem;color:rgba(255,255,255,0.5);margin-bottom:4px;">Max Concurrent Nodes</div>
                        <div class="progress-bar">
                            <div class="progress-bar-fill" style="width: 60%;"></div>
                        </div>
                        <div style="font-size:0.7rem;color:rgba(255,255,255,0.3);margin-top:4px;">3 / 5</div>
                    </div>
                    <div>
                        <div style="font-size:0.8rem;color:rgba(255,255,255,0.5);margin-bottom:4px;">Execution Progress</div>
                        <div class="progress-bar">
                            <div class="progress-bar-fill" style="width: 40%;"></div>
                        </div>
                        <div style="font-size:0.7rem;color:rgba(255,255,255,0.3);margin-top:4px;">2 / 5 nodes complete</div>
                    </div>
                    <div style="margin-top:8px;">
                        <div style="font-size:0.8rem;color:rgba(255,255,255,0.5);">DAG: research_pipeline</div>
                        <div style="font-size:0.7rem;color:rgba(255,255,255,0.3);">Started 45s ago • 2 nodes running</div>
                    </div>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    def _render_swarm_tab(self) -> None:
        """Render the swarm intelligence tab."""
        col1, col2 = st.columns([1, 1])

        with col1:
            st.markdown(
                """
            <div class="glass-card">
                <div class="section-title"><span class="icon">🗳️</span> Consensus Results</div>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <div class="vote-bar">
                        <span class="vote-label">Strongly Agree</span>
                        <div class="vote-track">
                            <div class="vote-fill" style="width: 0%; background: #6366f1;" data-width="75%"></div>
                        </div>
                        <span class="vote-count">3</span>
                    </div>
                    <div class="vote-bar">
                        <span class="vote-label">Agree</span>
                        <div class="vote-track">
                            <div class="vote-fill" style="width: 0%; background: #818cf8;" data-width="50%"></div>
                        </div>
                        <span class="vote-count">2</span>
                    </div>
                    <div class="vote-bar">
                        <span class="vote-label">Abstain</span>
                        <div class="vote-track">
                            <div class="vote-fill" style="width: 0%; background: #a78bfa;" data-width="25%"></div>
                        </div>
                        <span class="vote-count">1</span>
                    </div>
                    <div class="vote-bar">
                        <span class="vote-label">Disagree</span>
                        <div class="vote-track">
                            <div class="vote-fill" style="width: 0%; background: #f87171;" data-width="25%"></div>
                        </div>
                        <span class="vote-count">1</span>
                    </div>
                    <div class="vote-bar">
                        <span class="vote-label">Strongly Disagree</span>
                        <div class="vote-track">
                            <div class="vote-fill" style="width: 0%; background: #ef4444;" data-width="0%"></div>
                        </div>
                        <span class="vote-count">0</span>
                    </div>
                </div>
                <script>
                setTimeout(() => {
                    document.querySelectorAll('.vote-fill').forEach(el => {
                        el.style.width = el.dataset.width;
                    });
                }, 300);
                </script>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with col2:
            st.markdown(
                """
            <div class="glass-card" style="text-align: center;">
                <div class="section-title"><span class="icon">🏆</span> Consensus Decision</div>
                <div style="font-size: 2rem; font-weight: 700; color: #34d399; animation: float 3s ease-in-out infinite;">
                    ✅ APPROVED
                </div>
                <div style="font-size: 0.9rem; color: rgba(255,255,255,0.6); margin: 12px 0;">
                    "Proceed with GPT-4o for complex tasks"
                </div>
                <div style="font-size: 0.8rem; color: rgba(255,255,255,0.4);">
                    Confidence: 87% • 6/7 agents in agreement
                </div>
                <div style="margin-top: 16px; display: flex; gap: 8px; justify-content: center;">
                    <span class="status-badge completed" style="padding:6px 16px;">
                        <span class="dot"></span> 3 Strongly Agree
                    </span>
                    <span class="status-badge running" style="padding:6px 16px;">
                        <span class="dot"></span> 2 Agree
                    </span>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    def _render_tools_tab(self) -> None:
        """Render the tools registry tab."""

        # Try to get real tools
        try:
            from ansiq.tools.discover import list_discovered_tools

            list_discovered_tools()
            tools = []
            from ansiq.tools.discover import _tool_registry

            for name, cls in _tool_registry.items():
                instance = cls()
                tools.append(
                    {
                        "name": name,
                        "description": instance.description,
                        "parameters": [
                            {"name": p.name, "type": p.type} for p in instance.parameters
                        ],
                    }
                )
        except Exception:
            tools = [
                {
                    "name": "web_search",
                    "description": "Search the web for information",
                    "parameters": [
                        {"name": "query", "type": "string"},
                        {"name": "max_results", "type": "integer"},
                    ],
                },
                {
                    "name": "calculate",
                    "description": "Perform mathematical calculations",
                    "parameters": [
                        {"name": "expression", "type": "string"},
                    ],
                },
                {
                    "name": "read_file",
                    "description": "Read contents of a file",
                    "parameters": [
                        {"name": "path", "type": "string"},
                        {"name": "encoding", "type": "string"},
                    ],
                },
            ]

        browser = ToolBrowser(tools)
        st.markdown(browser.render(), unsafe_allow_html=True)

        # Quick Add Tool Section
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            """
        <div class="glass-card">
            <div class="section-title"><span class="icon">➕</span> Register New Tool</div>
            <div style="display: flex; gap: 8px;">
                <input type="text" placeholder="Tool name" style="
                    flex: 1; padding: 10px 16px; border-radius: 10px;
                    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
                    color: white; font-size: 0.9rem;
                ">
                <button class="btn-primary" onclick="alert('Tool registration coming soon!')">
                    ✨ Register
                </button>
            </div>
            <div style="margin-top: 12px; font-size: 0.8rem; color: rgba(255,255,255,0.4);">
                💡 Use @ansiq_tool() decorator in your code to auto-register tools
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    def _render_analytics_tab(self) -> None:
        """Render the analytics tab."""
        col1, col2 = st.columns([1, 1])

        with col1:
            chart = CostChart(
                [
                    {"label": "GPT-4o", "value": 18500},
                    {"label": "GPT-4o-mini", "value": 12000},
                    {"label": "Claude 3.5", "value": 8900},
                    {"label": "Claude Haiku", "value": 5800},
                    {"label": "Total", "value": 45200},
                ]
            )
            st.markdown(chart.render(), unsafe_allow_html=True)

        with col2:
            st.markdown(
                """
            <div class="glass-card">
                <div class="section-title"><span class="icon">📈</span> Performance Metrics</div>
                <div style="display: flex; flex-direction: column; gap: 12px;">
                    <div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="font-size:0.8rem; color: rgba(255,255,255,0.6);">Avg Response Time</span>
                            <span style="font-size:0.8rem; font-weight:600; color: #34d399;">1.2s</span>
                        </div>
                        <div class="progress-bar" style="margin-top:4px;">
                            <div class="progress-bar-fill" style="width: 85%;"></div>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="font-size:0.8rem; color: rgba(255,255,255,0.6);">Success Rate</span>
                            <span style="font-size:0.8rem; font-weight:600; color: #34d399;">97.3%</span>
                        </div>
                        <div class="progress-bar" style="margin-top:4px;">
                            <div class="progress-bar-fill" style="width: 97%;"></div>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="font-size:0.8rem; color: rgba(255,255,255,0.6);">Cache Hit Rate</span>
                            <span style="font-size:0.8rem; font-weight:600; color: #fbbf24;">62.5%</span>
                        </div>
                        <div class="progress-bar" style="margin-top:4px;">
                            <div class="progress-bar-fill" style="width: 62%; background: linear-gradient(90deg, #f59e0b, #fbbf24, #fcd34d);"></div>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="font-size:0.8rem; color: rgba(255,255,255,0.6);">Cost Efficiency</span>
                            <span style="font-size:0.8rem; font-weight:600; color: #818cf8;">$0.02/task</span>
                        </div>
                        <div class="progress-bar" style="margin-top:4px;">
                            <div class="progress-bar-fill" style="width: 78%; background: linear-gradient(90deg, #6366f1, #818cf8, #a78bfa);"></div>
                        </div>
                    </div>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    def _render_footer(self) -> None:
        """Render the dashboard footer."""
        st.markdown(
            """
        <div class="divider"></div>
        <div style="text-align: center; padding: 20px; font-size: 0.8rem; color: rgba(255,255,255,0.2);">
            AnsiQ v0.2.0 — Built with ❤️ and 🧠 —
            <span class="gradient-text">Next-Gen Agent Orchestration</span>
        </div>
        """,
            unsafe_allow_html=True,
        )


def run_dashboard():
    """Entry point to run the AnsiQ dashboard."""
    dashboard = AnsiqDashboard()
    dashboard.run()


if __name__ == "__main__":
    run_dashboard()
