"""
Baby Smith Trading Dashboard - Main Entry Point.

This module provides a Streamlit-based dashboard for monitoring
trading performance and market data. The dashboard has been 
refactored into modular components for better maintainability.

To run the dashboard:
    streamlit run src/agent_smith/dashboard.py
"""

from agent_smith.dashboard.main import main

# Legacy import compatibility
from agent_smith.dashboard.data_fetchers import DashboardDataFetcher
from agent_smith.dashboard.chart_components import ChartManager  
from agent_smith.dashboard.ui_components import UIComponentManager

# Re-export main function for backward compatibility
__all__ = ['main', 'DashboardDataFetcher', 'ChartManager', 'UIComponentManager']

# Entry point when run directly
if __name__ == "__main__":
    main()