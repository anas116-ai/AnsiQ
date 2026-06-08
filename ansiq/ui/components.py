"""Reusable UI Components — inspired by 21st.dev glassmorphism, shadcn/ui clean design, and motionsite.ai animations.

Each component is a standalone HTML/CSS/JS block that can be rendered in Streamlit
with beautiful animations, 3D hover effects, and glassmorphism styling.
"""

from __future__ import annotations

from typing import Any


def get_base_styles() -> str:
    """Return the base CSS styles inspired by 21st.dev + shadcn/ui + motionsite.ai."""
    return """
    <style>
    /* ── Base Reset & Typography (shadcn/ui inspired) ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    .stApp {
        background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 50%, #0f0f23 100%);
    }

    /* ── Glassmorphism Card (21st.dev inspired) ── */
    .glass-card {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 16px;
        padding: 24px;
        transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        position: relative;
        overflow: hidden;
    }

    .glass-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(
            90deg,
            transparent,
            rgba(255, 255, 255, 0.03),
            transparent
        );
        transition: left 0.5s ease;
    }

    .glass-card:hover::before {
        left: 100%;
    }

    .glass-card:hover {
        transform: translateY(-4px) scale(1.01);
        border-color: rgba(99, 102, 241, 0.3);
        box-shadow:
            0 8px 32px rgba(99, 102, 241, 0.1),
            0 1px 4px rgba(0, 0, 0, 0.2);
    }

    /* ── 3D Tilt Card (motionsite.ai inspired) ── */
    .tilt-card {
        perspective: 1000px;
        transform-style: preserve-3d;
    }

    .tilt-card-inner {
        transition: transform 0.5s ease;
        transform-style: preserve-3d;
    }

    .tilt-card:hover .tilt-card-inner {
        transform: rotateX(2deg) rotateY(2deg);
    }

    /* ── Metric Display ── */
    .metric-container {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .metric-value {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #818cf8, #6366f1, #4f46e5);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        line-height: 1.2;
    }

    .metric-label {
        font-size: 0.85rem;
        color: rgba(255, 255, 255, 0.5);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .metric-change {
        font-size: 0.8rem;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 6px;
        display: inline-block;
    }

    .metric-change.positive {
        color: #34d399;
        background: rgba(52, 211, 153, 0.1);
    }

    .metric-change.negative {
        color: #f87171;
        background: rgba(248, 113, 113, 0.1);
    }

    /* ── Status Badge ── */
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }

    .status-badge .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        animation: pulse-dot 2s infinite;
    }

    .status-badge.running { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
    .status-badge.running .dot { background: #818cf8; }
    .status-badge.completed { background: rgba(52, 211, 153, 0.15); color: #34d399; }
    .status-badge.completed .dot { background: #34d399; animation: none; }
    .status-badge.failed { background: rgba(248, 113, 113, 0.15); color: #f87171; }
    .status-badge.failed .dot { background: #f87171; animation: none; }
    .status-badge.pending { background: rgba(251, 191, 36, 0.15); color: #fbbf24; }
    .status-badge.pending .dot { background: #fbbf24; }

    @keyframes pulse-dot {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.5; transform: scale(1.5); }
    }

    /* ── Timeline ── */
    .timeline {
        position: relative;
        padding-left: 24px;
    }

    .timeline::before {
        content: '';
        position: absolute;
        left: 7px;
        top: 0;
        bottom: 0;
        width: 2px;
        background: linear-gradient(to bottom, rgba(99, 102, 241, 0.4), transparent);
    }

    .timeline-item {
        position: relative;
        padding: 8px 0 16px;
        opacity: 0;
        animation: fadeInSlide 0.5s ease forwards;
    }

    .timeline-item::before {
        content: '';
        position: absolute;
        left: -20px;
        top: 12px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #6366f1;
        border: 2px solid rgba(99, 102, 241, 0.3);
        box-shadow: 0 0 12px rgba(99, 102, 241, 0.3);
    }

    .timeline-item.completed::before { background: #34d399; border-color: rgba(52, 211, 153, 0.3); box-shadow: 0 0 12px rgba(52, 211, 153, 0.3); }
    .timeline-item.failed::before { background: #f87171; border-color: rgba(248, 113, 113, 0.3); box-shadow: 0 0 12px rgba(248, 113, 113, 0.3); }
    .timeline-item.running::before { animation: pulse-dot 1.5s infinite; }

    .timeline-time {
        font-size: 0.75rem;
        color: rgba(255, 255, 255, 0.3);
        margin-bottom: 1px;
    }

    .timeline-title {
        font-size: 0.9rem;
        font-weight: 600;
        color: rgba(255, 255, 255, 0.9);
    }

    .timeline-desc {
        font-size: 0.8rem;
        color: rgba(255, 255, 255, 0.5);
        margin-top: 1px;
    }

    /* ── DAG Graph Nodes (21st.dev inspired) ── */
    .dag-node {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 16px;
        border-radius: 10px;
        font-size: 0.85rem;
        font-weight: 500;
        transition: all 0.3s ease;
        cursor: pointer;
        border: 1px solid rgba(255, 255, 255, 0.06);
        background: rgba(255, 255, 255, 0.02);
    }

    .dag-node:hover {
        transform: scale(1.05);
        box-shadow: 0 4px 16px rgba(99, 102, 241, 0.2);
        border-color: rgba(99, 102, 241, 0.3);
    }

    .dag-node.root { border-left: 3px solid #6366f1; }
    .dag-node.completed { border-left: 3px solid #34d399; }
    .dag-node.running { border-left: 3px solid #fbbf24; animation: pulse-border 1.5s infinite; }
    .dag-node.failed { border-left: 3px solid #f87171; }

    @keyframes pulse-border {
        0%, 100% { border-left-color: #fbbf24; }
        50% { border-left-color: #f59e0b; }
    }

    .dag-arrow {
        color: rgba(255, 255, 255, 0.2);
        font-size: 1.2rem;
        margin: 4px 0;
    }

    /* ── Animations (motionsite.ai inspired) ── */
    @keyframes fadeInSlide {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    @keyframes slideUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes scaleIn {
        from { opacity: 0; transform: scale(0.9); }
        to { opacity: 1; transform: scale(1); }
    }

    @keyframes shimmer {
        0% { background-position: -200% center; }
        100% { background-position: 200% center; }
    }

    @keyframes float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-6px); }
    }

    @keyframes glow {
        0%, 100% { box-shadow: 0 0 20px rgba(99, 102, 241, 0.2); }
        50% { box-shadow: 0 0 40px rgba(99, 102, 241, 0.4); }
    }

    .animate-fade-in { animation: fadeIn 0.5s ease forwards; }
    .animate-slide-up { animation: slideUp 0.5s ease forwards; }
    .animate-scale-in { animation: scaleIn 0.4s ease forwards; }
    .animate-float { animation: float 3s ease-in-out infinite; }
    .animate-glow { animation: glow 2s ease-in-out infinite; }

    /* Staggered children animations */
    .stagger-children > * {
        opacity: 0;
        animation: slideUp 0.5s ease forwards;
    }

    .stagger-children > *:nth-child(1) { animation-delay: 0.1s; }
    .stagger-children > *:nth-child(2) { animation-delay: 0.2s; }
    .stagger-children > *:nth-child(3) { animation-delay: 0.3s; }
    .stagger-children > *:nth-child(4) { animation-delay: 0.4s; }
    .stagger-children > *:nth-child(5) { animation-delay: 0.5s; }

    /* ── Gradient Text ── */
    .gradient-text {
        background: linear-gradient(135deg, #818cf8, #6366f1, #a78bfa, #818cf8);
        background-size: 200% auto;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shimmer 3s linear infinite;
    }

    /* ── Particle Background ── */
    .particle-bg {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 0;
        overflow: hidden;
    }

    .particle-bg::before {
        content: '';
        position: absolute;
        width: 400px;
        height: 400px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(99, 102, 241, 0.03) 0%, transparent 70%);
        top: -100px;
        right: -100px;
        animation: float 8s ease-in-out infinite;
    }

    .particle-bg::after {
        content: '';
        position: absolute;
        width: 300px;
        height: 300px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(168, 85, 247, 0.03) 0%, transparent 70%);
        bottom: -50px;
        left: -50px;
        animation: float 10s ease-in-out infinite reverse;
    }

    /* ── shadcn/ui styled button ── */
    .btn-primary {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 20px;
        border-radius: 10px;
        background: linear-gradient(135deg, #6366f1, #4f46e5);
        color: white;
        font-weight: 600;
        font-size: 0.9rem;
        border: none;
        cursor: pointer;
        transition: all 0.3s ease;
        text-decoration: none;
    }

    .btn-primary:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(99, 102, 241, 0.35);
    }

    .btn-ghost {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 20px;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.03);
        color: rgba(255, 255, 255, 0.8);
        font-weight: 500;
        font-size: 0.9rem;
        border: 1px solid rgba(255, 255, 255, 0.08);
        cursor: pointer;
        transition: all 0.3s ease;
    }

    .btn-ghost:hover {
        background: rgba(255, 255, 255, 0.06);
        border-color: rgba(99, 102, 241, 0.3);
    }

    /* ── Tool Card ── */
    .tool-card {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 16px;
        transition: all 0.3s ease;
    }

    .tool-card:hover {
        background: rgba(255, 255, 255, 0.04);
        border-color: rgba(99, 102, 241, 0.2);
        transform: translateX(4px);
    }

    .tool-name {
        font-weight: 600;
        color: rgba(255, 255, 255, 0.9);
        font-size: 0.9rem;
    }

    .tool-desc {
        font-size: 0.8rem;
        color: rgba(255, 255, 255, 0.5);
        margin-top: 2px;
    }

    .tool-param {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 500;
        background: rgba(99, 102, 241, 0.1);
        color: #818cf8;
        margin: 2px 2px;
    }

    /* ── Section Title ── */
    .section-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: rgba(255, 255, 255, 0.9);
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .section-title .icon {
        font-size: 1.2rem;
    }

    /* ── Divider ── */
    .divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.06), transparent);
        margin: 24px 0;
    }

    /* ── Loading Spinner (21st.dev inspired) ── */
    .spinner {
        width: 24px;
        height: 24px;
        border: 2px solid rgba(99, 102, 241, 0.1);
        border-top-color: #6366f1;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        display: inline-block;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    /* ── Progress Bar ── */
    .progress-bar {
        width: 100%;
        height: 4px;
        background: rgba(255, 255, 255, 0.06);
        border-radius: 2px;
        overflow: hidden;
    }

    .progress-bar-fill {
        height: 100%;
        border-radius: 2px;
        background: linear-gradient(90deg, #6366f1, #818cf8, #a78bfa);
        background-size: 200% auto;
        animation: shimmer 2s linear infinite;
        transition: width 0.5s ease;
    }

    /* ── Vote bar chart ── */
    .vote-bar {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 4px 0;
    }

    .vote-label {
        font-size: 0.8rem;
        color: rgba(255, 255, 255, 0.6);
        width: 120px;
        flex-shrink: 0;
    }

    .vote-track {
        flex: 1;
        height: 8px;
        background: rgba(255, 255, 255, 0.04);
        border-radius: 4px;
        overflow: hidden;
    }

    .vote-fill {
        height: 100%;
        border-radius: 4px;
        transition: width 1s ease;
    }

    .vote-count {
        font-size: 0.8rem;
        font-weight: 600;
        color: rgba(255, 255, 255, 0.8);
        width: 30px;
        text-align: right;
    }

    /* ── Responsive Grid ── */
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 16px;
        margin: 16px 0;
    }

    /* ── Scrollbar Styling ── */
    ::-webkit-scrollbar {
        width: 4px;
        height: 4px;
    }

    ::-webkit-scrollbar-track {
        background: transparent;
    }

    ::-webkit-scrollbar-thumb {
        background: rgba(99, 102, 241, 0.3);
        border-radius: 2px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: rgba(99, 102, 241, 0.5);
    }
    </style>
    """


class StatusCard:
    """Glassmorphism status card — 21st.dev inspired design."""

    def __init__(
        self,
        title: str,
        value: str,
        status: str = "running",
        subtitle: str = "",
        icon: str = "",
    ):
        self.title = title
        self.value = value
        self.status = status
        self.subtitle = subtitle
        self.icon = icon

    def render(self) -> str:
        return f"""
        <div class="glass-card animate-scale-in" style="animation-delay: 0.1s;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <div style="font-size: 0.8rem; color: rgba(255,255,255,0.5); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;">
                        {self.icon} {self.title}
                    </div>
                    <div style="font-size: 2rem; font-weight: 700; color: rgba(255,255,255,0.95);">
                        {self.value}
                    </div>
                    {f'<div style="font-size: 0.8rem; color: rgba(255,255,255,0.4); margin-top: 4px;">{self.subtitle}</div>' if self.subtitle else ""}
                </div>
                <div>
                    <span class="status-badge {self.status}">
                        <span class="dot"></span>
                        {self.status.upper()}
                    </span>
                </div>
            </div>
        </div>
        """


class MetricCard:
    """Metric display card — shadcn/ui inspired design with gradient text."""

    def __init__(
        self,
        label: str,
        value: str,
        change: str | None = None,
        change_type: str = "positive",
        icon: str = "",
    ):
        self.label = label
        self.value = value
        self.change = change
        self.change_type = change_type
        self.icon = icon

    def render(self) -> str:
        change_html = ""
        if self.change:
            change_html = f'<span class="metric-change {self.change_type}">{self.change}</span>'

        return f"""
        <div class="glass-card" style="text-align: center;">
            <div class="metric-container">
                <div class="metric-label">{self.icon} {self.label}</div>
                <div class="metric-value">{self.value}</div>
                {change_html}
            </div>
        </div>
        """


class AgentTimeline:
    """Animated timeline of agent events — motionsite.ai smooth animations."""

    def __init__(self, items: list[dict[str, Any]]):
        self.items = items

    def render(self) -> str:
        items_html = ""
        for i, item in enumerate(self.items):
            status = item.get("status", "completed")
            delay = 0.1 * (i + 1)
            items_html += f"""
            <div class="timeline-item {status}" style="animation-delay: {delay}s;">
                <div class="timeline-time">{item.get("time", "")}</div>
                <div class="timeline-title">{item.get("title", "")}</div>
                <div class="timeline-desc">{item.get("description", "")}</div>
            </div>
            """
        return f"""
        <div class="glass-card">
            <div class="section-title"><span class="icon">📋</span> Agent Timeline</div>
            <div class="timeline">{items_html}</div>
        </div>
        """


class DAGVisualizer:
    """DAG flow visualization — clean node-based layout."""

    def __init__(self, nodes: list[dict[str, Any]]):
        self.nodes = nodes

    def render(self) -> str:
        nodes_html = ""
        # Use index-based iteration so we can append a connector arrow
        # between adjacent nodes without relying on dict equality.
        last_index = len(self.nodes) - 1
        for i, node in enumerate(self.nodes):
            node_class = node.get("class", "")
            name = node.get("name", "")
            status = node.get("status", "")
            deps = node.get("deps", [])
            dep_str = (
                f"<span style='font-size:0.7rem;color:rgba(255,255,255,0.3);'>[{', '.join(deps[:2])}]</span>"
                if deps
                else "<span style='font-size:0.7rem;color:rgba(99,102,241,0.5);'>root</span>"
            )

            nodes_html += f"""
            <div class="dag-node {node_class}">
                <span>📌</span>
                <span>{name}</span>
                <span class="status-badge {status}" style="padding:2px 8px;font-size:0.7rem;">
                    <span class="dot"></span>
                    {status}
                </span>
                {dep_str}
            </div>
            """
            if i < last_index:
                nodes_html += '<div class="dag-arrow">↓</div>'

        return f"""
        <div class="glass-card" style="text-align: center;">
            <div class="section-title"><span class="icon">🔀</span> DAG Execution Flow</div>
            <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
                {nodes_html}
            </div>
        </div>
        """


class ToolBrowser:
    """Tool registry browser — clean card layout."""

    def __init__(self, tools: list[dict[str, Any]]):
        self.tools = tools

    def render(self) -> str:
        tools_html = ""
        for tool in self.tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            params = tool.get("parameters", [])
            params_html = "".join(
                f'<span class="tool-param">{p.get("name", "?")}: {p.get("type", "string")}</span>'
                for p in params[:4]
            )
            if len(params) > 4:
                params_html += f'<span class="tool-param">+{len(params) - 4}</span>'

            tools_html += f"""
            <div class="tool-card" style="margin-bottom: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div class="tool-name">🔧 {name}</div>
                        <div class="tool-desc">{desc[:80]}{"..." if len(desc) > 80 else ""}</div>
                    </div>
                    <div style="display: flex; gap: 4px; flex-wrap: wrap; max-width: 200px;">
                        {params_html}
                    </div>
                </div>
            </div>
            """
        return f"""
        <div class="glass-card">
            <div class="section-title"><span class="icon">🔧</span> Registered Tools</div>
            <div style="max-height: 300px; overflow-y: auto;">
                {tools_html or '<div style="color: rgba(255,255,255,0.3); text-align: center; padding: 20px;">No tools registered</div>'}
            </div>
        </div>
        """


class CostChart:
    """Cost analytics display — animated bars."""

    def __init__(self, data: list[dict[str, Any]]):
        self.data = data

    def render(self) -> str:
        max_value = max((d.get("value", 0) for d in self.data), default=1)
        bars_html = ""
        colors = ["#6366f1", "#818cf8", "#a78bfa", "#c4b5fd", "#34d399", "#fbbf24"]

        for i, item in enumerate(self.data):
            label = item.get("label", "")
            value = item.get("value", 0)
            pct = (value / max_value * 100) if max_value > 0 else 0
            color = colors[i % len(colors)]
            0.1 * (i + 1)

            bars_html += f"""
            <div class="vote-bar">
                <span class="vote-label">{label}</span>
                <div class="vote-track">
                    <div class="vote-fill"
                         style="width: 0%; background: {color};"
                         data-width="{pct}%">
                    </div>
                </div>
                <span class="vote-count">{value}</span>
            </div>
            """

        # JavaScript to animate bars on load
        animate_js = """
        <script>
        setTimeout(() => {
            document.querySelectorAll('.vote-fill').forEach(el => {
                el.style.width = el.dataset.width;
            });
        }, 200);
        </script>
        """

        return f"""
        <div class="glass-card">
            <div class="section-title"><span class="icon">📊</span> Usage Analytics</div>
            {bars_html}
            {animate_js}
        </div>
        """
