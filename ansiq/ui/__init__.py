"""Web UI Dashboard — real-time agent monitoring and control.

Provides a beautiful, animated Streamlit-based interface for:
- Monitoring agent execution in real-time
- Visualizing DAG orchestration flows
- Viewing swarm intelligence voting results
- Browsing registered tools
- Analyzing costs and usage metrics
"""

from ansiq.ui.components import (
    AgentTimeline,
    CostChart,
    DAGVisualizer,
    MetricCard,
    StatusCard,
    ToolBrowser,
)
from ansiq.ui.dashboard import AnsiqDashboard

__all__ = [
    "AnsiqDashboard",
    "StatusCard",
    "MetricCard",
    "AgentTimeline",
    "DAGVisualizer",
    "ToolBrowser",
    "CostChart",
]
